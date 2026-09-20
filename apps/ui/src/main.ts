import { listen } from '@tauri-apps/api/event';
import { invoke, isTauri } from '@tauri-apps/api/core';

const canvas = document.createElement('canvas');
canvas.setAttribute('aria-hidden', 'true');
document.querySelector('#app')!.append(canvas);
const ctx = canvas.getContext('2d', { alpha: true })!;
const travelDuration = 500;
const birthDuration = 150;
const dismissDuration = 460;

// Cursor-control visual tuning. These values are intentionally centralized for quick iteration.
const CURSOR_TUNING = {
  auraGlowRadius: 144,
  auraCoreRadius: 48,
  auraInnerGlowIntensity: 0.22,
  auraOuterBloomIntensity: 0.1,
  auraFalloff: 0.72,
  auraBreathingStrength: 0.07,
  auraBreathingMs: 2400,
  trailLifetimeMs: 950,
  trailCoreWidth: 1.15,
  trailGlowWidth: 5,
  movementMinMs: 380,
  movementMaxMs: 1150,
  movementMsPerPixel: 0.52,
  trajectoryCurvatureMin: 0.045,
  trajectoryCurvatureMax: 0.09,
  shortTrajectoryStyles: ['arc', 'asymmetric'] as const,
  mediumTrajectoryStyles: ['arc', 'sCurve', 'asymmetric', 'hook'] as const,
  longTrajectoryStyles: ['sweep', 'sCurve', 'hook', 'asymmetric'] as const,
  cursorParticleMinDelayMs: 150,
  cursorParticleMaxDelayMs: 290,
  cursorParticleMinLifetimeMs: 900,
  cursorParticleMaxLifetimeMs: 1500,
  cursorParticleMaxCount: 10,
  clickSettleMs: 180,
  clickFieldSpacing: 48,
  clickWaveSpeed: 2050,
  clickWaveWidth: 46,
  clickWaveIntensity: 0.13,
  clickWaveWakeIntensity: 0.032,
  clickPointIlluminationMs: 220,
  clickFieldIntensity: 0.33,
  clickLocalRippleRadius: 42,
  clickLocalRippleMs: 340,
  clickLocalIntensity: 0.82,
  clickLocalRingIntensity: 0.24,
  clickMaximumBloom: 14,
  clickDistanceAttenuation: 0.58,
  clickWaveAttackMs: 70,
  clickWaveReleaseMs: 180,
} as const;
type OverlayPhase = 'idle' | 'summoning' | 'settled' | 'dismissing';
let phase: OverlayPhase = 'idle';
let started = 0;
let dismissStarted = 0;
let dismissStartRadius = 0;
let currentRadius = 0;
let frame = 0;
let width = innerWidth;
let height = innerHeight;
let summonOrigin = { x: width / 2, y: height / 2 };
let dismissOrigin = { ...summonOrigin };
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const smoothstep = (n: number) => n * n * (3 - 2 * n);
const smootherstep = (n: number) => n * n * n * (n * (n * 6 - 15) + 10);

interface SummonOrigin {
  x: number;
  y: number;
}

interface TrailPoint extends SummonOrigin {
  born: number;
}

type TrajectoryStyle = 'arc' | 'sCurve' | 'asymmetric' | 'sweep' | 'hook';

interface CursorMotion {
  from: SummonOrigin;
  to: SummonOrigin;
  control1: SummonOrigin;
  control2: SummonOrigin;
  started: number;
  duration: number;
  style: TrajectoryStyle;
  onComplete?: () => void;
}

interface ClickSequence extends SummonOrigin {
  started: number;
  fired: boolean;
  action?: () => void;
}

interface FieldPoint extends SummonOrigin {
  size: number;
  reflectivity: number;
}

interface Particle {
  side: number;
  x: number;
  y: number;
  dx: number;
  dy: number;
  size: number;
  born: number;
  lifetime: number;
  brightness: number;
}

interface CursorParticle extends SummonOrigin {
  dx: number;
  dy: number;
  size: number;
  born: number;
  lifetime: number;
  brightness: number;
}

let particles: Particle[] = [];
const particleTimers = [0, 0, 0, 0];
let lastSettledFrame = 0;
let controlAuraEnabled = false;
let cursorPosition = { x: width / 2, y: height / 2 };
let cursorMotion: CursorMotion | null = null;
let trail: TrailPoint[] = [];
let clickSequence: ClickSequence | null = null;
let cursorPollTimer = 0;
let lastCursorCommand = 0;
let clickField: FieldPoint[] = [];
let cursorParticles: CursorParticle[] = [];
let nextCursorParticleAt = 0;

function rebuildClickField() {
  clickField = [];
  const spacing = CURSOR_TUNING.clickFieldSpacing;
  const columns = Math.ceil(width / spacing);
  const rows = Math.ceil(height / spacing);
  const noise = (column: number, row: number, salt: number) => {
    const value = Math.sin(column * 127.1 + row * 311.7 + salt * 74.7) * 43758.5453;
    return value - Math.floor(value);
  };
  for (let row = 0; row <= rows; row += 1) {
    for (let column = 0; column <= columns; column += 1) {
      clickField.push({
        x: Math.max(0, Math.min(width, column * spacing + (noise(column, row, 1) - 0.5) * spacing * 0.44)),
        y: Math.max(0, Math.min(height, row * spacing + (noise(column, row, 2) - 0.5) * spacing * 0.44)),
        size: 0.45 + noise(column, row, 3) * 0.55,
        reflectivity: 0.55 + noise(column, row, 4) * 0.45,
      });
    }
  }
}

function resize() {
  width = innerWidth;
  height = innerHeight;
  const scale = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  rebuildClickField();
  if (phase !== 'idle' || hasCursorVisuals()) queueDraw();
}

