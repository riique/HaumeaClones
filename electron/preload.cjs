const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electron', {
    python: {
        start: () => ipcRenderer.invoke('python:start'),
        stop: () => ipcRenderer.invoke('python:stop'),
        send: (method, params) => ipcRenderer.invoke('python:send', method, params),

        onLog: (callback) => {
            const handler = (_event, data) => callback(data)
            ipcRenderer.on('python:log', handler)
            return () => ipcRenderer.removeListener('python:log', handler)
        },
        onProgress: (callback) => {
            const handler = (_event, data) => callback(data)
            ipcRenderer.on('python:progress', handler)
            return () => ipcRenderer.removeListener('python:progress', handler)
        },
        onStatus: (callback) => {
            const handler = (_event, data) => callback(data)
            ipcRenderer.on('python:status', handler)
            return () => ipcRenderer.removeListener('python:status', handler)
        },
    },

    store: {
        get: (key) => ipcRenderer.invoke('store:get', key),
        set: (key, value) => ipcRenderer.invoke('store:set', key, value),
        delete: (key) => ipcRenderer.invoke('store:delete', key),
        getAll: () => ipcRenderer.invoke('store:getAll'),
    },
})
