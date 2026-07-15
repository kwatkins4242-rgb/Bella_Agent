const { app, BrowserWindow, ipcMain, shell, Menu, Tray, nativeImage, dialog } = require('electron');
const path = require('path');
const fs = require('fs');

// ═══════════════════════════════════════
// STATE
// ═══════════════════════════════════════
let mainWindow = null;
let tray = null;
let ptyProcess = null;

// ═══════════════════════════════════════
// PATHS
// ═══════════════════════════════════════
const isDev = process.argv.includes('--dev');
const USER_DATA = app.getPath('userData');
const CONFIG_FILE = path.join(USER_DATA, 'odin-config.json');
const HTML_FILE = isDev 
    ? path.join(__dirname, 'odin-shell.html')
    : `file://${path.join(__dirname, 'odin-shell.html')}`;

// ═══════════════════════════════════════
// CONFIG
// ═══════════════════════════════════════
function loadConfig() {
    try {
        if (fs.existsSync(CONFIG_FILE)) {
            return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
        }
    } catch(e) { console.error('[CONFIG] Load failed:', e.message); }
    return getDefaultConfig();
}

function saveConfig(patch) {
    try {
        const cfg = loadConfig();
        const merged = { ...cfg, ...patch };
        fs.writeFileSync(CONFIG_FILE, JSON.stringify(merged, null, 2));
        return { ok: true };
    } catch(e) {
        console.error('[CONFIG] Save failed:', e.message);
        return { ok: false, error: e.message };
    }
}

function getDefaultConfig() {
    return {
        hudUrl: "",
        hudBrainOrigin: "",
        hudBrainChatKey: "",
        hudLlmBackend: "",
        browserUrl: "https://duckduckgo.com/",
        swaggerUrl: "",
        n8nPanelUrl: "",
        moonshotUrl: "https://api.moonshot.cn/v1",
        nvidiaUrl: "https://integrate.api.nvidia.com/v1",
        mongoUri: "",
        elevenVoice: "",
        n8nUrl: "",
        mcpUrl: "",
    };
}

// ═══════════════════════════════════════
// PTY (Terminal)
// ═══════════════════════════════════════
let pty = null;
let shell_name = process.platform === 'win32' ? 'powershell.exe' : 'bash';

function spawnPty(cols, rows) {
    try {
        pty = require('node-pty').spawn(shell_name, [], {
            name: 'xterm-256color',
            cols: cols || 80,
            rows: rows || 24,
            cwd: process.env.HOME || process.env.USERPROFILE,
            env: process.env,
        });

        pty.onData((data) => {
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.webContents.send('pty-data', data);
            }
        });

        pty.onExit(({ exitCode }) => {
            console.log('[PTY] Exited with code:', exitCode);
            pty = null;
        });

        return { ok: true };
    } catch(e) {
        console.error('[PTY] Spawn failed:', e.message);
        return { ok: false, error: e.message };
    }
}

function writePty(data) {
    if (pty) pty.write(data);
}

function resizePty(cols, rows) {
    if (pty) pty.resize(cols, rows);
}

