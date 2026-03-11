const { app, BrowserWindow, ipcMain } = require('electron')
const path = require('path')
const Store = require('electron-store').default
const { PythonBridge } = require('./python-bridge.cjs')

const store = new Store({ name: 'haumea-credentials' })

const TITLEBAR_HEIGHT = 40

let mainWindow
let pythonBridge

function createWindow() {
    const isMac = process.platform === 'darwin'

    mainWindow = new BrowserWindow({
        width: 1360,
        height: 920,
        minWidth: 1180,
        minHeight: 780,
        icon: path.join(__dirname, '..', 'icon.ico'),
        autoHideMenuBar: true,
        backgroundColor: '#060609',
        titleBarStyle: isMac ? 'hiddenInset' : 'hidden',
        ...(isMac
            ? {}
            : {
                titleBarOverlay: {
                    color: '#0c0c12',
                    symbolColor: '#eae8e4',
                    height: TITLEBAR_HEIGHT,
                },
            }),
        webPreferences: {
            preload: path.join(__dirname, 'preload.cjs'),
            contextIsolation: true,
            nodeIntegration: false,
        },
    })

    if (process.env.NODE_ENV === 'development' || process.argv.includes('--dev')) {
        mainWindow.loadURL('http://localhost:5173')
    } else {
        mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
    }

    mainWindow.on('closed', () => {
        mainWindow = null
    })
}

app.whenReady().then(() => {
    pythonBridge = new PythonBridge()

    pythonBridge.onLog((data) => {
        mainWindow?.webContents.send('python:log', data)
    })
    pythonBridge.onProgress((data) => {
        mainWindow?.webContents.send('python:progress', data)
    })
    pythonBridge.onStatus((data) => {
        mainWindow?.webContents.send('python:status', data)
    })

    ipcMain.handle('python:send', async (_event, method, params) => {
        return pythonBridge.send(method, params)
    })

    ipcMain.handle('python:start', async () => {
        return pythonBridge.start()
    })

    ipcMain.handle('python:stop', async () => {
        return pythonBridge.stop()
    })

    // Credential store IPC
    ipcMain.handle('store:get', (_event, key) => store.get(key))
    ipcMain.handle('store:set', (_event, key, value) => store.set(key, value))
    ipcMain.handle('store:delete', (_event, key) => store.delete(key))
    ipcMain.handle('store:getAll', () => store.store)

    pythonBridge.start()
    createWindow()
})

app.on('window-all-closed', () => {
    pythonBridge?.stop()
    app.quit()
})

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