function ring(radius: number, birthProgress: number, travelProgress: number) {
  const { x: originX, y: originY } = summonOrigin;
  // A compact ignition forms at the cursor before becoming the traveling crest.
  const pulse = travelProgress <= 0
    ? smoothstep(clamp(birthProgress / 0.45))
    : 1 - clamp(travelProgress / 0.16);
  if (pulse > 0) {
    const pulseRadius = 3 + 6 * birthProgress;
    const auraRadius = 8 + 8 * birthProgress;
    const aura = ctx.createRadialGradient(originX, originY, 0, originX, originY, auraRadius);
    aura.addColorStop(0, `rgba(225,246,255,${0.16 * pulse})`);
    aura.addColorStop(0.42, `rgba(170,220,250,${0.075 * pulse})`);
    aura.addColorStop(1, 'rgba(145,205,244,0)');
    ctx.fillStyle = aura;
    ctx.fillRect(originX - auraRadius, originY - auraRadius, auraRadius * 2, auraRadius * 2);

    const ignition = ctx.createRadialGradient(originX, originY, 0, originX, originY, pulseRadius);
    ignition.addColorStop(0, `rgba(255,255,255,${0.98 * pulse})`);
    ignition.addColorStop(0.18, `rgba(241,251,255,${0.82 * pulse})`);
    ignition.addColorStop(0.48, `rgba(190,231,255,${0.38 * pulse})`);
    ignition.addColorStop(1, 'rgba(175,222,250,0)');
    ctx.fillStyle = ignition;
    ctx.fillRect(originX - pulseRadius, originY - pulseRadius, pulseRadius * 2, pulseRadius * 2);
  }

  const birthCrest = travelProgress <= 0
    ? smoothstep(clamp(birthProgress / 0.45))
    : 1 - clamp(travelProgress / 0.12);
  if (birthCrest > 0) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(originX, originY, radius, 0, Math.PI * 2);
    ctx.shadowColor = `rgba(195,235,255,${0.72 * birthCrest})`;
    ctx.shadowBlur = 5;
    ctx.strokeStyle = `rgba(250,253,255,${0.95 * birthCrest})`;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }
  if (travelProgress <= 0) return;

  const alpha = clamp(travelProgress * 12) * (1 - clamp((travelProgress - 0.78) / 0.22));
  const waveDevelopment = smoothstep(clamp(travelProgress / 0.24));
  const band = 2 + (32 + travelProgress * 65 - 2) * waveDevelopment;
  const feather = 2 + 16 * waveDevelopment;
  const innerRadius = Math.max(0, radius - band);
  const outerRadius = radius + feather;
  const crest = clamp((radius - innerRadius) / (outerRadius - innerRadius));
  const gradient = ctx.createRadialGradient(originX, originY, innerRadius, originX, originY, outerRadius);
  gradient.addColorStop(0, 'rgba(175,222,250,0)');
  gradient.addColorStop(Math.max(0, crest - 0.36), `rgba(158,215,249,${0.012 * alpha})`);
  gradient.addColorStop(Math.max(0, crest - 0.19), `rgba(175,222,250,${0.052 * alpha})`);
  gradient.addColorStop(crest, `rgba(246,253,255,${0.76 * alpha})`);
  gradient.addColorStop(Math.min(1, crest + 0.1), `rgba(205,237,255,${0.18 * alpha})`);
  gradient.addColorStop(1, 'rgba(175,222,250,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  // Keep a fine, bright crest visible as the softer energy trails behind it.
  ctx.save();
  ctx.beginPath();
  ctx.arc(originX, originY, radius, 0, Math.PI * 2);
  ctx.shadowColor = `rgba(178,226,253,${0.62 * alpha})`;
  ctx.shadowBlur = 7 + 5 * waveDevelopment;
  ctx.strokeStyle = `rgba(247,253,255,${0.72 * alpha})`;
  ctx.lineWidth = 0.8 + 0.35 * waveDevelopment;
  ctx.stroke();
  ctx.restore();

  if (radius > 28) {
    // A quiet echo gives the wave a soft, water-like wake.
    const echoAlpha = 0.12 * alpha * waveDevelopment;
    ctx.save();
    ctx.beginPath();
    ctx.arc(originX, originY, radius - 25, 0, Math.PI * 2);
    ctx.shadowColor = `rgba(166,219,250,${0.24 * echoAlpha})`;
    ctx.shadowBlur = 5;
    ctx.strokeStyle = `rgba(194,232,253,${echoAlpha})`;
    ctx.lineWidth = 1.4;
    ctx.stroke();
    ctx.restore();
  }
}

