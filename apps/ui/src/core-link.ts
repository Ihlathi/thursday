// The overlay window owns the single UI connection to Core (Core allows one UI
// socket). The settings window talks to Core through these Tauri events.
import { emit, listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { CoreClient, type AgentEvent } from './protocol';
import { playPointer, setOverlayMetrics, type OverlayMetrics } from './pointer';

interface SocketConfig {
  url: string;
  token: string;
}

export interface OverlayControls {
  summon(origin?: { x: number; y: number }): void;
  dismiss(): void;
  setMode(mode: 'idle' | 'listening' | 'working' | 'speaking'): void;
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

/** Core marks pointer-bound actions in acting metadata; animate before dispatch. */
function pointerFrom(event: AgentEvent) {
  const pointer = event.metadata?.pointer as { x?: number; y?: number } | undefined;
  if (!pointer || typeof pointer.x !== 'number' || typeof pointer.y !== 'number') return null;
  return pointer as { x: number; y: number };
}

export async function startCoreLink(metrics: OverlayMetrics, overlay: OverlayControls) {
  setOverlayMetrics(metrics);

  const connect = async () => {
    client?.disconnect();
    const config = await invoke<SocketConfig>('socket_config');
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
        if (event.status === 'confirmation_required') pending = event;
        if (['completed', 'cancelled', 'error'].includes(event.status)) pending = null;
        // Mirror every event to the settings window's activity log.
        void emit('agent-event', { event, taskId });
      },
      onState(state, detail) {
        void emit('core-state', { state, detail });
      },
    });
    client.connect();
  };

  await connect();
  await listen('settings-changed', () => void connect());
  await listen<string>('core-request', (message) => {
    if (!client?.request(message.payload)) void emit('core-state', { state: 'closed', detail: 'Core busy or offline' });
  });
  await listen<boolean>('confirmation-decision', (message) => {
    if (pending && client) client.confirm(pending, message.payload);
    pending = null;
  });
  await listen<{ reply_to: string; text: string }>('core-reply', (message) => {
    client?.reply(message.payload.reply_to, message.payload.text);
  });
  await listen('core-cancel', () => {
    client?.cancel();
  });
}
