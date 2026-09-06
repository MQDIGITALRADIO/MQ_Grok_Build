/**
 * MQ Radio — Electron shell.
 * Starts the bundled MQRadioEngine (Python On-Air server) and opens the UI.
 *
 * Future AU host (not implemented): the Program path is
 *   source → [AU insert if set] → native processing → device
 * Selected AU name persists in Settings (`insert.slot` / `insert.name`).
 * Until this shell (or a native helper) hosts Audio Units, the engine sets
 * `audio_route.au_insert.warning = "au_insert_inactive"` and still runs native.
 * A future Mac build may load the selected AU in-process or via a helper bridge;
 * do not claim AU hosting until that path is real.
 */
const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const HOST = '127.0.0.1';
const PORT = 8080;
const READY_URL = `http://${HOST}:${PORT}/`;

let mainWindow = null;
let engineProcess = null;
let quitting = false;

function engineBinaryPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'MQRadioEngine', 'MQRadioEngine');
  }
  const candidates = [
    path.join(__dirname, 'resources', 'MQRadioEngine', 'MQRadioEngine'),
    path.join(__dirname, '..', 'dist', 'MQRadioEngine', 'MQRadioEngine'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return candidates[0];
}

function startEngine() {
  const bin = engineBinaryPath();
  if (!fs.existsSync(bin)) {
    dialog.showErrorBox(
      'MQ Radio',
      `Could not find the MQ Radio engine at:\n${bin}\n\nReinstall from the DMG or rebuild the desktop package.`
    );
    app.quit();
    return;
  }

  try {
    fs.chmodSync(bin, 0o755);
  } catch (_) {
    /* ignore */
  }

  const dataDir = path.join(app.getPath('userData'), 'data');
  fs.mkdirSync(dataDir, { recursive: true });

  const env = {
    ...process.env,
    MQ_RADIO_DATA_DIR: dataDir,
    MQ_RADIO_HOST: HOST,
    MQ_RADIO_PORT: String(PORT),
  };

  engineProcess = spawn(bin, [], {
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  engineProcess.stdout.on('data', (buf) => {
    console.log(`[engine] ${buf.toString().trimEnd()}`);
  });
  engineProcess.stderr.on('data', (buf) => {
    console.error(`[engine] ${buf.toString().trimEnd()}`);
  });
  engineProcess.on('exit', (code, signal) => {
    console.log(`[engine] exited code=${code} signal=${signal}`);
    engineProcess = null;
    if (!quitting) {
      dialog.showErrorBox(
        'MQ Radio',
        'The radio engine stopped unexpectedly. The app will close.'
      );
      app.quit();
    }
  });
}

function waitForServer(timeoutMs = 90000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const req = http.get(READY_URL, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) {
          resolve();
        } else {
          retry();
        }
      });
      req.on('error', retry);
      req.setTimeout(2000, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error('Timed out waiting for On-Air server'));
        return;
      }
      setTimeout(tryOnce, 400);
    };
    tryOnce();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    title: 'MQ Radio',
    backgroundColor: '#0b1020',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadURL(READY_URL);

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function stopEngine() {
  if (!engineProcess) return;
  const child = engineProcess;
  engineProcess = null;
  try {
    child.kill('SIGTERM');
  } catch (_) {
    /* ignore */
  }
  setTimeout(() => {
    try {
      if (!child.killed) child.kill('SIGKILL');
    } catch (_) {
      /* ignore */
    }
  }, 3000);
}

app.whenReady().then(async () => {
  startEngine();
  try {
    await waitForServer();
  } catch (err) {
    dialog.showErrorBox(
      'MQ Radio',
      `Could not start the On-Air server.\n\n${err.message}\n\nIf Gatekeeper blocked the engine binary, right-click the app and choose Open once.`
    );
    quitting = true;
    stopEngine();
    app.quit();
    return;
  }
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', () => {
  quitting = true;
  stopEngine();
});

app.on('window-all-closed', () => {
  quitting = true;
  stopEngine();
  app.quit();
});
