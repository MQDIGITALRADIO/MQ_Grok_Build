/**
 * MQ Radio — Electron preload.
 * Exposes a safe desktop bridge so the On-Air UI can resolve absolute paths
 * for hotkey drops. Electron 32+ removed File.path; use webUtils instead.
 */
const { contextBridge, webUtils } = require('electron');

contextBridge.exposeInMainWorld('mqDesktop', {
  isElectron: true,
  /** Packaging version string (Electron package.json). */
  appVersion: (() => {
    try {
      return require('./package.json').version || '0.1.2';
    } catch (_) {
      return '0.1.2';
    }
  })(),
  /**
   * Absolute filesystem path for a dropped File (Electron only).
   * Returns "" when unavailable.
   */
  getPathForFile(file) {
    if (!file) return '';
    try {
      if (webUtils && typeof webUtils.getPathForFile === 'function') {
        const p = webUtils.getPathForFile(file);
        return typeof p === 'string' ? p : '';
      }
    } catch (_) {
      /* ignore */
    }
    // Legacy Electron: File.path may still exist on the object.
    try {
      if (file.path && typeof file.path === 'string') return file.path;
    } catch (_) {
      /* ignore */
    }
    return '';
  },
});