// ═══════════════════════════════════════
// WINDOW
// ═══════════════════════════════════════
function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1600,
        height: 1000,
        minWidth: 1024,
        minHeight: 700,
        title: 'ODIN · Operational Digital Intelligence Node',
        backgroundColor: '#080b10',
        show: false,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            spellcheck: false,
            webviewTag: true,
        },
    });

    // Splash
    mainWindow.loadURL(`data:text/html,<html>
        <body style="background:#080b10;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-family:monospace;color:#c9a84c;">
            <div style="text-align:center;">
                <div style="font-size:72px;font-weight:700;letter-spacing:12px;text-shadow:0 0 40px rgba(201,168,76,.5);">ODIN</div>
                <div style="font-size:12px;letter-spacing:6px;color:#3dbdb5;margin-top:12px;">OPERATIONAL DIGITAL INTELLIGENCE NODE</div>
                <div style="font-size:10px;color:#4a5260;margin-top:20px;letter-spacing:3px;">LOADING...</div>
            </div>
        </body>
    </html>`);

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        mainWindow.loadURL(HTML_FILE);
    });

    // Menu
    const menuTemplate = [
        {
            label: 'ODIN',
            submenu: [
                { label: 'About ODIN', enabled: false },
                { type: 'separator' },
                { label: 'Developer Tools', accelerator: 'F12', click: () => mainWindow.webContents.toggleDevTools() },
                { type: 'separator' },
                { label: 'Quit', accelerator: 'CmdOrCtrl+Q', click: () => app.quit() },
            ],
        },
        {
            label: 'View',
            submenu: [
                { label: 'Reload', accelerator: 'CmdOrCtrl+R', click: () => mainWindow.webContents.reload() },
                { label: 'Hard Reload', accelerator: 'CmdOrCtrl+Shift+R', click: () => mainWindow.webContents.reloadIgnoringCache() },
                { type: 'separator' },
                { label: 'Zoom In', accelerator: 'CmdOrCtrl+Plus', role: 'zoomIn' },
                { label: 'Zoom Out', accelerator: 'CmdOrCtrl+-', role: 'zoomOut' },
                { label: 'Reset Zoom', accelerator: 'CmdOrCtrl+0', role: 'resetZoom' },
                { type: 'separator' },
                { label: 'Fullscreen', accelerator: 'F11', click: () => mainWindow.setFullScreen(!mainWindow.isFullScreen()) },
            ],
        },
        {
            label: 'Tools',
            submenu: [
                { label: 'New Conversation', accelerator: 'CmdOrCtrl+N', click: () => mainWindow.webContents.send('new-conv') },
                { label: 'Save Memory', accelerator: 'CmdOrCtrl+S', click: () => mainWindow.webContents.send('save-mem') },
                { type: 'separator' },
                { label: 'Bug Bounty Panel', click: () => mainWindow.webContents.send('toggle-panel', 'bounty') },
                { label: 'Hunt Mode', click: () => mainWindow.webContents.send('toggle-panel', 'hunt') },
                { label: 'Code Panel', click: () => mainWindow.webContents.send('toggle-panel', 'code') },
            ],
        },
        {
            label: 'Help',
            submenu: [
                { label: 'Open BELLA Server', click: () => shell.openExternal('http://45.76.238.174:8000') },
                { label: 'API Docs', click: () => shell.openExternal('http://45.76.238.174:8000/docs') },
                { type: 'separator' },
                { label: 'ODIN Docs', click: () => {} },
            ],
        },
    ];

    const menu = Menu.buildFromTemplate(menuTemplate);
    Menu.setApplicationMenu(menu);

    mainWindow.on('closed', () => { mainWindow = null; });
    mainWindow.on('unresponsive', () => { console.warn('[WINDOW] Unresponsive'); });
}

