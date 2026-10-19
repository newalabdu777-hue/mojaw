'use strict';

const { app, BrowserWindow, shell } = require('electron');
const path = require('node:path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#f5f7f6',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });

  win.once('ready-to-show', () => win.show());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) {
      void shell.openExternal(url);
    }
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    const localIndex = pathToFileURL(path.join(__dirname, '..', 'dist', 'index.html'));
    // Only the packaged entry point may navigate in the renderer. Blocking all other
    // URLs (including arbitrary file:// URLs) prevents the app window being redirected.
    if (url !== localIndex && !url.startsWith(`${localIndex}#`)) event.preventDefault();
  });

  void win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
}

function pathToFileURL(filePath) {
  return require('node:url').pathToFileURL(filePath).href;
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
