import { isTauri } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';

const settingsPreview = new URLSearchParams(location.search).get('window') === 'settings';
const settingsWindow = isTauri() ? getCurrentWindow().label === 'settings' : settingsPreview;

if (settingsWindow) {
  void import('./settings-window');
} else {
  void import('./overlay');
}
