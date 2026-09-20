import { listen } from '@tauri-apps/api/event';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { attachPointerLayer, playPointer, type OverlayMetrics } from './pointer';
import { startCoreLink } from './core-link';

const host = document.querySelector('#app')!;
const canvas = document.createElement('canvas');
canvas.className = 'summon-layer';
canvas.setAttribute('aria-hidden', 'true');
host.append(canvas);
attachPointerLayer(host);
const ctx = canvas.getContext('2d', { alpha: true })!;
const duration = 500;
let active = false;
let closing = false;
let started = 0;
let frame = 0;
let width = innerWidth;
let height = innerHeight;
let originX = width / 2;
let originY = height / 2;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const clamp = (n: number) => Math.max(0, Math.min(1, n));

interface SummonOrigin {
  x: number;
  y: number;
}

function resize() {
  width = innerWidth;
  height = innerHeight;
  const scale = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  if (active) draw(performance.now());
}

function ring(radius: number, progress: number) {
  const alpha = clamp(progress * 12) * (1 - clamp((progress - 0.78) / 0.22));
  if (radius < 2 || alpha <= 0) return;
  const band = 32 + progress * 65;
  const gradient = ctx.createRadialGradient(originX, originY, Math.max(0, radius - band), originX, originY, radius + 18);
  gradient.addColorStop(0, 'rgba(175,222,250,0)');
  gradient.addColorStop(0.45, `rgba(175,222,250,${0.025 * alpha})`);
  gradient.addColorStop(0.76, `rgba(205,237,255,${0.13 * alpha})`);
  gradient.addColorStop(band / (band + 18), `rgba(244,252,255,${0.64 * alpha})`);
  gradient.addColorStop(1, 'rgba(175,222,250,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  ctx.beginPath();
  ctx.arc(originX, originY, Math.max(1, radius - 25), 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(206,238,255,${0.09 * alpha})`;
  ctx.lineWidth = 3;
  ctx.stroke();
}

// Each edge lights only where the expanding circle has reached it.
function edge(length: number, distance: number, contactPoint: number, radius: number) {
  if (radius <= distance) return;
  const reach = Math.sqrt(radius * radius - distance * distance);
  const start = Math.max(0, contactPoint - reach);
  const end = Math.min(length, contactPoint + reach);
  const contact = clamp((radius - distance) / 35);
  const bloom = ctx.createLinearGradient(0, 0, 0, 150);
  bloom.addColorStop(0, `rgba(187,226,250,${0.24 * contact})`);
  bloom.addColorStop(0.09, `rgba(180,224,250,${0.13 * contact})`);
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
  // Feather the advancing contact points rather than ending in hard cuts.
  for (const x of [contactPoint - reach, contactPoint + reach]) {
    if (x <= 0 || x >= length) continue;
    const glow = ctx.createRadialGradient(x, 0, 0, x, 0, 35);
    glow.addColorStop(0, `rgba(227,246,255,${0.22 * contact})`);
    glow.addColorStop(1, 'rgba(190,229,255,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(x - 35, 0, 70, 35);
  }
}

function draw(now: number) {
  cancelAnimationFrame(frame);
  // Dismissal replays the same geometry in reverse: the ring collapses back to
  // its origin instead of the whole layer simply fading out.
  const raw = reducedMotion.matches ? 1 : clamp((now - started) / duration);
  const p = closing ? 1 - raw : raw;
  const cornerDistances = [
    Math.hypot(originX, originY),
    Math.hypot(width - originX, originY),
    Math.hypot(originX, height - originY),
    Math.hypot(width - originX, height - originY),
  ];
  const maxRadius = Math.max(...cornerDistances);
  const radius = (1 - Math.pow(1 - p, 1.65)) * (maxRadius + 2);
  ctx.clearRect(0, 0, width, height);
  ring(radius, p);
  edge(width, originY, originX, radius);
  ctx.save(); ctx.translate(width, height); ctx.rotate(Math.PI);
  edge(width, height - originY, width - originX, radius); ctx.restore();
  ctx.save(); ctx.translate(0, height); ctx.rotate(-Math.PI / 2);
  edge(height, originX, height - originY, radius); ctx.restore();
  ctx.save(); ctx.translate(width, 0); ctx.rotate(Math.PI / 2);
  edge(height, width - originX, originY, radius); ctx.restore();
  const corners = [[0, 0], [width, 0], [0, height], [width, height]];
  corners.forEach(([x, y], index) => {
    const corner = clamp((radius - cornerDistances[index] + 30) / 32);
    const glow = ctx.createRadialGradient(x, y, 0, x, y, 170);
    glow.addColorStop(0, `rgba(220,241,255,${0.19 * corner})`);
    glow.addColorStop(0.3, `rgba(185,226,250,${0.065 * corner})`);
    glow.addColorStop(1, 'rgba(185,226,250,0)');
    ctx.fillStyle = glow; ctx.fillRect(x - 170, y - 170, 340, 340);
  });
  if (raw < 1) {
    frame = requestAnimationFrame(draw);
  } else if (closing) {
    closing = false;
    active = false;
    canvas.classList.remove('visible');
    ctx.clearRect(0, 0, width, height);
  } else if (active) {
    canvas.classList.add('settled');
  }
}

function summon(origin?: SummonOrigin) {
  if (active && !closing) return;
  active = true;
  closing = false;
  cancelAnimationFrame(frame);
  canvas.classList.remove('settled');
  canvas.classList.add('visible');
  originX = clamp((origin?.x ?? width / 2) / width) * width;
  originY = clamp((origin?.y ?? height / 2) / height) * height;
  started = performance.now();
  draw(started);
}

function dismiss() {
  if (!active || closing) return;
  closing = true;
  canvas.classList.remove('settled');
  setOverlayMode('idle');
  cancelAnimationFrame(frame);
  started = performance.now();
  draw(started);
}

/** Overlay presence says a session is live; the mode says what it is doing. */
function setOverlayMode(mode: 'idle' | 'listening' | 'working' | 'speaking') {
  canvas.dataset.mode = mode;
}

function toggle(origin?: SummonOrigin) {
  if (active && !closing) dismiss();
  else summon(origin);
}

resize();
addEventListener('resize', resize);
if (isTauri()) {
  await listen<SummonOrigin>('overlay-toggle', (event) => toggle(event.payload));
  // overlay_ready shows the (transparent, click-through) overlay and returns the
  // monitor origin/scale needed to map Core's screen coordinates onto it.
  const metrics = await invoke<OverlayMetrics>('overlay_ready');
  await startCoreLink(metrics, { summon, dismiss, setMode: setOverlayMode });
} else {
  // Browser-only preview; native operation uses the global shortcut.
  addEventListener('keydown', (event) => {
    if (event.code === 'KeyJ' && event.ctrlKey && event.altKey && !event.repeat) toggle();
  });
  addEventListener('click', (event) => playPointer(event.clientX, event.clientY));
}
