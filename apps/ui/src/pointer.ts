// Cursor animation: plays whenever Core is about to move or use the pointer.
// Its own canvas so the summon animation and the pointer trail never fight.
export interface OverlayMetrics {
  origin_x: number;
  origin_y: number;
  scale: number;
}

const canvas = document.createElement('canvas');
canvas.className = 'pointer-layer';
canvas.setAttribute('aria-hidden', 'true');
const ctx = canvas.getContext('2d', { alpha: true })!;

let metrics: OverlayMetrics = { origin_x: 0, origin_y: 0, scale: 1 };
let width = innerWidth;
let height = innerHeight;
let frame = 0;
let from = { x: innerWidth / 2, y: innerHeight / 2 };
let to = from;
let started = 0;
let playing = false;
const travel = 260;
const settle = 420;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const ease = (t: number) => 1 - Math.pow(1 - t, 3);
const clamp01 = (n: number) => Math.max(0, Math.min(1, n));

export function attachPointerLayer(host: Element) {
  host.append(canvas);
  resizePointerLayer();
  addEventListener('resize', resizePointerLayer);
}

export function setOverlayMetrics(next: OverlayMetrics) {
  metrics = next;
}

function resizePointerLayer() {
  width = innerWidth;
  height = innerHeight;
  const scale = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
}

/** Screen (physical) coordinates from Core -> overlay CSS pixels. */
function toLocal(x: number, y: number) {
  return {
    x: (x - metrics.origin_x) / metrics.scale,
    y: (y - metrics.origin_y) / metrics.scale,
  };
}

function halo(x: number, y: number, radius: number, alpha: number) {
  const glow = ctx.createRadialGradient(x, y, 0, x, y, radius);
  glow.addColorStop(0, `rgba(244,252,255,${0.5 * alpha})`);
  glow.addColorStop(0.35, `rgba(196,234,255,${0.28 * alpha})`);
  glow.addColorStop(1, 'rgba(175,222,250,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
}

function render(now: number) {
  const elapsed = now - started;
  const move = clamp01(elapsed / travel);
  const land = clamp01((elapsed - travel) / settle);
  const eased = ease(move);
  const x = from.x + (to.x - from.x) * eased;
  const y = from.y + (to.y - from.y) * eased;
  ctx.clearRect(0, 0, width, height);

  // Comet trail behind the travelling point.
  const steps = 9;
  for (let i = steps; i > 0; i -= 1) {
    const t = ease(clamp01(move - i * 0.03));
    const tx = from.x + (to.x - from.x) * t;
    const ty = from.y + (to.y - from.y) * t;
    halo(tx, ty, 14 + i * 1.5, (0.1 * (steps - i)) / steps);
  }
  halo(x, y, 26, 1 - land * 0.4);

  // Reticle ripple once it arrives.
  if (land > 0) {
    const radius = 10 + land * 34;
    ctx.beginPath();
    ctx.arc(to.x, to.y, radius, 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(226,246,255,${0.75 * (1 - land)})`;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(to.x, to.y, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(244,252,255,${0.9 * (1 - land)})`;
    ctx.fill();
  }

  if (land < 1) {
    frame = requestAnimationFrame(render);
  } else {
    playing = false;
    ctx.clearRect(0, 0, width, height);
    canvas.classList.remove('active');
  }
}

/** Called for every Core pointer action, before the bridge executes it. */
export function playPointer(screenX: number, screenY: number) {
  const target = toLocal(screenX, screenY);
  if (!Number.isFinite(target.x) || !Number.isFinite(target.y)) return;
  from = playing ? to : { x: target.x, y: Math.max(0, target.y - 140) };
  to = target;
  started = performance.now();
  playing = true;
  canvas.classList.add('active');
  cancelAnimationFrame(frame);
  if (reducedMotion.matches) {
    // Still mark the target, without the travel.
    from = to;
  }
  frame = requestAnimationFrame(render);
}
