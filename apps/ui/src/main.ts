import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';

const loaders = {
  settings: () => import('./settings-window'),
  assistant: () => import('./assistant-window'),
  main: () => import('./overlay'),
};
const label = isTauri() ? getCurrentWindow().label : new URLSearchParams(location.search).get('window');
void loaders[label === 'settings' || label === 'assistant' ? label : 'main']();