function closingRing(radius: number, progress: number) {
  const { x: originX, y: originY } = dismissOrigin;
  const wave = Math.sin(progress * Math.PI);
  if (radius > 3 && wave > 0.002) {
    const band = 7 + 20 * (1 - progress);
    const feather = 5 + 9 * (1 - progress);
    const innerRadius = Math.max(0, radius - band);
    const outerRadius = radius + feather;
    const crest = clamp((radius - innerRadius) / (outerRadius - innerRadius));
    const gradient = ctx.createRadialGradient(originX, originY, innerRadius, originX, originY, outerRadius);
    gradient.addColorStop(0, 'rgba(166,218,249,0)');
    gradient.addColorStop(Math.max(0, crest - 0.3), `rgba(173,224,252,${0.035 * wave})`);
    gradient.addColorStop(crest, `rgba(244,252,255,${0.66 * wave})`);
    gradient.addColorStop(1, 'rgba(166,218,249,0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);

    ctx.save();
    ctx.beginPath();
    ctx.arc(originX, originY, radius, 0, Math.PI * 2);
    ctx.shadowColor = `rgba(176,226,253,${0.48 * wave})`;
    ctx.shadowBlur = 8;
    ctx.strokeStyle = `rgba(247,253,255,${0.68 * wave})`;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.restore();
  }

  const resolve = smoothstep(clamp((progress - 0.7) / 0.22))
    * (1 - smoothstep(clamp((progress - 0.93) / 0.07)));
  if (resolve > 0) {
    const pulseRadius = 5 + 8 * resolve;
    const pulse = ctx.createRadialGradient(originX, originY, 0, originX, originY, pulseRadius);
    pulse.addColorStop(0, `rgba(255,255,255,${0.9 * resolve})`);
    pulse.addColorStop(0.24, `rgba(221,244,255,${0.54 * resolve})`);
    pulse.addColorStop(1, 'rgba(166,218,249,0)');
    ctx.fillStyle = pulse;
    ctx.fillRect(originX - pulseRadius, originY - pulseRadius, pulseRadius * 2, pulseRadius * 2);
  }
}

// Each edge lights only where the expanding circle has reached it.
function edge(length: number, distance: number, contactPoint: number, radius: number) {
  if (radius <= distance) return;
  const reach = Math.sqrt(radius * radius - distance * distance);
  const start = Math.max(0, contactPoint - reach);
  const end = Math.min(length, contactPoint + reach);
  const contact = clamp((radius - distance) / 35);
  const impact = 1 - smoothstep(clamp((radius - distance) / 58));

  // The first contact is a soft accumulation of the same approaching wave.
  if (impact > 0) {
    const impactRadius = 64;
    const impactGlow = ctx.createRadialGradient(contactPoint, 0, 0, contactPoint, 0, impactRadius);
    impactGlow.addColorStop(0, `rgba(250,254,255,${0.52 * impact})`);
    impactGlow.addColorStop(0.18, `rgba(205,239,255,${0.26 * impact})`);
    impactGlow.addColorStop(1, 'rgba(166,218,249,0)');
    ctx.fillStyle = impactGlow;
    ctx.fillRect(contactPoint - impactRadius, 0, impactRadius * 2, impactRadius);
  }

  const bloom = ctx.createLinearGradient(0, 0, 0, 170);
  bloom.addColorStop(0, `rgba(201,235,255,${0.3 * contact})`);
  bloom.addColorStop(0.08, `rgba(184,226,251,${0.16 * contact})`);
  bloom.addColorStop(0.38, `rgba(174,220,248,${0.045 * contact})`);
  bloom.addColorStop(1, 'rgba(180,224,250,0)');
  ctx.save();
  ctx.beginPath();
  ctx.rect(start, 0, end - start, 170);
  ctx.clip();
  ctx.fillStyle = bloom;
  ctx.fillRect(0, 0, length, 170);
  ctx.shadowColor = 'rgba(196,234,255,0.8)';
  ctx.shadowBlur = 14;
  ctx.fillStyle = `rgba(242,251,255,${0.88 * contact})`;
  ctx.fillRect(start, 0, end - start, 1);
  ctx.restore();
  // Feather the advancing contact points rather than ending in hard cuts.
  for (const x of [contactPoint - reach, contactPoint + reach]) {
    if (x <= 0 || x >= length) continue;
    const glow = ctx.createRadialGradient(x, 0, 0, x, 0, 42);
    glow.addColorStop(0, `rgba(237,250,255,${0.3 * contact})`);
    glow.addColorStop(0.25, `rgba(198,234,254,${0.14 * contact})`);
    glow.addColorStop(1, 'rgba(190,229,255,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(x - 42, 0, 84, 42);
  }
}

function clearParticleTimers() {
  particleTimers.forEach((timer) => clearTimeout(timer));
  particleTimers.fill(0);
}

function scheduleParticle(side: number, initial = false) {
  clearTimeout(particleTimers[side]);
  if (phase !== 'settled') return;
  const edgeCount = particles.filter((particle) => particle.side === side).length;
  const quietMoment = Math.random() < 0.06;
  const nextDelay = initial
    ? 30 + Math.random() * 220
    : edgeCount === 0
      ? 30 + Math.random() * 70
      : quietMoment
        ? 650 + Math.random() * 450
        : 100 + Math.random() * 150;
  particleTimers[side] = window.setTimeout(() => {
    if (phase !== 'settled') return;
    const currentEdgeCount = particles.filter((particle) => particle.side === side).length;
    if (currentEdgeCount >= 12) return scheduleParticle(side);
    const along = 0.08 + Math.random() * 0.84;
    const inward = 18 + Math.random() * 28;
    const lateral = (Math.random() - 0.5) * 12;
    const brighter = Math.random() < 0.1;
    let x = 0;
    let y = 0;
    let dx = 0;
    let dy = 0;
    if (side === 0) { x = width * along; dx = lateral; dy = inward; }
    if (side === 1) { x = width; y = height * along; dx = -inward; dy = lateral; }
    if (side === 2) { x = width * along; y = height; dx = lateral; dy = -inward; }
    if (side === 3) { y = height * along; dx = inward; dy = lateral; }
    particles.push({
      side, x, y, dx, dy,
      size: brighter
        ? 0.64 + Math.random() * 0.34
        : 0.28 + Math.pow(Math.random(), 2) * 0.38,
      born: performance.now(),
      lifetime: 2200 + Math.random() * 1400,
      brightness: brighter
        ? 0.44 + Math.random() * 0.18
        : 0.18 + Math.random() * 0.24,
    });
    queueDraw();
    scheduleParticle(side);
  }, nextDelay);
}

function scheduleParticles() {
  for (let side = 0; side < 4; side += 1) scheduleParticle(side, true);
}

function drawParticles(now: number, phaseOpacity = 1) {
  particles = particles.filter((particle) => now - particle.born < particle.lifetime);
  for (const particle of particles) {
    const progress = clamp((now - particle.born) / particle.lifetime);
    const drift = smoothstep(progress);
    const opacity = Math.sin(progress * Math.PI) * particle.brightness * phaseOpacity;
    const x = particle.x + particle.dx * drift;
    const y = particle.y + particle.dy * drift;
    const haloRadius = 2.8 + particle.size * 5.8;
    const glow = ctx.createRadialGradient(x, y, 0, x, y, haloRadius);
    glow.addColorStop(0, `rgba(250,254,255,${0.78 * opacity})`);
    glow.addColorStop(0.1, `rgba(230,247,255,${0.58 * opacity})`);
    glow.addColorStop(0.34, `rgba(203,237,255,${0.3 * opacity})`);
    glow.addColorStop(0.62, `rgba(174,224,252,${0.1 * opacity})`);
    glow.addColorStop(1, 'rgba(154,214,249,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(x - haloRadius, y - haloRadius, haloRadius * 2, haloRadius * 2);
  }
}

function hasCursorVisuals() {
  return controlAuraEnabled || cursorMotion !== null || trail.length > 0
    || clickSequence !== null || cursorParticles.length > 0;
}

function setCursorControlAura(enabled: boolean, at?: SummonOrigin) {
  controlAuraEnabled = enabled;
  if (at) cursorPosition = normalizedOrigin(at);
  clearInterval(cursorPollTimer);
  cursorPollTimer = 0;
  if (enabled) {
    canvas.classList.add('visible');
    cursorPollTimer = window.setInterval(async () => {
      if (!controlAuraEnabled || cursorMotion) return;
      try {
        cursorPosition = normalizedOrigin(await invoke<SummonOrigin>('cursor_origin'));
        queueDraw();
      } catch {
        // The next poll can recover; avoid interrupting the visual system.
      }
    }, 50);
  }
  queueDraw();
}

function cubicPoint(motion: CursorMotion, progress: number): SummonOrigin {
  const inverse = 1 - progress;
  const x = inverse ** 3 * motion.from.x
    + 3 * inverse ** 2 * progress * motion.control1.x
    + 3 * inverse * progress ** 2 * motion.control2.x
    + progress ** 3 * motion.to.x;
  const y = inverse ** 3 * motion.from.y
    + 3 * inverse ** 2 * progress * motion.control1.y
    + 3 * inverse * progress ** 2 * motion.control2.y
    + progress ** 3 * motion.to.y;

  return { x, y };
}

function trajectoryStyle(distance: number): TrajectoryStyle {
  const styles = distance < 180
    ? CURSOR_TUNING.shortTrajectoryStyles
    : distance < 600
      ? CURSOR_TUNING.mediumTrajectoryStyles
      : CURSOR_TUNING.longTrajectoryStyles;
  return styles[Math.floor(Math.random() * styles.length)] as TrajectoryStyle;
}

function moveJarvisCursor(to: SummonOrigin, from = cursorPosition, onComplete?: () => void) {
  const start = normalizedOrigin(from);
  const target = normalizedOrigin(to);
  const vx = target.x - start.x;
  const vy = target.y - start.y;
  const distance = Math.hypot(vx, vy);
  if (distance < 2) {
    cursorPosition = target;
    onComplete?.();
    return;
  }
  const nx = -vy / distance;
  const ny = vx / distance;
  const style = trajectoryStyle(distance);
  const curvature = CURSOR_TUNING.trajectoryCurvatureMin
    + Math.random() * (CURSOR_TUNING.trajectoryCurvatureMax - CURSOR_TUNING.trajectoryCurvatureMin);
  const curve = Math.max(3, Math.min(58, distance * curvature)) * (Math.random() < 0.5 ? -1 : 1);
  let firstBend = 0.72;
  let secondBend = 0.56;
  let firstProgress = 0.34;
  let secondProgress = 0.7;
  if (style === 'sCurve') { firstBend = 0.82; secondBend = -0.68; }
  if (style === 'asymmetric') { firstBend = 0.38; secondBend = 0.92; firstProgress = 0.27; }
  if (style === 'sweep') { firstBend = 1; secondBend = 0.82; }
  if (style === 'hook') { firstBend = 0.28; secondBend = -0.7; secondProgress = 0.8; }
  cursorMotion = {
    from: start,
    to: target,
    control1: {
      x: start.x + vx * firstProgress + nx * curve * firstBend,
      y: start.y + vy * firstProgress + ny * curve * firstBend,
    },
    control2: {
      x: start.x + vx * secondProgress + nx * curve * secondBend,
      y: start.y + vy * secondProgress + ny * curve * secondBend,
    },
    started: performance.now(),
    duration: Math.min(
      CURSOR_TUNING.movementMaxMs,
      Math.max(CURSOR_TUNING.movementMinMs, CURSOR_TUNING.movementMinMs + distance * CURSOR_TUNING.movementMsPerPixel),
    ),
    style,
    onComplete,
  };
  cursorPosition = start;
  trail = [{ ...start, born: performance.now() }];
  canvas.classList.add('visible');
  queueDraw();
}

function showJarvisClick(at: SummonOrigin = cursorPosition, action?: () => void) {
  cursorPosition = normalizedOrigin(at);
  clickSequence = { ...cursorPosition, started: performance.now(), fired: false, action };
  canvas.classList.add('visible');
  queueDraw();
}

function runAutonomousAction(from: SummonOrigin, to: SummonOrigin) {
  setCursorControlAura(true, from);
  moveJarvisCursor(to, from, () => showJarvisClick(cursorPosition));
}

function updateCursorMotion(now: number) {
  if (!cursorMotion) return;
  const raw = clamp((now - cursorMotion.started) / cursorMotion.duration);
  const point = cubicPoint(cursorMotion, smootherstep(raw));
  cursorPosition = point;
  const previous = trail[trail.length - 1];
  if (!previous || Math.hypot(point.x - previous.x, point.y - previous.y) >= 2.2 || now - previous.born >= 34) {
    trail.push({ ...point, born: now });
  }
  if (now - lastCursorCommand >= 16 || raw >= 1) {
    lastCursorCommand = now;
    void invoke('set_cursor_position', { x: point.x, y: point.y }).catch(() => undefined);
  }
  if (raw >= 1) {
    const complete = cursorMotion.onComplete;
    cursorMotion = null;
    cursorPosition = normalizedOrigin(point);
    complete?.();
  }
}

function drawTrail(now: number) {
  trail = trail.filter((point) => now - point.born < CURSOR_TUNING.trailLifetimeMs);
  for (let index = 1; index < trail.length; index += 1) {
    const previous = trail[index - 1];
    const point = trail[index];
    const age = clamp((now - point.born) / CURSOR_TUNING.trailLifetimeMs);
    const alpha = (1 - smoothstep(age)) * 0.52;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(previous.x, previous.y);
    ctx.lineTo(point.x, point.y);
    ctx.shadowColor = `rgba(151,216,250,${0.38 * alpha})`;
    ctx.shadowBlur = 7;
    ctx.strokeStyle = `rgba(169,225,253,${0.2 * alpha})`;
    ctx.lineWidth = CURSOR_TUNING.trailGlowWidth;
    ctx.stroke();
    ctx.shadowBlur = 2;
    ctx.strokeStyle = `rgba(240,251,255,${0.76 * alpha})`;
    ctx.lineWidth = CURSOR_TUNING.trailCoreWidth;
    ctx.stroke();
    ctx.restore();
  }
}

function drawClickBorderImpactPoint(side: number, along: number, strength: number) {
  const horizontal = side === 0 || side === 2;
  const x = horizontal ? along : side === 3 ? 4 : width - 4;
  const y = horizontal ? side === 0 ? 4 : height - 4 : along;
  const radius = 46;
  const glow = ctx.createRadialGradient(x, y, 0, x, y, radius);
  glow.addColorStop(0, `rgba(248,253,255,${0.32 * strength})`);
  glow.addColorStop(0.16, `rgba(205,239,255,${0.18 * strength})`);
  glow.addColorStop(0.55, `rgba(172,222,251,${0.055 * strength})`);
  glow.addColorStop(1, 'rgba(160,216,248,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);

  ctx.save();
  ctx.shadowColor = `rgba(207,241,255,${0.55 * strength})`;
  ctx.shadowBlur = 12;
  ctx.fillStyle = `rgba(246,253,255,${0.5 * strength})`;
  if (horizontal) ctx.fillRect(along - 11, side === 0 ? 0 : height - 1, 22, 1);
  else ctx.fillRect(side === 3 ? 0 : width - 1, along - 11, 1, 22);
  ctx.restore();
}

function drawClickBorderResponse(origin: SummonOrigin, radius: number, maximumDistance: number, envelope: number) {
  if (phase !== 'settled' || radius <= 0 || envelope <= 0) return;
  const edges = [
    { side: 0, distance: origin.y, contact: origin.x, length: width },
    { side: 1, distance: width - origin.x, contact: origin.y, length: height },
    { side: 2, distance: height - origin.y, contact: origin.x, length: width },
    { side: 3, distance: origin.x, contact: origin.y, length: height },
  ];
  for (const edge of edges) {
    if (radius < edge.distance) continue;
    const reach = Math.sqrt(Math.max(0, radius * radius - edge.distance * edge.distance));
    const firstContact = 1 - smoothstep(clamp((radius - edge.distance) / 90));
    const distanceFade = 1 - 0.35 * clamp(radius / maximumDistance);
    const strength = envelope * distanceFade * (0.38 + firstContact * 0.62);
    const first = edge.contact - reach;
    const second = edge.contact + reach;
    if (first >= 0 && first <= edge.length) drawClickBorderImpactPoint(edge.side, first, strength);
    if (reach > 3 && second >= 0 && second <= edge.length) {
      drawClickBorderImpactPoint(edge.side, second, strength);
    }
  }
}

function drawClickSequence(now: number) {
  if (!clickSequence) return 0;
  const elapsed = now - clickSequence.started;
  const settle = clamp(elapsed / CURSOR_TUNING.clickSettleMs);
  if (elapsed >= CURSOR_TUNING.clickSettleMs && !clickSequence.fired) {
    clickSequence.fired = true;
    clickSequence.action?.();
  }
  const waveElapsed = elapsed - CURSOR_TUNING.clickSettleMs;
  if (waveElapsed >= 0) {
    const maximumDistance = Math.max(
      Math.hypot(clickSequence.x, clickSequence.y),
      Math.hypot(width - clickSequence.x, clickSequence.y),
      Math.hypot(clickSequence.x, height - clickSequence.y),
      Math.hypot(width - clickSequence.x, height - clickSequence.y),
    );
    const waveRadius = waveElapsed * CURSOR_TUNING.clickWaveSpeed / 1000;
    const waveDuration = maximumDistance / CURSOR_TUNING.clickWaveSpeed * 1000;
    const localProgress = clamp(waveElapsed / CURSOR_TUNING.clickLocalRippleMs);
    const waveAttack = smoothstep(clamp(waveElapsed / CURSOR_TUNING.clickWaveAttackMs));
    const waveRelease = 1 - smoothstep(clamp(
      (waveElapsed - waveDuration) / CURSOR_TUNING.clickWaveReleaseMs,
    ));
    const waveEnvelope = waveAttack * waveRelease;

    // A glossy local response establishes exactly where the click occurred.
    if (localProgress < 1) {
      const eased = 1 - Math.pow(1 - localProgress, 3);
      const alpha = waveAttack * (1 - smoothstep(localProgress));
      const radius = 2 + eased * CURSOR_TUNING.clickLocalRippleRadius;
      const outer = radius + CURSOR_TUNING.clickMaximumBloom;
      const ringAlpha = alpha * CURSOR_TUNING.clickLocalRingIntensity;
      const local = ctx.createRadialGradient(clickSequence.x, clickSequence.y, 0, clickSequence.x, clickSequence.y, outer);
      local.addColorStop(0, `rgba(255,255,255,${0.18 * ringAlpha * CURSOR_TUNING.clickLocalIntensity})`);
      local.addColorStop(Math.max(0, radius / outer - 0.12), `rgba(193,233,254,${0.12 * ringAlpha})`);
      local.addColorStop(radius / outer, `rgba(246,253,255,${0.42 * ringAlpha})`);
      local.addColorStop(1, 'rgba(166,218,249,0)');
      ctx.fillStyle = local;
      ctx.fillRect(clickSequence.x - outer, clickSequence.y - outer, outer * 2, outer * 2);
    }

    // The wavefront is nearly transparent; the reflective field carries most of its presence.
    if (waveRadius > 1 && waveRadius < maximumDistance + CURSOR_TUNING.clickWaveWidth) {
      const inner = Math.max(0, waveRadius - CURSOR_TUNING.clickWaveWidth);
      const outer = waveRadius + CURSOR_TUNING.clickWaveWidth * 0.35;
      const crest = (waveRadius - inner) / (outer - inner);
      const sheet = ctx.createRadialGradient(clickSequence.x, clickSequence.y, inner, clickSequence.x, clickSequence.y, outer);
      sheet.addColorStop(0, 'rgba(160,216,248,0)');
      sheet.addColorStop(Math.max(0, crest - 0.62), `rgba(163,219,250,${0.008 * waveEnvelope})`);
      sheet.addColorStop(Math.max(0, crest - 0.34), `rgba(176,227,252,${CURSOR_TUNING.clickWaveWakeIntensity * waveEnvelope})`);
      sheet.addColorStop(Math.max(0, crest - 0.12), `rgba(202,239,255,${CURSOR_TUNING.clickWaveIntensity * 0.46 * waveEnvelope})`);
      sheet.addColorStop(crest, `rgba(237,250,255,${CURSOR_TUNING.clickWaveIntensity * waveEnvelope})`);
      sheet.addColorStop(Math.min(1, crest + 0.1), `rgba(191,232,253,${CURSOR_TUNING.clickWaveIntensity * 0.2 * waveEnvelope})`);
      sheet.addColorStop(1, 'rgba(160,216,248,0)');
      ctx.fillStyle = sheet;
      ctx.fillRect(0, 0, width, height);
    }

    ctx.save();
    ctx.shadowColor = 'rgba(169,225,253,0.42)';
    ctx.shadowBlur = 4;
    for (const point of clickField) {
      const distance = Math.hypot(point.x - clickSequence.x, point.y - clickSequence.y);
      const arrival = distance / CURSOR_TUNING.clickWaveSpeed * 1000;
      const pointAge = waveElapsed - arrival;
      if (pointAge < 0 || pointAge > CURSOR_TUNING.clickPointIlluminationMs) continue;
      const illumination = smoothstep(Math.sin(
        (pointAge / CURSOR_TUNING.clickPointIlluminationMs) * Math.PI,
      ));
      const attenuation = 1 - (distance / Math.max(1, maximumDistance)) * CURSOR_TUNING.clickDistanceAttenuation;
      const alpha = illumination * attenuation * point.reflectivity * CURSOR_TUNING.clickFieldIntensity;
      const size = point.size * (1 + illumination * 0.42);
      ctx.fillStyle = `rgba(221,246,255,${alpha})`;
      ctx.beginPath();
      ctx.arc(point.x, point.y, size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    drawClickBorderResponse(clickSequence, waveRadius, maximumDistance, waveEnvelope);

    const flashProgress = clamp(waveElapsed / 110);
    const flash = Math.sin(flashProgress * Math.PI)
      * (1 - smoothstep(flashProgress) * 0.35)
      * CURSOR_TUNING.clickLocalIntensity;
    if (flash > 0) {
      const glow = ctx.createRadialGradient(clickSequence.x, clickSequence.y, 0, clickSequence.x, clickSequence.y, 13);
      glow.addColorStop(0, `rgba(255,255,255,${flash})`);
      glow.addColorStop(0.28, `rgba(210,241,255,${0.46 * flash})`);
      glow.addColorStop(1, 'rgba(166,218,249,0)');
      ctx.fillStyle = glow;
      ctx.fillRect(clickSequence.x - 13, clickSequence.y - 13, 26, 26);
    }

    if (waveElapsed >= waveDuration + Math.max(
      CURSOR_TUNING.clickPointIlluminationMs,
      CURSOR_TUNING.clickWaveReleaseMs,
    )) clickSequence = null;
  }
  return elapsed < CURSOR_TUNING.clickSettleMs
    ? smoothstep(settle)
    : 1 - smoothstep(clamp(waveElapsed / 220));
}

function drawCursorAura(now: number, focus: number) {
  if (!controlAuraEnabled && !cursorMotion && !clickSequence) return;
  const breathe = 1 + Math.sin((now / CURSOR_TUNING.auraBreathingMs) * Math.PI * 2)
    * CURSOR_TUNING.auraBreathingStrength;
  const radius = CURSOR_TUNING.auraGlowRadius * breathe * (1 - focus * 0.18);
  const focusIntensity = 1 + focus * 0.34;
  const centerX = cursorPosition.x + 5;
  const centerY = cursorPosition.y + 8;
  const driftX = Math.sin(now / 740) * radius * 0.035;
  const driftY = Math.cos(now / 910) * radius * 0.028;

  const outer = ctx.createRadialGradient(
    centerX + driftX,
    centerY + driftY,
    0,
    centerX,
    centerY,
    radius,
  );
  outer.addColorStop(0, `rgba(207,240,255,${CURSOR_TUNING.auraOuterBloomIntensity * 1.22 * focusIntensity})`);
  outer.addColorStop(0.18, `rgba(184,229,253,${CURSOR_TUNING.auraOuterBloomIntensity * 0.82 * focusIntensity})`);
  outer.addColorStop(0.4, `rgba(161,216,250,${CURSOR_TUNING.auraOuterBloomIntensity * 0.42})`);
  outer.addColorStop(CURSOR_TUNING.auraFalloff, `rgba(139,201,246,${CURSOR_TUNING.auraOuterBloomIntensity * 0.085})`);
  outer.addColorStop(0.88, `rgba(130,194,243,${CURSOR_TUNING.auraOuterBloomIntensity * 0.018})`);
  outer.addColorStop(1, 'rgba(125,188,240,0)');
  ctx.fillStyle = outer;
  ctx.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);

  // Overlapping low-opacity fields keep the illumination soft without exposing a geometric edge.
  for (const [offsetX, offsetY, scale] of [[-0.11, 0.06, 0.74], [0.13, -0.09, 0.68]]) {
    const lobeRadius = radius * scale;
    const x = centerX + radius * offsetX;
    const y = centerY + radius * offsetY;
    const lobe = ctx.createRadialGradient(x, y, 0, x, y, lobeRadius);
    lobe.addColorStop(0, `rgba(183,229,253,${CURSOR_TUNING.auraOuterBloomIntensity * 0.25 * focusIntensity})`);
    lobe.addColorStop(0.42, `rgba(153,212,249,${CURSOR_TUNING.auraOuterBloomIntensity * 0.085})`);
    lobe.addColorStop(0.78, `rgba(137,201,246,${CURSOR_TUNING.auraOuterBloomIntensity * 0.018})`);
    lobe.addColorStop(1, 'rgba(130,194,243,0)');
    ctx.fillStyle = lobe;
    ctx.fillRect(x - lobeRadius, y - lobeRadius, lobeRadius * 2, lobeRadius * 2);
  }

  const coreRadius = CURSOR_TUNING.auraCoreRadius * breathe;
  const core = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, coreRadius);
  core.addColorStop(0, `rgba(247,253,255,${CURSOR_TUNING.auraInnerGlowIntensity * focusIntensity})`);
  core.addColorStop(0.22, `rgba(218,243,255,${CURSOR_TUNING.auraInnerGlowIntensity * 0.7 * focusIntensity})`);
  core.addColorStop(0.52, `rgba(177,224,251,${CURSOR_TUNING.auraInnerGlowIntensity * 0.27})`);
  core.addColorStop(0.76, `rgba(150,210,248,${CURSOR_TUNING.auraInnerGlowIntensity * 0.07})`);
  core.addColorStop(0.9, `rgba(139,202,246,${CURSOR_TUNING.auraInnerGlowIntensity * 0.015})`);
  core.addColorStop(1, 'rgba(132,195,243,0)');
  ctx.fillStyle = core;
  ctx.fillRect(centerX - coreRadius, centerY - coreRadius, coreRadius * 2, coreRadius * 2);
}

function spawnCursorParticle(now: number) {
  if (cursorParticles.length >= CURSOR_TUNING.cursorParticleMaxCount) return;
  const angle = Math.random() * Math.PI * 2;
  const spawnRadius = 7 + Math.random() * 14;
  const travel = 17 + Math.random() * 24;
  cursorParticles.push({
    x: cursorPosition.x + 5 + Math.cos(angle) * spawnRadius,
    y: cursorPosition.y + 8 + Math.sin(angle) * spawnRadius,
    dx: Math.cos(angle + (Math.random() - 0.5) * 0.55) * travel,
    dy: Math.sin(angle + (Math.random() - 0.5) * 0.55) * travel,
    size: 0.3 + Math.random() * 0.42,
    born: now,
    lifetime: CURSOR_TUNING.cursorParticleMinLifetimeMs
      + Math.random() * (CURSOR_TUNING.cursorParticleMaxLifetimeMs - CURSOR_TUNING.cursorParticleMinLifetimeMs),
    brightness: 0.17 + Math.random() * 0.2,
  });
}

function drawCursorParticles(now: number) {
  const emitting = controlAuraEnabled || cursorMotion !== null || clickSequence !== null;
  if (emitting && now >= nextCursorParticleAt) {
    spawnCursorParticle(now);
    const delayRange = CURSOR_TUNING.cursorParticleMaxDelayMs - CURSOR_TUNING.cursorParticleMinDelayMs;
    nextCursorParticleAt = now + CURSOR_TUNING.cursorParticleMinDelayMs + Math.random() * delayRange;
  } else if (!emitting) {
    nextCursorParticleAt = 0;
  }

  cursorParticles = cursorParticles.filter((particle) => now - particle.born < particle.lifetime);
  for (const particle of cursorParticles) {
    const progress = clamp((now - particle.born) / particle.lifetime);
    const drift = smoothstep(progress);
    const opacity = Math.sin(progress * Math.PI) * particle.brightness;
    const x = particle.x + particle.dx * drift;
    const y = particle.y + particle.dy * drift;
    const haloRadius = 2.6 + particle.size * 5.5;
    const glow = ctx.createRadialGradient(x, y, 0, x, y, haloRadius);
    glow.addColorStop(0, `rgba(250,254,255,${0.72 * opacity})`);
    glow.addColorStop(0.14, `rgba(229,246,255,${0.5 * opacity})`);
    glow.addColorStop(0.42, `rgba(199,235,254,${0.22 * opacity})`);
    glow.addColorStop(1, 'rgba(154,214,249,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(x - haloRadius, y - haloRadius, haloRadius * 2, haloRadius * 2);
  }
}

function drawCursorSystem(now: number) {
  updateCursorMotion(now);
  drawTrail(now);
  const focus = drawClickSequence(now);
  drawCursorAura(now, focus);
  drawCursorParticles(now);
}

function testMovementTarget(from: SummonOrigin) {
  return {
    x: from.x < width / 2 ? width * 0.72 : width * 0.28,
    y: from.y < height / 2 ? height * 0.68 : height * 0.32,
  };
}

function cornerDistances(origin: SummonOrigin = summonOrigin) {
  const { x: originX, y: originY } = origin;
  return [
    Math.hypot(originX, originY),
    Math.hypot(width - originX, originY),
    Math.hypot(originX, height - originY),
    Math.hypot(width - originX, height - originY),
  ];
}

function drawBorder(radius: number, distances: number[], origin: SummonOrigin = summonOrigin) {
  const { x: originX, y: originY } = origin;
  edge(width, originY, originX, radius);
  ctx.save(); ctx.translate(width, height); ctx.rotate(Math.PI);
  edge(width, height - originY, width - originX, radius); ctx.restore();
  ctx.save(); ctx.translate(0, height); ctx.rotate(-Math.PI / 2);
  edge(height, originX, height - originY, radius); ctx.restore();
  ctx.save(); ctx.translate(width, 0); ctx.rotate(Math.PI / 2);
  edge(height, width - originX, originY, radius); ctx.restore();
  const corners = [[0, 0], [width, 0], [0, height], [width, height]];
  corners.forEach(([x, y], index) => {
    const corner = clamp((radius - distances[index] + 30) / 32);
    const glow = ctx.createRadialGradient(x, y, 0, x, y, 170);
    glow.addColorStop(0, `rgba(220,241,255,${0.19 * corner})`);
    glow.addColorStop(0.3, `rgba(185,226,250,${0.065 * corner})`);
    glow.addColorStop(1, 'rgba(185,226,250,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(x - 170, y - 170, 340, 340);
  });
}

function draw(now: number) {
  frame = 0;
  const cursorVisuals = hasCursorVisuals();
  if (phase === 'settled' && particles.length > 0 && !cursorVisuals && now - lastSettledFrame < 32) {
    queueDraw();
    return;
  }
  if (phase === 'settled') lastSettledFrame = now;
  ctx.clearRect(0, 0, width, height);

  if (phase === 'idle') {
    drawCursorSystem(now);
    if (hasCursorVisuals()) queueDraw();
    else canvas.classList.remove('visible');
    return;
  }

  const lifecycleOrigin = phase === 'dismissing' ? dismissOrigin : summonOrigin;
  const distances = cornerDistances(lifecycleOrigin);
  const maxRadius = Math.max(...distances) + 2;

  if (phase === 'summoning') {
    const elapsed = Math.max(0, now - started);
    const birthProgress = reducedMotion.matches ? 1 : clamp(elapsed / birthDuration);
    const travelProgress = reducedMotion.matches ? 1 : clamp((elapsed - birthDuration) / travelDuration);
    const birthRadius = 3 * smoothstep(birthProgress);
    const easedTravel = 1 - Math.pow(1 - smootherstep(travelProgress), 1.65);
    currentRadius = travelProgress > 0
      ? 3 + easedTravel * (maxRadius - 3)
      : birthRadius;
    ring(currentRadius, birthProgress, travelProgress);
    drawBorder(currentRadius, distances, lifecycleOrigin);
    drawCursorSystem(now);
    if (travelProgress < 1) {
      queueDraw();
    } else {
      phase = 'settled';
      currentRadius = maxRadius;
      canvas.classList.add('settled');
      scheduleParticles();
      if (hasCursorVisuals()) queueDraw();
    }
    return;
  }

  if (phase === 'settled') {
    currentRadius = maxRadius;
    drawBorder(currentRadius, distances, lifecycleOrigin);
    drawParticles(now);
    drawCursorSystem(now);
    if (particles.length > 0 || hasCursorVisuals()) queueDraw();
    return;
  }

  const dismissProgress = reducedMotion.matches
    ? 1
    : clamp((now - dismissStarted) / dismissDuration);
  currentRadius = 3 + (dismissStartRadius - 3) * (1 - smootherstep(dismissProgress));
  drawBorder(currentRadius, distances, lifecycleOrigin);
  closingRing(currentRadius, dismissProgress);
  drawParticles(now, 1 - smoothstep(clamp(dismissProgress / 0.35)));
  drawCursorSystem(now);
  if (dismissProgress < 1) {
    queueDraw();
  } else {
    phase = 'idle';
    particles = [];
    if (hasCursorVisuals()) queueDraw();
    else {
      ctx.clearRect(0, 0, width, height);
      canvas.classList.remove('visible');
    }
  }
}

function queueDraw() {
  if (!frame) frame = requestAnimationFrame(draw);
}

function normalizedOrigin(origin?: SummonOrigin): SummonOrigin {
  return {
    x: typeof origin?.x === 'number' && Number.isFinite(origin.x) && width > 0
      ? clamp(origin.x / width) * width
      : width / 2,
    y: typeof origin?.y === 'number' && Number.isFinite(origin.y) && height > 0
      ? clamp(origin.y / height) * height
      : height / 2,
  };
}

function summon(origin?: SummonOrigin) {
  clearParticleTimers();
  particles = [];
  phase = 'summoning';
  canvas.classList.remove('settled');
  canvas.classList.add('visible');
  summonOrigin = normalizedOrigin(origin);
  started = performance.now();
  currentRadius = 0;
  draw(started);
}

function dismiss(origin: SummonOrigin = summonOrigin) {
  clearParticleTimers();
  if (phase === 'idle' || phase === 'dismissing') return;
  const wasSettled = phase === 'settled';
  dismissOrigin = normalizedOrigin(origin);
  phase = 'dismissing';
  dismissStarted = performance.now();
  dismissStartRadius = wasSettled
    ? Math.max(...cornerDistances(dismissOrigin)) + 2
    : Math.max(3, currentRadius);
  canvas.classList.remove('settled');
  queueDraw();
}

async function toggle() {
  try {
    const origin = await invoke<SummonOrigin>('cursor_origin');
    phase === 'idle' ? summon(origin) : dismiss(origin);
  } catch (error) {
    console.error('Unable to capture the cursor position', error);
  }
}

async function handleDevelopmentAction(action: string) {
  try {
    const origin = normalizedOrigin(await invoke<SummonOrigin>('cursor_origin'));
    if (action === 'aura') {
      setCursorControlAura(!controlAuraEnabled, origin);
    } else if (action === 'movement') {
      setCursorControlAura(true, origin);
      moveJarvisCursor(testMovementTarget(origin), origin);
    } else if (action === 'click') {
      cursorPosition = origin;
      showJarvisClick(origin);
    } else if (action === 'action') {
      runAutonomousAction(origin, testMovementTarget(origin));
    }
  } catch (error) {
    console.error('Unable to run the JARVIS cursor visual', error);
  }
}

resize();
addEventListener('resize', resize);
if (isTauri()) {
  await listen('jarvis-toggle', toggle);
  await listen<string>('jarvis-dev-action', (event) => handleDevelopmentAction(event.payload));
  await invoke('overlay_ready');
} else {
  // Browser-only preview; native operation uses the global shortcut.
  addEventListener('keydown', (event) => {
    if (event.code === 'KeyJ' && event.ctrlKey && event.altKey && !event.repeat) {
      phase === 'idle' ? summon() : dismiss();
    }
  });
}
