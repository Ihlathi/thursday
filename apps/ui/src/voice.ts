// Microphone capture for the overlay. The protocol takes one complete recording
// per request (not a stream), so this records an utterance, ends it on silence,
// and hands back a base64 Audio payload.
export interface AudioPayload {
  mime_type: 'audio/webm' | 'audio/ogg' | 'audio/wav' | 'audio/mpeg';
  encoding: 'base64';
  data: string;
}

const SILENCE = 0.012; // RMS below this counts as quiet
const START_TIMEOUT = 4000; // give up if nobody speaks
const TRAILING_SILENCE = 1100; // end the utterance after this much quiet
const MAX_LENGTH = 15000;
const MAX_BYTES = 2_000_000; // Core rejects anything larger once decoded

let recorder: MediaRecorder | null = null;
let stopping = false;

export const capturing = () => recorder !== null;

/** Ends the current capture early; the pending promise still resolves. */
export function stopCapture() {
  if (recorder && recorder.state === 'recording') {
    stopping = true;
    recorder.stop();
  }
}

function pickMime(): { recorder: string; wire: AudioPayload['mime_type'] } {
  for (const candidate of ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg']) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      // The schema takes the bare type, not the codec parameter.
      return { recorder: candidate, wire: candidate.startsWith('audio/ogg') ? 'audio/ogg' : 'audio/webm' };
    }
  }
  return { recorder: '', wire: 'audio/webm' };
}

async function toBase64(blob: Blob) {
  const buffer = new Uint8Array(await blob.arrayBuffer());
  let binary = '';
  for (let i = 0; i < buffer.length; i += 0x8000) {
    binary += String.fromCharCode(...buffer.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

export interface CaptureResult {
  audio?: AudioPayload;
  reason?: string;
}

/**
 * Records one utterance. `onLevel` receives 0..1 loudness for the overlay.
 * The stream is released as soon as the recording ends so the OS microphone
 * indicator does not stay lit while the app idles in the tray.
 */
export async function captureUtterance(onLevel?: (level: number) => void): Promise<CaptureResult> {
  if (recorder) return { reason: 'Already recording.' };
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (error) {
    return { reason: `Microphone unavailable: ${(error as Error).name}` };
  }

  const { recorder: mime, wire } = pickMime();
  const chunks: BlobPart[] = [];
  const context = new AudioContext();
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  context.createMediaStreamSource(stream).connect(analyser);
  const samples = new Float32Array(analyser.fftSize);

  stopping = false;
  recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  recorder.addEventListener('dataavailable', (event) => {
    if (event.data.size) chunks.push(event.data);
  });

  const started = performance.now();
  let speechAt = 0;
  let quietSince = 0;

  const finished = new Promise<void>((resolve) => {
    recorder!.addEventListener('stop', () => resolve(), { once: true });
  });

  const meter = setInterval(() => {
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const sample of samples) sum += sample * sample;
    const rms = Math.sqrt(sum / samples.length);
    onLevel?.(Math.min(1, rms * 12));
    const now = performance.now();
    if (rms > SILENCE) {
      if (!speechAt) speechAt = now;
      quietSince = 0;
    } else if (speechAt && !quietSince) {
      quietSince = now;
    }
    const heardNothing = !speechAt && now - started > START_TIMEOUT;
    const trailedOff = quietSince && now - quietSince > TRAILING_SILENCE;
    if (heardNothing || trailedOff || now - started > MAX_LENGTH) stopCapture();
  }, 50);

  recorder.start(250);
  await finished;
  clearInterval(meter);
  onLevel?.(0);
  stream.getTracks().forEach((track) => track.stop());
  void context.close();
  const wasStopped = stopping;
  recorder = null;
  stopping = false;

  if (!speechAt && !wasStopped) return { reason: 'No speech detected.' };
  const blob = new Blob(chunks, { type: wire });
  if (!blob.size) return { reason: 'Nothing was recorded.' };
  if (blob.size > MAX_BYTES) return { reason: 'Recording too long for one request.' };
  return { audio: { mime_type: wire, encoding: 'base64', data: await toBase64(blob) } };
}

let speaker: HTMLAudioElement | null = null;

/** Plays a `speaking` event's audio. */
export function playSpeech(audio: { mime_type: string; data: string }) {
  stopSpeech();
  speaker = new Audio(`data:${audio.mime_type};base64,${audio.data}`);
  void speaker.play().catch(() => undefined);
}

export function stopSpeech() {
  if (speaker) {
    speaker.pause();
    speaker = null;
  }
}
