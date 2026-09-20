import './settings.css';
import {
  DEFAULT_VISUAL_SETTINGS,
  type NumericSetting,
  broadcastVisualSettings,
  loadVisualSettings,
  normalizeVisualSettings,
  persistVisualSettings,
  settingRange,
} from './visual-settings';

type Tab = 'general' | 'appearance' | 'mouse';
interface SliderControl {
  key: NumericSetting;
  label: string;
  description: string;
}
interface ControlGroup {
  title: string;
  description: string;
  controls: SliderControl[];
}

const pages: Record<Exclude<Tab, 'general'>, ControlGroup[]> = {
  appearance: [
    {
      title: 'Overall',
      description: 'Balance the entire visual system and its pace.',
      controls: [
        { key: 'visualIntensity', label: 'Visual intensity', description: 'Brightness of the complete JARVIS visual layer.' },
        { key: 'animationSpeed', label: 'Animation speed', description: 'Overall pace for visual transitions and motion.' },
      ],
    },
    {
      title: 'Border',
      description: 'Tune the settled screen-edge presence.',
      controls: [
        { key: 'borderGlowIntensity', label: 'Border glow', description: 'Brightness of the illuminated screen edge.' },
        { key: 'borderBloomAmount', label: 'Border bloom', description: 'How far soft light extends inward from the edge.' },
        { key: 'borderBreathingIntensity', label: 'Border breathing', description: 'Strength of the slow settled pulse.' },
        { key: 'borderParticleAmount', label: 'Border particles', description: 'Amount and frequency of edge motes.' },
        { key: 'borderParticleTravelDistance', label: 'Particle travel', description: 'How far edge motes drift into the screen.' },
      ],
    },
    {
      title: 'Summon and dismiss',
      description: 'Control how JARVIS arrives and leaves.',
      controls: [
        { key: 'summonAnimationSpeed', label: 'Summon speed', description: 'Pace of the cursor-origin ripple.' },
        { key: 'rippleIntensity', label: 'Ripple intensity', description: 'Brightness of the summon wave.' },
        { key: 'dismissAnimationSpeed', label: 'Dismiss speed', description: 'Pace of the closing animation.' },
      ],
    },
  ],
  mouse: [
    {
      title: 'Cursor aura',
      description: 'Pure blue-white illumination around the real pointer.',
      controls: [
        { key: 'auraSize', label: 'Aura size', description: 'Overall reach of the feathered bloom.' },
        { key: 'auraBrightness', label: 'Aura brightness', description: 'Strength of the core and outer light.' },
        { key: 'auraBlueBalance', label: 'Blue balance', description: 'Color richness of the pale-blue bloom.' },
        { key: 'auraFeathering', label: 'Aura feathering', description: 'Softness and spread of the outer fade.' },
        { key: 'cursorParticleAmount', label: 'Cursor particles', description: 'Amount of subtle motes around the aura.' },
        { key: 'cursorParticleTravelDistance', label: 'Particle travel', description: 'How far cursor motes drift before fading.' },
      ],
    },
    {
      title: 'Movement',
      description: 'Keep autonomous motion purposeful and easy to follow.',
      controls: [
        { key: 'movementSpeed', label: 'Movement speed', description: 'Pace of autonomous cursor travel.' },
        { key: 'pathPersonality', label: 'Path personality', description: 'Amount of restrained organic curvature.' },
        { key: 'trailIntensity', label: 'Trail intensity', description: 'Visibility of the fading movement path.' },
        { key: 'trailLifetime', label: 'Trail lifetime', description: 'How long the path remains visible.' },
      ],
    },
    {
      title: 'Click response',
      description: 'Tune the existing glossy screen-field ripple.',
      controls: [
        { key: 'clickRippleIntensity', label: 'Ripple intensity', description: 'Strength of the click wave and local response.' },
        { key: 'clickRippleSpeed', label: 'Ripple speed', description: 'How quickly the wave crosses the display.' },
        { key: 'screenFieldIntensity', label: 'Screen-field response', description: 'Visibility of microscopic reflected points.' },
        { key: 'borderImpactIntensity', label: 'Border impact', description: 'Strength of the edge response when the wave arrives.' },
      ],
    },
  ],
};

const app = document.querySelector<HTMLDivElement>('#app')!;
app.innerHTML = `
  <div class="settings-shell">
    <aside class="settings-sidebar" aria-label="Settings categories">
      <div class="brand"><span class="brand-mark" aria-hidden="true"></span><div><strong>JARVIS</strong><span>Settings</span></div></div>
      <nav class="settings-nav">
        <button class="nav-item active" data-tab="general"><span>General</span></button>
        <button class="nav-item" data-tab="appearance"><span>Appearance</span></button>
        <button class="nav-item" data-tab="mouse"><span>Mouse Control</span></button>
      </nav>
      <button id="reset-all" class="reset-button">Reset to defaults</button>
    </aside>
    <main class="settings-content">
      <header><p class="eyebrow">JARVIS CONTROL SURFACE</p><h1 id="page-title">General</h1><p id="page-description">Core comfort and accessibility preferences.</p></header>
      <div id="settings-page" class="settings-page"></div>
      <div id="save-status" class="save-status" role="status" aria-live="polite">Settings are saved automatically</div>
    </main>
  </div>`;

