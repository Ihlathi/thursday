import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import NativeWebSocket from '@tauri-apps/plugin-websocket';

type JsonObject = Record<string, unknown>;

interface Envelope {
  version: '1.0';
  type: string;
  request_id: string;
  task_id?: string;
  payload: JsonObject;
}

interface Confirmation {
  confirmation_id: string;
  call_id: string;
  action_hash: string;
  action: string;
  consequence: string;
  risk: string;
  expires_at: number;
}

interface SummonEvent {
  active: boolean;
  x: number;
  y: number;
}

interface CoreConfig {
  url: string;
  token: string;
}

const byId = <T extends HTMLElement>(id: string) => document.querySelector<T>(`#${id}`)!;
const assistant = byId<HTMLElement>('assistant');
const connectionDot = byId<HTMLElement>('connection-dot');
const connectionLabel = byId<HTMLElement>('connection-label');
const connectionHelp = byId<HTMLElement>('connection-help');
const statusOrb = byId<HTMLElement>('status-orb');
const statusLabel = byId<HTMLElement>('status-heading');
const statusMessage = byId<HTMLElement>('status-message');
const activity = byId<HTMLOListElement>('activity');
const requestForm = byId<HTMLFormElement>('request-form');
const requestLabel = byId<HTMLLabelElement>('request-label');
const requestInput = byId<HTMLTextAreaElement>('request-input');
const sendButton = byId<HTMLButtonElement>('send-button');
const voiceButton = byId<HTMLButtonElement>('voice-button');
const speakToggle = byId<HTMLInputElement>('speak-toggle');
const cancelButton = byId<HTMLButtonElement>('cancel-button');
const confirmationPanel = byId<HTMLElement>('confirmation');
const approveButton = byId<HTMLButtonElement>('approve-button');
const denyButton = byId<HTMLButtonElement>('deny-button');

const canvas = document.createElement('canvas');
canvas.setAttribute('aria-hidden', 'true');
document.querySelector('#app')!.prepend(canvas);
const ctx = canvas.getContext('2d', { alpha: true })!;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let overlayActive = false;
let animationStarted = 0;
let animationFrame = 0;
let width = innerWidth;
let height = innerHeight;
let originX = width / 2;
let originY = height / 2;

let socket: NativeWebSocket | null = null;
let removeSocketListener: (() => void) | null = null;
let connected = false;
let connecting = false;
let activeTaskId: string | null = null;
let activeRequestId: string | null = null;
let pendingReplyTo: string | null = null;
let pendingConfirmation: Confirmation | null = null;
let handshakeResolve: (() => void) | null = null;
let handshakeReject: ((reason: Error) => void) | null = null;
let recorder: MediaRecorder | null = null;
let recordingStream: MediaStream | null = null;
let recordingChunks: Blob[] = [];
let discardRecording = false;
let playback: HTMLAudioElement | null = null;

const terminalStatuses = new Set(['completed', 'cancelled', 'error']);
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const freshId = (prefix: string) => `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`;

function resize() {
  width = innerWidth;
  height = innerHeight;
  const scale = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  if (overlayActive) draw(performance.now());
}

