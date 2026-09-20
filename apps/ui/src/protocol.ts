// Client for shared/protocol.schema.json v1.0 over the Core UI socket.
// Frames are JSON text only; the token never appears in the URL.
export type AgentStatus =
  | 'listening'
  | 'thinking'
  | 'acting'
  | 'speaking'
  | 'confirmation_required'
  | 'completed'
  | 'cancelled'
  | 'error'
  | 'debug'
  | 'awaiting_input';

export interface AgentEvent {
  status: AgentStatus;
  message?: string;
  metadata?: Record<string, unknown>;
  audio?: { mime_type: string; encoding: string; data: string };
  confirmation?: {
    confirmation_id: string;
    call_id: string;
    action_hash: string;
    action: string;
    consequence: string;
    risk: string;
    expires_at: number;
  };
  error?: { code: string; message: string; retryable: boolean };
}

export interface Envelope {
  version: '1.0';
  type: string;
  request_id: string;
  task_id?: string;
  payload: Record<string, unknown>;
}

const uid = () => crypto.randomUUID().replaceAll('-', '');

export interface CoreHandlers {
  onEvent(event: AgentEvent, taskId: string): void;
  onState(state: 'connecting' | 'open' | 'closed', detail?: string): void;
}

export class CoreClient {
  private socket: WebSocket | null = null;
  private taskId: string | null = null;
  private retry = 0;
  private timer = 0;
  private closed = false;

  constructor(private url: string, private token: string, private handlers: CoreHandlers) {}

  get busy() {
    return this.taskId !== null;
  }

  connect() {
    this.closed = false;
    clearTimeout(this.timer);
    this.handlers.onState('connecting');
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.addEventListener('open', () => {
      // Core closes the connection unless a valid hello arrives within five seconds.
      socket.send(
        JSON.stringify({ version: '1.0', type: 'hello', request_id: uid(), payload: { role: 'ui', token: this.token } }),
      );
    });
    socket.addEventListener('message', (message) => {
      let frame: Envelope;
      try {
        frame = JSON.parse(String(message.data));
      } catch {
        return;
      }
      if (frame.type === 'hello_ack') {
        this.retry = 0;
        this.handlers.onState('open');
        return;
      }
      if (frame.type === 'agent_event') {
        const event = frame.payload as unknown as AgentEvent;
        const task = frame.task_id ?? '';
        if (['completed', 'cancelled', 'error'].includes(event.status) && task === this.taskId) this.taskId = null;
        this.handlers.onEvent(event, task);
        return;
      }
      if (frame.type === 'error') {
        this.handlers.onEvent({ status: 'error', error: frame.payload as never }, frame.task_id ?? '');
      }
    });
    socket.addEventListener('close', (event) => {
      this.socket = null;
      this.taskId = null;
      this.handlers.onState('closed', event.reason || `code ${event.code}`);
      if (this.closed) return;
      // Core may not be running yet; back off but keep trying.
      this.retry = Math.min(this.retry + 1, 6);
      this.timer = window.setTimeout(() => this.connect(), 500 * 2 ** (this.retry - 1));
    });
  }

  disconnect() {
    this.closed = true;
    clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
  }

  private send(type: string, payload: Record<string, unknown>, taskId?: string) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    const frame: Envelope = { version: '1.0', type, request_id: uid(), payload };
    if (taskId) frame.task_id = taskId;
    this.socket.send(JSON.stringify(frame));
    return true;
  }

  /** Task IDs are never reused for the lifetime of a Core process. */
  request(text: string, speak = false) {
    return this.start({ text, speak });
  }

  /** UserRequest carries exactly one of text or audio. Core runs the STT. */
  requestAudio(audio: Record<string, unknown>, speak = true) {
    return this.start({ audio, speak });
  }

  private start(payload: Record<string, unknown>) {
    if (this.busy) return false;
    const taskId = uid();
    this.taskId = taskId;
    if (!this.send('user_request', payload, taskId)) {
      this.taskId = null;
      return false;
    }
    return true;
  }

  /** Echo the confirmation fields back exactly; never auto-approve. */
  confirm(event: AgentEvent, approved: boolean) {
    const c = event.confirmation;
    if (!c || !this.taskId) return false;
    return this.send(
      'confirmation_response',
      { confirmation_id: c.confirmation_id, call_id: c.call_id, action_hash: c.action_hash, approved },
      this.taskId,
    );
  }

  reply(replyTo: string, text: string) {
    if (!this.taskId) return false;
    return this.send('user_reply', { reply_to: replyTo, text }, this.taskId);
  }

  cancel() {
    if (!this.taskId) return false;
    return this.send('cancel', { reason: 'User cancelled' }, this.taskId);
  }
}
