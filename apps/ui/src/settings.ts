// The only window this app ever shows. Opened from the system tray.
import { invoke } from '@tauri-apps/api/core';
import { emit, listen } from '@tauri-apps/api/event';
import type { AgentEvent } from './protocol';

interface Settings {
  gemini_api_key: string;
  gemini_model: string;
  elevenlabs_api_key: string;
  elevenlabs_voice_id: string;
  model_mode: string;
  core_port: number;
  python_path: string;
  repo_path: string;
  autostart_core: boolean;
  start_bridge: boolean;
  speak_replies: boolean;
  ui_token: string;
  platform_token: string;
}

const pick = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const text = ['gemini_api_key', 'gemini_model', 'elevenlabs_api_key', 'elevenlabs_voice_id', 'python_path', 'repo_path'] as const;
const log = pick<HTMLOListElement>('events');
const coreState = pick<HTMLSpanElement>('core-state');
const processState = pick<HTMLSpanElement>('process-state');
const saveState = pick<HTMLParagraphElement>('save-state');
const confirmBox = pick<HTMLDivElement>('confirm');
const replyBox = pick<HTMLDivElement>('reply');
let loaded: Settings;

function note(message: string) {
  const item = document.createElement('li');
  item.textContent = message;
  log.prepend(item);
  while (log.childElementCount > 80) log.lastElementChild?.remove();
}

async function load() {
  loaded = await invoke<Settings>('get_settings');
  for (const key of text) pick<HTMLInputElement>(key).value = String(loaded[key] ?? '');
  pick<HTMLSelectElement>('model_mode').value = loaded.model_mode;
  pick<HTMLInputElement>('core_port').value = String(loaded.core_port);
  pick<HTMLInputElement>('autostart_core').checked = loaded.autostart_core;
  pick<HTMLInputElement>('start_bridge').checked = loaded.start_bridge;
  pick<HTMLInputElement>('speak_replies').checked = loaded.speak_replies;
  await refreshCore();
}

function collect(): Settings {
  const next = { ...loaded };
  for (const key of text) next[key] = pick<HTMLInputElement>(key).value.trim();
  next.model_mode = pick<HTMLSelectElement>('model_mode').value;
  next.core_port = Number(pick<HTMLInputElement>('core_port').value) || 8765;
  next.autostart_core = pick<HTMLInputElement>('autostart_core').checked;
  next.start_bridge = pick<HTMLInputElement>('start_bridge').checked;
  next.speak_replies = pick<HTMLInputElement>('speak_replies').checked;
  return next;
}

async function refreshCore() {
  try {
    const status = await invoke<boolean[]>('core_status');
    const [core, bridge] = Array.isArray(status) ? status : [Boolean(status), false];
    processState.textContent = `Core ${core ? 'running' : 'stopped'} · bridge ${bridge ? 'running' : 'stopped'}`;
  } catch (error) {
    processState.textContent = `status unavailable: ${error}`;
  }
}

pick<HTMLButtonElement>('save').addEventListener('click', async () => {
  loaded = collect();
  try {
    await invoke('save_settings', { settings: loaded });
    saveState.textContent = 'Saved. Restart Core to apply provider changes.';
  } catch (error) {
    saveState.textContent = `Could not save: ${error}`;
  }
});

// Every control reports its outcome: a button that silently fails is worse
// than one that says why.
async function act(what: string, run: () => Promise<unknown>) {
  saveState.textContent = `${what}…`;
  try {
    await run();
    saveState.textContent = `${what}: ok`;
  } catch (error) {
    saveState.textContent = `${what} failed: ${error}`;
  }
  await refreshCore();
}

pick<HTMLButtonElement>('start').addEventListener('click', async () => {
  await act('Start Core', () => invoke('core_start'));
  // Core needs a moment to bind the port before the socket can connect.
  setTimeout(refreshCore, 1200);
});

pick<HTMLButtonElement>('stop').addEventListener('click', () => act('Stop Core', () => invoke('core_stop')));

// An orphaned Core from a previous `tauri dev` restart keeps the port and the
// old token, so the UI gets rejected while everything looks healthy.
pick<HTMLButtonElement>('free').addEventListener('click', async () => {
  try {
    saveState.textContent = await invoke<string>('free_port');
  } catch (error) {
    saveState.textContent = `Free port failed: ${error}`;
  }
  await refreshCore();
});

pick<HTMLButtonElement>('send').addEventListener('click', async () => {
  const value = pick<HTMLInputElement>('request').value.trim();
  if (!value) return;
  // The overlay owns the socket, so it answers with core-ack.
  await act('Send', () => invoke('send_request', { text: value }));
});

pick<HTMLButtonElement>('cancel').addEventListener('click', () => act('Cancel', async () => emit('core-cancel', {})));
pick<HTMLButtonElement>('approve').addEventListener('click', () => {
  void emit('confirmation-decision', true);
  confirmBox.hidden = true;
});
pick<HTMLButtonElement>('deny').addEventListener('click', () => {
  void emit('confirmation-decision', false);
  confirmBox.hidden = true;
});

let replyTo = '';
pick<HTMLButtonElement>('reply-send').addEventListener('click', () => {
  const value = pick<HTMLInputElement>('reply-text').value.trim();
  if (!value || !replyTo) return;
  void emit('core-reply', { reply_to: replyTo, text: value });
  pick<HTMLInputElement>('reply-text').value = '';
  replyBox.hidden = true;
});

let overlayAnswered = false;
await listen<{ state: string; detail?: string }>('core-state', (message) => {
  overlayAnswered = true;
  const { state, detail } = message.payload;
  coreState.textContent = `Socket: ${state}${detail ? ` (${detail})` : ''}`;
});

// Whether the overlay actually accepted the request it was handed.
await listen<{ accepted: boolean; reason: string }>('core-ack', (message) => {
  const { accepted, reason } = message.payload;
  if (!accepted) saveState.textContent = `Not sent — ${reason}`;
});

await listen<{ event: AgentEvent; taskId: string }>('agent-event', (message) => {
  const event = message.payload.event;
  const detail = event.message ?? event.error?.message ?? JSON.stringify(event.metadata ?? {});
  note(`${event.status} — ${detail}`);
  if (event.status === 'confirmation_required' && event.confirmation) {
    // Render the exact action, consequence, risk and expiry Core sent.
    pick('confirm-action').textContent = event.confirmation.action;
    pick('confirm-consequence').textContent = event.confirmation.consequence;
    pick('confirm-risk').textContent = event.confirmation.risk;
    pick('confirm-expiry').textContent = new Date(event.confirmation.expires_at * 1000).toLocaleTimeString();
    confirmBox.hidden = false;
  }
  if (event.status === 'awaiting_input') {
    replyTo = String(event.metadata?.reply_to ?? '');
    pick('reply-question').textContent = event.message ?? 'Core asked a question.';
    replyBox.hidden = !replyTo;
  }
  if (['completed', 'cancelled', 'error'].includes(event.status)) {
    confirmBox.hidden = true;
    replyBox.hidden = true;
  }
});

await load();
// The overlay was already connected before this window existed; ask it to
// repeat its current socket state.
await emit('core-state-request', {});
// Silence here means the overlay webview never came up, which would make Send
// and Cancel look broken even though the panel is fine.
setTimeout(() => {
  if (!overlayAnswered) coreState.textContent = 'Socket: overlay not responding';
}, 1500);
setInterval(refreshCore, 4000);