function ring(radius: number, progress: number) {
  const alpha = clamp(progress * 12) * (1 - clamp((progress - 0.78) / 0.22));
  if (radius < 2 || alpha <= 0) return;
  const band = 32 + progress * 65;
  const gradient = ctx.createRadialGradient(
    originX, originY, Math.max(0, radius - band), originX, originY, radius + 18,
  );
  gradient.addColorStop(0, 'rgba(175,222,250,0)');
  gradient.addColorStop(0.45, `rgba(175,222,250,${0.025 * alpha})`);
  gradient.addColorStop(0.76, `rgba(205,237,255,${0.13 * alpha})`);
  gradient.addColorStop(band / (band + 18), `rgba(244,252,255,${0.64 * alpha})`);
  gradient.addColorStop(1, 'rgba(175,222,250,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
}

function edge(length: number, distance: number, contactPoint: number, radius: number) {
  if (radius <= distance) return;
  const reach = Math.sqrt(radius * radius - distance * distance);
  const start = Math.max(0, contactPoint - reach);
  const end = Math.min(length, contactPoint + reach);
  const contact = clamp((radius - distance) / 35);
  const bloom = ctx.createLinearGradient(0, 0, 0, 150);
  bloom.addColorStop(0, `rgba(187,226,250,${0.24 * contact})`);
  bloom.addColorStop(0.4, `rgba(180,224,250,${0.035 * contact})`);
  bloom.addColorStop(1, 'rgba(180,224,250,0)');
  ctx.save();
  ctx.beginPath();
  ctx.rect(start, 0, end - start, 150);
  ctx.clip();
  ctx.fillStyle = bloom;
  ctx.fillRect(0, 0, length, 150);
  ctx.shadowColor = 'rgba(196,234,255,0.8)';
  ctx.shadowBlur = 12;
  ctx.fillStyle = `rgba(236,249,255,${0.78 * contact})`;
  ctx.fillRect(start, 0, end - start, 1);
  ctx.restore();
}

function draw(now: number) {
  cancelAnimationFrame(animationFrame);
  const progress = reducedMotion.matches ? 1 : clamp((now - animationStarted) / 500);
  const cornerDistances = [
    Math.hypot(originX, originY),
    Math.hypot(width - originX, originY),
    Math.hypot(originX, height - originY),
    Math.hypot(width - originX, height - originY),
  ];
  const radius = (1 - Math.pow(1 - progress, 1.65)) * (Math.max(...cornerDistances) + 2);
  ctx.clearRect(0, 0, width, height);
  ring(radius, progress);
  edge(width, originY, originX, radius);
  ctx.save(); ctx.translate(width, height); ctx.rotate(Math.PI);
  edge(width, height - originY, width - originX, radius); ctx.restore();
  ctx.save(); ctx.translate(0, height); ctx.rotate(-Math.PI / 2);
  edge(height, originX, height - originY, radius); ctx.restore();
  ctx.save(); ctx.translate(width, 0); ctx.rotate(Math.PI / 2);
  edge(height, width - originX, originY, radius); ctx.restore();
  if (overlayActive && progress < 1) animationFrame = requestAnimationFrame(draw);
  else if (overlayActive) canvas.classList.add('settled');
}

function setOverlay(active: boolean, origin?: Pick<SummonEvent, 'x' | 'y'>) {
  overlayActive = active;
  cancelAnimationFrame(animationFrame);
  canvas.classList.remove('settled');
  canvas.classList.toggle('visible', active);
  assistant.classList.toggle('visible', active);
  assistant.setAttribute('aria-hidden', String(!active));
  if (active) {
    originX = clamp((origin?.x ?? width / 2) / width) * width;
    originY = clamp((origin?.y ?? height / 2) / height) * height;
    animationStarted = performance.now();
    draw(animationStarted);
    window.setTimeout(() => requestInput.focus(), reducedMotion.matches ? 0 : 350);
  }
}

function setConnection(state: 'connecting' | 'connected' | 'disconnected', detail?: string) {
  connectionDot.dataset.state = state;
  connectionLabel.textContent = state === 'connected' ? 'Connected' : state === 'connecting' ? 'Connecting' : 'Disconnected';
  connectionHelp.hidden = state !== 'disconnected';
  connected = state === 'connected';
  if (!activeTaskId) setComposerEnabled(connected);
  if (state === 'connected') {
    updateStatus('ready', 'Ready', 'Tell me what you would like to do.');
  } else if (state === 'disconnected') {
    updateStatus('error', 'Connection needed', detail ?? 'Core is not available.');
  }
}

function updateStatus(status: string, label: string, message: string) {
  statusOrb.dataset.status = status;
  statusLabel.textContent = label;
  statusMessage.textContent = message;
}

function setComposerEnabled(enabled: boolean) {
  requestInput.disabled = !enabled;
  sendButton.disabled = !enabled;
  voiceButton.disabled = !enabled || !navigator.mediaDevices?.getUserMedia;
}

function appendActivity(status: string, message: string) {
  if (!message) return;
  const last = activity.lastElementChild;
  if (last?.textContent === message) return;
  const item = document.createElement('li');
  item.dataset.status = status;
  item.textContent = message;
  activity.append(item);
  while (activity.children.length > 8) activity.firstElementChild?.remove();
  item.scrollIntoView({ block: 'nearest' });
}

function envelope(type: string, payload: JsonObject, taskId?: string): Envelope {
  const message: Envelope = { version: '1.0', type, request_id: freshId('req'), payload };
  if (taskId) message.task_id = taskId;
  return message;
}

async function sendEnvelope(message: Envelope) {
  if (!socket || !connected) throw new Error('Core is not connected.');
  await socket.send(JSON.stringify(message));
}

function socketText(message: unknown): string | null {
  if (typeof message === 'string') return message;
  if (!message || typeof message !== 'object') return null;
  const data = (message as { data?: unknown }).data;
  if (typeof data === 'string') return data;
  if (Array.isArray(data)) return new TextDecoder().decode(new Uint8Array(data));
  return null;
}

function handleSocketMessage(rawMessage: unknown) {
  const text = socketText(rawMessage);
  if (!text) {
    if ((rawMessage as { type?: string })?.type === 'Close') handleDisconnect('Core closed the connection.');
    return;
  }
  let message: Envelope;
  try {
    message = JSON.parse(text) as Envelope;
  } catch {
    handleDisconnect('Core sent an invalid response.');
    return;
  }

  if (message.type === 'hello_ack' && message.payload.role === 'ui') {
    handshakeResolve?.();
    handshakeResolve = null;
    handshakeReject = null;
    return;
  }
  if (message.type === 'error') {
    const errorText = typeof message.payload.message === 'string' ? message.payload.message : 'Core rejected the request.';
    appendActivity('error', errorText);
    updateStatus('error', 'Request error', errorText);
    if (message.request_id === activeRequestId) finishTask();
    return;
  }
  if (message.type !== 'agent_event' || message.task_id !== activeTaskId) return;
  handleAgentEvent(message.payload);
}

function handleAgentEvent(payload: JsonObject) {
  const status = typeof payload.status === 'string' ? payload.status : 'error';
  const message = typeof payload.message === 'string' ? payload.message : status.replaceAll('_', ' ');
  if (status !== 'debug') appendActivity(status, message);
  updateStatus(status, status.replaceAll('_', ' '), message);

  if (status === 'confirmation_required' && payload.confirmation) {
    showConfirmation(payload.confirmation as unknown as Confirmation);
  } else if (status === 'awaiting_input') {
    const metadata = payload.metadata as JsonObject | undefined;
    pendingReplyTo = typeof metadata?.reply_to === 'string' ? metadata.reply_to : null;
    requestLabel.textContent = 'Your answer';
    requestInput.placeholder = 'Type your answer…';
    setComposerEnabled(Boolean(pendingReplyTo));
    requestInput.focus();
  } else if (status === 'speaking' && payload.audio) {
    playAudio(payload.audio as JsonObject);
  }

  if (terminalStatuses.has(status)) finishTask();
}

function showConfirmation(confirmation: Confirmation) {
  pendingConfirmation = confirmation;
  byId('confirmation-action').textContent = confirmation.action;
  byId('confirmation-consequence').textContent = confirmation.consequence;
  byId('confirmation-risk').textContent = confirmation.risk.replaceAll('_', ' ');
  byId('confirmation-expiry').textContent = new Date(confirmation.expires_at * 1000).toLocaleTimeString();
  confirmationPanel.hidden = false;
  approveButton.disabled = false;
  denyButton.disabled = false;
  approveButton.focus();
}

async function answerConfirmation(approved: boolean) {
  if (!pendingConfirmation || !activeTaskId) return;
  approveButton.disabled = true;
  denyButton.disabled = true;
  const confirmation = pendingConfirmation;
  pendingConfirmation = null;
  confirmationPanel.hidden = true;
  await sendEnvelope(envelope('confirmation_response', {
    confirmation_id: confirmation.confirmation_id,
    call_id: confirmation.call_id,
    action_hash: confirmation.action_hash,
    approved,
  }, activeTaskId));
  updateStatus('thinking', approved ? 'Approved' : 'Denied', approved ? 'Continuing the task…' : 'Stopping safely…');
}

async function startTextRequest(text: string) {
  activeTaskId = freshId('task');
  const requestId = freshId('request');
  activeRequestId = requestId;
  activity.replaceChildren();
  setComposerEnabled(false);
  cancelButton.disabled = false;
  updateStatus('thinking', 'Starting', 'Sending your request securely to Core…');
  const message: Envelope = {
    version: '1.0',
    type: 'user_request',
    request_id: requestId,
    task_id: activeTaskId,
    payload: { text, speak: speakToggle.checked },
  };
  try {
    await sendEnvelope(message);
  } catch (error) {
    failLocal(error);
  }
}

async function startAudioRequest(audio: JsonObject) {
  activeTaskId = freshId('task');
  const requestId = freshId('request');
  activeRequestId = requestId;
  activity.replaceChildren();
  setComposerEnabled(false);
  cancelButton.disabled = false;
  updateStatus('thinking', 'Uploading voice request', 'Sending the recording securely to Core…');
  try {
    await sendEnvelope({
      version: '1.0',
      type: 'user_request',
      request_id: requestId,
      task_id: activeTaskId,
      payload: { audio, speak: speakToggle.checked },
    });
  } catch (error) {
    failLocal(error);
  }
}

function finishTask() {
  activeTaskId = null;
  activeRequestId = null;
  pendingReplyTo = null;
  pendingConfirmation = null;
  confirmationPanel.hidden = true;
  cancelButton.disabled = true;
  requestLabel.textContent = 'What would you like me to do?';
  requestInput.placeholder = 'Type a request…';
  setComposerEnabled(connected);
}

function failLocal(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  appendActivity('error', message);
  updateStatus('error', 'Could not continue', message);
  finishTask();
}

function stopLocalMedia() {
  discardRecording = true;
  if (recorder?.state === 'recording') recorder.stop();
  recorder = null;
  recordingStream?.getTracks().forEach((track) => track.stop());
  recordingStream = null;
  recordingChunks = [];
  voiceButton.setAttribute('aria-pressed', 'false');
  voiceButton.setAttribute('aria-label', 'Start voice request');
  voiceButton.classList.remove('recording');
  playback?.pause();
  playback = null;
}

async function cancelTask() {
  stopLocalMedia();
  if (!activeTaskId) return;
  cancelButton.disabled = true;
  updateStatus('cancelled', 'Cancelling', 'Waiting for Core to stop the task safely…');
  try {
    await sendEnvelope(envelope('cancel', { reason: 'User cancelled' }, activeTaskId));
  } catch (error) {
    failLocal(error);
  }
}

async function submitRequest() {
  const text = requestInput.value.trim();
  if (!text) return;
  requestInput.value = '';
  if (activeTaskId && pendingReplyTo) {
    const replyTo = pendingReplyTo;
    pendingReplyTo = null;
    setComposerEnabled(false);
    await sendEnvelope(envelope('user_reply', { reply_to: replyTo, text }, activeTaskId));
    updateStatus('thinking', 'Answer received', 'Continuing the task…');
    return;
  }
  if (!activeTaskId) await startTextRequest(text);
}

function recordingMimeType(): string | null {
  for (const mime of ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/ogg']) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return null;
}

async function toggleRecording() {
  if (recorder?.state === 'recording') {
    recorder.stop();
    return;
  }
  if (activeTaskId) return;
  try {
    const mimeType = recordingMimeType();
    if (!mimeType) throw new Error('This system does not provide a supported voice recording format.');
    recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    discardRecording = false;
    recordingChunks = [];
    recorder = new MediaRecorder(recordingStream, { mimeType });
    recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size) recordingChunks.push(event.data);
    });
    recorder.addEventListener('stop', async () => {
      const blob = new Blob(recordingChunks, { type: mimeType });
      recordingStream?.getTracks().forEach((track) => track.stop());
      recordingStream = null;
      recorder = null;
      voiceButton.setAttribute('aria-pressed', 'false');
      voiceButton.setAttribute('aria-label', 'Start voice request');
      voiceButton.classList.remove('recording');
      if (discardRecording) {
        recordingChunks = [];
        return;
      }
      if (!recordingChunks.length) return;
      if (blob.size > 2_000_000) {
        failLocal(new Error('The recording is larger than 2 MB. Please record a shorter request.'));
        return;
      }
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let binary = '';
      for (let index = 0; index < bytes.length; index += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
      }
      const protocolMime = mimeType.startsWith('audio/ogg') ? 'audio/ogg' : 'audio/webm';
      await startAudioRequest({ mime_type: protocolMime, encoding: 'base64', data: btoa(binary) });
    }, { once: true });
    recorder.start();
    voiceButton.setAttribute('aria-pressed', 'true');
    voiceButton.setAttribute('aria-label', 'Stop and send voice request');
    voiceButton.classList.add('recording');
    updateStatus('listening', 'Listening', 'Select the microphone button again when you are finished.');
  } catch (error) {
    failLocal(error);
  }
}

