import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';

const settingsPreview = new URLSearchParams(location.search).get('window') === 'settings';
const settingsWindow = isTauri() ? getCurrentWindow().label === 'settings' : settingsPreview;

if (isTauri() && getCurrentWindow().label === 'assistant') {
  void import('./assistant-window');
} else if (settingsWindow) {
  void import('./settings-window');
} else {
  void import('./overlay');
}
