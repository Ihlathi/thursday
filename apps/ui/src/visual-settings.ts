import { emit } from '@tauri-apps/api/event';
import { invoke, isTauri } from '@tauri-apps/api/core';

export interface VisualSettings {
  visualIntensity: number;
  animationSpeed: number;
  reducedMotion: boolean;
  borderGlowIntensity: number;
  borderBloomAmount: number;
  borderBreathingIntensity: number;
  borderParticleAmount: number;
  borderParticleTravelDistance: number;
  summonAnimationSpeed: number;
  rippleIntensity: number;
  dismissAnimationSpeed: number;
  auraSize: number;
  auraBrightness: number;
  auraBlueBalance: number;
  auraFeathering: number;
  cursorParticleAmount: number;
  cursorParticleTravelDistance: number;
  movementSpeed: number;
  pathPersonality: number;
  trailIntensity: number;
  trailLifetime: number;
  clickRippleIntensity: number;
  clickRippleSpeed: number;
  screenFieldIntensity: number;
  borderImpactIntensity: number;
}

export type NumericSetting = Exclude<keyof VisualSettings, 'reducedMotion'>;

export const DEFAULT_VISUAL_SETTINGS: VisualSettings = {
  visualIntensity: 100,
  animationSpeed: 100,
  reducedMotion: false,
  borderGlowIntensity: 100,
  borderBloomAmount: 100,
  borderBreathingIntensity: 100,
  borderParticleAmount: 100,
  borderParticleTravelDistance: 100,
  summonAnimationSpeed: 100,
  rippleIntensity: 100,
  dismissAnimationSpeed: 100,
  auraSize: 100,
  auraBrightness: 100,
  auraBlueBalance: 100,
  auraFeathering: 100,
  cursorParticleAmount: 100,
  cursorParticleTravelDistance: 100,
  movementSpeed: 100,
  pathPersonality: 100,
  trailIntensity: 100,
  trailLifetime: 100,
  clickRippleIntensity: 100,
  clickRippleSpeed: 100,
  screenFieldIntensity: 100,
  borderImpactIntensity: 100,
};

export const VISUAL_SETTINGS_EVENT = 'visual-settings-changed';

const ranges: Record<NumericSetting, [number, number]> = {
  visualIntensity: [40, 150],
  animationSpeed: [50, 160],
  borderGlowIntensity: [30, 170],
  borderBloomAmount: [40, 180],
  borderBreathingIntensity: [0, 180],
  borderParticleAmount: [0, 180],
  borderParticleTravelDistance: [40, 180],
  summonAnimationSpeed: [50, 170],
  rippleIntensity: [30, 170],
  dismissAnimationSpeed: [50, 170],
  auraSize: [55, 170],
  auraBrightness: [30, 170],
  auraBlueBalance: [40, 160],
  auraFeathering: [50, 160],
  cursorParticleAmount: [0, 180],
  cursorParticleTravelDistance: [40, 180],
  movementSpeed: [50, 170],
  pathPersonality: [20, 150],
  trailIntensity: [20, 170],
  trailLifetime: [40, 180],
  clickRippleIntensity: [30, 170],
  clickRippleSpeed: [50, 170],
  screenFieldIntensity: [0, 180],
  borderImpactIntensity: [0, 180],
};

export function settingRange(key: NumericSetting) {
  return ranges[key];
}

export function normalizeVisualSettings(value: unknown): VisualSettings {
  const source = value && typeof value === 'object' ? value as Partial<VisualSettings> : {};
  const normalized = { ...DEFAULT_VISUAL_SETTINGS };
  for (const key of Object.keys(ranges) as NumericSetting[]) {
    const [minimum, maximum] = ranges[key];
    const candidate = source[key];
    normalized[key] = typeof candidate === 'number' && Number.isFinite(candidate)
      ? Math.max(minimum, Math.min(maximum, Math.round(candidate)))
      : DEFAULT_VISUAL_SETTINGS[key];
  }
  normalized.reducedMotion = typeof source.reducedMotion === 'boolean'
    ? source.reducedMotion
    : DEFAULT_VISUAL_SETTINGS.reducedMotion;
  return normalized;
}

export async function loadVisualSettings(): Promise<VisualSettings> {
  if (!isTauri()) return { ...DEFAULT_VISUAL_SETTINGS };
  try {
    const json = await invoke<string | null>('load_visual_settings');
    return json ? normalizeVisualSettings(JSON.parse(json)) : { ...DEFAULT_VISUAL_SETTINGS };
  } catch (error) {
    console.error('Unable to load JARVIS visual settings', error);
    return { ...DEFAULT_VISUAL_SETTINGS };
  }
}

export async function broadcastVisualSettings(settings: VisualSettings) {
  if (isTauri()) await emit(VISUAL_SETTINGS_EVENT, normalizeVisualSettings(settings));
}

export async function persistVisualSettings(settings: VisualSettings) {
  if (!isTauri()) return;
  await invoke('save_visual_settings', { json: JSON.stringify(normalizeVisualSettings(settings)) });
}
