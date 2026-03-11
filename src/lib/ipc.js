const api = window.electron?.python

export const ipc = {
    start: () => api?.start() ?? Promise.resolve({ ok: false }),
    stop: () => api?.stop() ?? Promise.resolve(),
    send: (method, params = {}) => api?.send(method, params) ?? Promise.reject('No bridge'),

    onLog: (callback) => api?.onLog(callback) ?? (() => {}),
    onProgress: (callback) => api?.onProgress(callback) ?? (() => {}),
    onStatus: (callback) => api?.onStatus(callback) ?? (() => {}),
}