function playAudio(audio: JsonObject) {
  if (audio.mime_type !== 'audio/mpeg' || typeof audio.data !== 'string') return;
  playback?.pause();
  playback = new Audio(`data:audio/mpeg;base64,${audio.data}`);
  playback.play().catch((error) => appendActivity('error', `Audio playback failed: ${String(error)}`));
}

async function disconnectSocket() {
  removeSocketListener?.();
  removeSocketListener = null;
  if (socket) await socket.disconnect().catch(() => undefined);
  socket = null;
}

function handleDisconnect(detail: string) {
  handshakeReject?.(new Error(detail));
  handshakeResolve = null;
  handshakeReject = null;
  stopLocalMedia();
  if (activeTaskId) {
    appendActivity('error', 'The Core connection ended, so the current task was cancelled.');
    finishTask();
  }
  setConnection('disconnected', detail);
}

async function connectCore() {
  if (connecting || connected || !isTauri()) return;
  connecting = true;
  setConnection('connecting');
  await disconnectSocket();
  try {
    const config = await invoke<CoreConfig>('core_connection_config');
    socket = await NativeWebSocket.connect(config.url, {
      maxMessageSize: 3_000_000,
      maxFrameSize: 3_000_000,
    });
    removeSocketListener = socket.addListener(handleSocketMessage);
    const handshake = new Promise<void>((resolve, reject) => {
      handshakeResolve = resolve;
      handshakeReject = reject;
      window.setTimeout(() => reject(new Error('Core authentication timed out.')), 5000);
    });
    await socket.send(JSON.stringify(envelope('hello', { role: 'ui', token: config.token })));
    await handshake;
    setConnection('connected');
  } catch (error) {
    await disconnectSocket();
    setConnection('disconnected', error instanceof Error ? error.message : String(error));
  } finally {
    connecting = false;
  }
}

requestForm.addEventListener('submit', (event) => {
  event.preventDefault();
  submitRequest().catch(failLocal);
});
requestInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    requestForm.requestSubmit();
  }
});
voiceButton.addEventListener('click', () => toggleRecording());
cancelButton.addEventListener('click', () => cancelTask());
approveButton.addEventListener('click', () => answerConfirmation(true).catch(failLocal));
denyButton.addEventListener('click', () => answerConfirmation(false).catch(failLocal));
byId('retry-button').addEventListener('click', () => connectCore());
byId('close-button').addEventListener('click', async () => {
  setOverlay(false);
  if (isTauri()) await invoke('set_overlay_active', { active: false });
});

addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && overlayActive) {
    setOverlay(false);
    if (isTauri()) invoke('set_overlay_active', { active: false }).catch(() => undefined);
  }
});
addEventListener('resize', resize);
resize();
setComposerEnabled(false);

if (isTauri()) {
  await listen<SummonEvent>('jarvis-toggle', (event) => setOverlay(event.payload.active, event.payload));
  await invoke('overlay_ready');
  await connectCore();
} else {
  setOverlay(true);
  setConnection('disconnected', 'Browser preview mode does not connect to Core.');
}
