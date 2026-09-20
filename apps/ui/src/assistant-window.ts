import { invoke } from '@tauri-apps/api/core';
import { emitTo, listen } from '@tauri-apps/api/event';
import './assistant.css';

interface Confirmation { confirmation_id: string; call_id: string; action_hash: string; action: string; consequence: string; risk: string; expires_at: number }
interface AgentEvent { status: string; message?: string; metadata?: { reply_to?: string }; confirmation?: Confirmation; audio?: { mime_type: string; encoding: string; data: string } }
interface Envelope { version: string; type: string; request_id: string; task_id?: string; payload: AgentEvent & { message?: string } }
const root = document.querySelector<HTMLDivElement>('#app')!;
root.innerHTML = `<main><h1>JARVIS</h1><p>What would you like help with?</p><button id="connect">Connect to assistant</button><p id="connection" role="status">Not connected</p><section id="messages" role="log" aria-live="polite"></section><section id="consent" aria-label="Action confirmation"></section><form><label for="request">Your request or reply</label><textarea id="request" maxlength="4096" required></textarea><label><input id="speak" type="checkbox"> Read responses aloud</label><div><button id="send" disabled>Send</button><button id="cancel" type="button" disabled>Stop</button></div></form><p id="error" role="alert"></p></main>`;
const el = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
let connected = false;
let task: string | null = null;
let requestId: string | null = null;
let replyTo: string | null = null;
let confirmation: Confirmation | null = null;
let expiry = 0;
let audio: HTMLAudioElement | null = null;
let cancelling = false;
const terminal = new Set(['completed', 'cancelled', 'error']);
function buttons() {
  el<HTMLButtonElement>('send').disabled = !connected || cancelling || (!!task && !replyTo);
  el<HTMLButtonElement>('cancel').disabled = !connected || !task || cancelling;
}
function stopAudio() { audio?.pause(); if (audio) audio.src = ''; audio = null; }
function clearConsent() { clearTimeout(expiry); confirmation = null; el('consent').replaceChildren(); }
function message(text: string) { const p = document.createElement('p'); p.textContent = text; el('messages').append(p); p.scrollIntoView({ block: 'nearest' }); }
async function send(type: string, payload: object, id: string = crypto.randomUUID()) {
  await invoke('core_send', { json: JSON.stringify({ version: '1.0', type, request_id: id, task_id: task, payload }) });
}
function activity(status: string) { void emitTo('main', 'jarvis-agent-status', status); }
function fail(error: unknown) { el('error').textContent = String(error); }
el('connect').onclick = async () => {
  el<HTMLButtonElement>('connect').disabled = true;
  el('connection').textContent = 'Connecting…';
  try { await invoke('core_connect'); } catch (error) { fail(error); el<HTMLButtonElement>('connect').disabled = false; }
};
await listen<string>('core-connection', ({ payload }) => {
  connected = payload === 'connected';
  el('connection').textContent = connected ? 'Connected to JARVIS Core' : payload;
  el<HTMLButtonElement>('connect').disabled = connected;
  if (!connected) { task = null; requestId = null; replyTo = null; cancelling = false; clearConsent(); stopAudio(); activity('cancelled'); }
  buttons();
});
await listen<Envelope>('core-message', ({ payload: frame }) => {
  if (frame.version !== '1.0') return;
  if (frame.type === 'error') { fail(frame.payload.message ?? 'Core rejected the request'); if (frame.request_id === requestId) { task = null; requestId = null; clearConsent(); stopAudio(); activity('error'); } buttons(); return; }
  if (frame.type !== 'agent_event' || frame.task_id !== task || frame.request_id !== requestId) return;
  const event = frame.payload;
  if (event.status === 'debug') return;
  if (cancelling && !terminal.has(event.status)) return;
  if (event.status !== 'debug') { message(event.message ?? event.status); activity(event.status); }
  clearConsent();
  replyTo = event.status === 'awaiting_input' ? event.metadata?.reply_to ?? null : null;
  if (event.status === 'confirmation_required' && event.confirmation) {
    confirmation = event.confirmation;
    const c = confirmation;
    for (const [label, value] of [['Action', c.action], ['Consequence', c.consequence], ['Risk', c.risk], ['Expires', new Date(c.expires_at * 1000).toLocaleString()]]) {
      const p = document.createElement('p'); p.textContent = `${label}: ${value}`; el('consent').append(p);
    }
    for (const approved of [false, true]) {
      const button = document.createElement('button'); button.textContent = approved ? 'Approve this action' : 'Do not proceed';
      button.disabled = Date.now() >= c.expires_at * 1000;
      button.onclick = async () => {
        if (confirmation !== c || Date.now() >= c.expires_at * 1000) return;
        clearConsent();
        try { await send('confirmation_response', { confirmation_id: c.confirmation_id, call_id: c.call_id, action_hash: c.action_hash, approved }); } catch (error) { fail(error); }
      };
      el('consent').append(button);
    }
    expiry = window.setTimeout(() => { clearConsent(); message('This approval has expired.'); }, Math.max(0, c.expires_at * 1000 - Date.now()));
  }
  if (event.status === 'speaking' && event.audio?.mime_type === 'audio/mpeg' && event.audio.encoding === 'base64' && event.audio.data.length <= 2_800_000) {
    stopAudio(); audio = new Audio(`data:audio/mpeg;base64,${event.audio.data}`); void audio.play().catch(() => message('Audio could not play. Please read the response above.'));
  }
  if (terminal.has(event.status)) { task = null; requestId = null; replyTo = null; cancelling = false; if (event.status !== 'completed') stopAudio(); }
  buttons();
});
root.querySelector('form')!.onsubmit = async (event) => {
  event.preventDefault(); if (!connected || cancelling || (task && !replyTo)) return;
  const input = el<HTMLTextAreaElement>('request'); const text = input.value.trim(); if (!text) return;
  el('error').textContent = ''; stopAudio();
  try {
    if (task && replyTo) { await send('user_reply', { reply_to: replyTo, text }); replyTo = null; }
    else { task = crypto.randomUUID(); requestId = crypto.randomUUID(); await send('user_request', { text, speak: el<HTMLInputElement>('speak').checked }, requestId); }
    input.value = ''; activity('thinking'); buttons();
  } catch (error) { task = null; requestId = null; fail(error); buttons(); }
};
el('cancel').onclick = async () => { if (!task) return; stopAudio(); clearConsent(); replyTo = null; cancelling = true; activity('cancelled'); buttons(); try { await send('cancel', { reason: 'User cancelled' }); } catch (error) { fail(error); } };
buttons();