const pageElement = document.querySelector<HTMLDivElement>('#settings-page')!;
const titleElement = document.querySelector<HTMLHeadingElement>('#page-title')!;
const descriptionElement = document.querySelector<HTMLParagraphElement>('#page-description')!;
const statusElement = document.querySelector<HTMLDivElement>('#save-status')!;
let settings = await loadVisualSettings();
let activeTab: Tab = 'general';
let saveTimer = 0;

function scheduleUpdate() {
  void broadcastVisualSettings(settings);
  statusElement.textContent = 'Applying changes…';
  clearTimeout(saveTimer);
  saveTimer = window.setTimeout(async () => {
    try {
      await persistVisualSettings(settings);
      statusElement.textContent = 'Saved';
    } catch (error) {
      console.error('Unable to save JARVIS settings', error);
      statusElement.textContent = 'Could not save settings';
    }
  }, 180);
}

function slider(control: SliderControl) {
  const [minimum, maximum] = settingRange(control.key);
  const row = document.createElement('div');
  row.className = 'control-row';
  row.innerHTML = `
    <div class="control-copy"><label for="${control.key}">${control.label}</label><p>${control.description}</p></div>
    <div class="slider-wrap">
      <output for="${control.key}">${settings[control.key]}%</output>
      <input id="${control.key}" type="range" min="${minimum}" max="${maximum}" step="1" value="${settings[control.key]}" aria-label="${control.label}">
    </div>`;
  const input = row.querySelector<HTMLInputElement>('input')!;
  const output = row.querySelector<HTMLOutputElement>('output')!;
  input.addEventListener('input', () => {
    settings[control.key] = Number(input.value);
    output.value = `${input.value}%`;
    scheduleUpdate();
  });
  return row;
}

function renderGeneral() {
  const section = document.createElement('section');
  section.className = 'settings-card';
  section.innerHTML = `
    <div class="section-heading"><div><h2>Accessibility</h2><p>Adapt motion while keeping JARVIS visually clear.</p></div></div>
    <label class="toggle-row" for="reduced-motion">
      <span><strong>Reduced motion</strong><small>Shorten animated transitions and suppress decorative breathing.</small></span>
      <input id="reduced-motion" type="checkbox" ${settings.reducedMotion ? 'checked' : ''}>
      <span class="toggle" aria-hidden="true"></span>
    </label>`;
  section.querySelector<HTMLInputElement>('#reduced-motion')!.addEventListener('change', (event) => {
    settings.reducedMotion = (event.currentTarget as HTMLInputElement).checked;
    scheduleUpdate();
  });
  pageElement.append(section);

  const note = document.createElement('section');
  note.className = 'settings-card quiet-card';
  note.innerHTML = '<h2>More controls are coming</h2><p>Voice, hotkeys, permissions, startup behavior, and assistant preferences can be added here without changing the visual settings structure.</p>';
  pageElement.append(note);
}

function renderPage() {
  pageElement.replaceChildren();
  if (activeTab === 'general') {
    titleElement.textContent = 'General';
    descriptionElement.textContent = 'Core comfort and accessibility preferences.';
    renderGeneral();
    return;
  }
  titleElement.textContent = activeTab === 'appearance' ? 'Appearance' : 'Mouse Control';
  descriptionElement.textContent = activeTab === 'appearance'
    ? 'Shape the light, motion, and screen-edge presence.'
    : 'Tune how JARVIS guides, moves, and clicks.';
  for (const group of pages[activeTab]) {
    const section = document.createElement('section');
    section.className = 'settings-card';
    section.innerHTML = `<div class="section-heading"><div><h2>${group.title}</h2><p>${group.description}</p></div></div>`;
    for (const control of group.controls) section.append(slider(control));
    pageElement.append(section);
  }
}

for (const button of document.querySelectorAll<HTMLButtonElement>('.nav-item')) {
  button.addEventListener('click', () => {
    activeTab = button.dataset.tab as Tab;
    document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item === button));
    renderPage();
    document.querySelector<HTMLElement>('.settings-content')!.scrollTop = 0;
  });
}

document.querySelector<HTMLButtonElement>('#reset-all')!.addEventListener('click', () => {
  settings = normalizeVisualSettings(DEFAULT_VISUAL_SETTINGS);
  renderPage();
  scheduleUpdate();
});

renderPage();
