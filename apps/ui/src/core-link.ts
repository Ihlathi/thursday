// The overlay window owns the single UI connection to Core (Core allows one UI
// socket). The settings window talks to Core through these Tauri events.
import { emit, listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { CoreClient, type AgentEvent } from './protocol';
import { playPointer, setOverlayMetrics, type OverlayMetrics } from './pointer';
import { captureUtterance, capturing, playSpeech, speechFinished, stopCapture, stopSpeech } from './voice';

interface SocketConfig {
  url: string;
  token: string;
  speak: boolean;
}

export interface OverlayControls {
  summon(origin?: { x: number; y: number }): void;
  dismiss(): void;
  setMode(mode: 'idle' | 'listening' | 'working' | 'speaking'): void;
  setLevel(level: number): void;
}

const MODES: Record<string, 'listening' | 'working' | 'speaking'> = {
  listening: 'listening',
  thinking: 'working',
  acting: 'working',
  awaiting_input: 'listening',
  confirmation_required: 'listening',
  speaking: 'speaking',
};
const TERMINAL = ['completed', 'cancelled', 'error'];

let client: CoreClient | null = null;
let pending: AgentEvent | null = null;
let socketState = 'connecting';
let socketDetail: string | undefined;
let speakReplies = true;
let controls: OverlayControls | null = null;
let answering = false;
let answerHandled = false;

/**
 * Core asked something. Listen for the answer here, in the overlay, rather than
 * making the user find a window: a question you cannot answer by talking is not
 * usable by the person this tool is for. The answer ships as audio; Core
 * transcribes it with the same ElevenLabs path it uses for requests.
 */
async function listenForAnswer(event: AgentEvent) {
  if (!client || answering || capturing()) return;
  answering = true;
  answerHandled = false;
  try {
    // Do not record our own voice reading the question out.
    await speechFinished();
    controls?.summon();
    controls?.setMode('listening');
    void emit('core-state', { state: 'open', detail: 'listening for your answer' });
    const { audio, reason } = await captureUtterance((level) => controls?.setLevel(level));
    // A button press in the settings window answered first; do not answer twice.
    if (answerHandled) return;
    if (!audio) {
      void emit('core-ack', { accepted: false, reason: reason ?? 'Nothing captured.' });
      return;
    }
    const sent =
      event.status === 'confirmation_required'
        ? client.confirmAudio(event, audio)
        : client.replyAudio(String(event.metadata?.reply_to ?? ''), audio);
    if (!sent) void emit('core-ack', { accepted: false, reason: 'Core would not accept the answer.' });
  } finally {
    answering = false;
  }
}

function announce() {
  void emit('core-state', { state: socketState, detail: socketDetail });
}

/** Core marks pointer-bound actions in acting metadata; animate before dispatch. */
function pointerFrom(event: AgentEvent) {
  const pointer = event.metadata?.pointer as { x?: number; y?: number } | undefined;
  if (!pointer || typeof pointer.x !== 'number' || typeof pointer.y !== 'number') return null;
  return pointer as { x: number; y: number };
}

/**
 * One press of the activation shortcut does the obvious next thing: stop a
 * running task, end an in-flight recording, or start listening.
 */
export async function voiceActivate(origin?: { x: number; y: number }) {
  if (!controls) return;
  if (capturing()) {
    // Mid-recording (a request or an answer): end the utterance, do not cancel.
    stopCapture();
    return;
  }
  if (client?.busy) {
    stopSpeech();
    client.cancel();
    return;
  }
  if (socketState !== 'open') {
    void emit('core-ack', { accepted: false, reason: `Socket is ${socketState}.` });
    return;
  }
  stopSpeech();
  controls.summon(origin);
  controls.setMode('listening');
  void emit('core-state', { state: 'open', detail: 'listening' });
  const { audio, reason } = await captureUtterance((level) => controls?.setLevel(level));
  if (!audio) {
    controls.dismiss();
    void emit('core-ack', { accepted: false, reason: reason ?? 'Nothing captured.' });
    return;
  }
  const accepted = client?.requestAudio(audio, speakReplies) ?? false;
  if (!accepted) {
    controls.dismiss();
    void emit('core-ack', { accepted: false, reason: 'Core would not accept the request.' });
  }
}

export async function startCoreLink(metrics: OverlayMetrics, overlay: OverlayControls) {
  setOverlayMetrics(metrics);
  controls = overlay;

  const connect = async () => {
    client?.disconnect();
    const config = await invoke<SocketConfig>('socket_config');
    speakReplies = config.speak;
    client = new CoreClient(config.url, config.token, {
      onEvent(event, taskId) {
        // The overlay is the session indicator: it opens when a task starts and
        // closes itself when the task reaches a terminal status.
        const mode = MODES[event.status];
        if (mode) {
          overlay.summon();
          overlay.setMode(mode);
        } else if (TERMINAL.includes(event.status)) {
          overlay.dismiss();
        }
        if (event.status === 'acting') {
          const pointer = pointerFrom(event);
          if (pointer) playPointer(pointer.x, pointer.y);
        }
        if (event.status === 'speaking' && event.audio) playSpeech(event.audio);
        if (event.status === 'confirmation_required') pending = event;
        if (event.status === 'confirmation_required' || (event.status === 'awaiting_input' && event.metadata?.reply_to)) {
          void listenForAnswer(event);
        }
        if (['completed', 'cancelled', 'error'].includes(event.status)) {
          pending = null;
          answering = false;
        }
        // Mirror every event to the settings window's activity log.
        void emit('agent-event', { event, taskId });
      },
      onState(state, detail) {
        socketState = state;
        socketDetail = detail;
        announce();
      },
    });
    client.connect();
  };

  await connect();
  await listen('settings-changed', () => void connect());
  // The settings window asks for the current state when it opens, because it
  // missed every event emitted before its webview existed.
  await listen('core-state-request', () => announce());
  await listen<string>('core-request', (message) => {
    const accepted = client?.request(message.payload) ?? false;
    void emit('core-ack', {
      accepted,
      reason: accepted ? '' : socketState === 'open' ? 'A task is already running.' : `Socket is ${socketState}.`,
    });
  });
  await listen<boolean>('confirmation-decision', (message) => {
    answerHandled = true;
    stopCapture();
    if (pending && client) client.confirm(pending, message.payload);
    pending = null;
  });
  await listen<{ reply_to: string; text: string }>('core-reply', (message) => {
    answerHandled = true;
    stopCapture();
    client?.reply(message.payload.reply_to, message.payload.text);
  });
  await listen('core-cancel', () => {
    stopSpeech();
    stopCapture();
    const sent = client?.cancel() ?? false;
    void emit('core-ack', { accepted: sent, reason: sent ? '' : 'No active task to cancel.' });
  });
}