// ═══════════════════════════════════════
// TRAY
// ═══════════════════════════════════════
function createTray() {
    try {
        const iconPath = path.join(__dirname, 'static', 'icon.png');
        let icon;
        if (fs.existsSync(iconPath)) {
            icon = nativeImage.createFromPath(iconPath);
        } else {
            // Generate a simple icon
            icon = nativeImage.createEmpty();
        }
        tray = new Tray(icon.isEmpty() ? nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAAdgAAAHYBTnsmCAAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAEVSURBVDiNpZMxTsNAEEX/rBMFCooUKSgoKOjopsKFnolzIFJRUFBQPIBOQUNBwwMoaJAoKChSEAQJkzVxYnfG2d2QqN35z7zZndkBOABwm7VdwH3bPQT4ADYA3rXOuR3oAngGsLXO7QM0AH4BvM7qO4D2AGdZ+wRwH+BWazsAnmqd84DOOjcGcNTWugAcNu0jwBft/Qjwu9aeZ+1xW/sW4IXWqR7gbK19ALjbNh9oH/cA7gDsG4w/AE+19h3A7bb5DHBbax8BbmrtI8DNtvlM4FbTuQ+4YvA+BLhltE8Bd41eB+Ba09gBuGEw9gC+GIx9gDNG0wG4aTQyALeNxhPA34DvAD8Gv1LqAAAAAElFTkSuQmCC') : icon);
        
        const contextMenu = Menu.buildFromTemplate([
            { label: 'Show ODIN', click: () => mainWindow?.show() },
            { label: 'Hide ODIN', click: () => mainWindow?.hide() },
            { type: 'separator' },
            { label: 'New Conversation', click: () => mainWindow?.webContents.send('new-conv') },
            { label: 'Reload', click: () => mainWindow?.webContents.reload() },
            { type: 'separator' },
            { label: 'Quit', click: () => app.quit() },
        ]);

        tray.setToolTip('ODIN — Operational Digital Intelligence Node');
        tray.setContextMenu(contextMenu);
        tray.on('click', () => mainWindow?.show());
    } catch(e) { console.error('[TRAY] Failed:', e.message); }
}

// ═══════════════════════════════════════
// IPC HANDLERS
// ═══════════════════════════════════════
function setupIPC() {
    // Config
    ipcMain.handle('load-config', () => loadConfig());
    ipcMain.handle('save-config', (_, patch) => saveConfig(patch));

    // PTY
    ipcMain.handle('pty-spawn', (_, cols, rows) => spawnPty(cols, rows));
    ipcMain.on('pty-write', (_, data) => writePty(data));
    ipcMain.on('pty-resize', (_, cols, rows) => resizePty(cols, rows));

    // Shell
    ipcMain.handle('open-external', (_, url) => {
        shell.openExternal(url);
        return { ok: true };
    });

    ipcMain.handle('show-save-dialog', async (_, options) => {
        const result = await dialog.showSaveDialog(mainWindow, options);
        return result;
    });

    ipcMain.handle('show-open-dialog', async (_, options) => {
        const result = await dialog.showOpenDialog(mainWindow, options);
        return result;
    });

    // Clipboard
    ipcMain.handle('clipboard-write', (_, text) => {
        require('electron').clipboard.writeText(text);
        return { ok: true };
    });

    // File ops
    ipcMain.handle('read-file', async (_, filePath) => {
        try {
            const content = fs.readFileSync(filePath);
            return { ok: true, content: content.toString('base64') };
        } catch(e) {
            return { ok: false, error: e.message };
        }
    });

    ipcMain.handle('write-file', async (_, filePath, data) => {
        try {
            fs.writeFileSync(filePath, Buffer.from(data, 'base64'));
            return { ok: true };
        } catch(e) {
            return { ok: false, error: e.message };
        }
    });

    // App info
    ipcMain.handle('app-info', () => ({
        version: app.getVersion(),
        platform: process.platform,
        arch: process.arch,
        userData: USER_DATA,
    }));

    console.log('[IPC] Handlers registered');
}

// ═══════════════════════════════════════
// APP LIFECYCLE
// ═══════════════════════════════════════
app.whenReady().then(() => {
    console.log('[APP] Starting ODIN Shell...');
    console.log('[APP] Platform:', process.platform);
    console.log('[APP] User data:', USER_DATA);
    console.log('[APP] HTML:', HTML_FILE);

    setupIPC();
    createWindow();
    createTray();

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });

    console.log('[APP] Ready');
});

app.on('window-all-closed', () => {
    if (pty) { try { pty.kill(); } catch(e) {} }
    if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
    if (pty) { try { pty.kill(); } catch(e) {} }
    console.log('[APP] Shutting down');
});

process.on('uncaughtException', (e) => {
    console.error('[APP] Uncaught exception:', e.message);
});

process.on('unhandledRejection', (e) => {
    console.error('[APP] Unhandled rejection:', e.message);
});
