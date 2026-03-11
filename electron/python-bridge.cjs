const { spawn } = require('child_process')
const path = require('path')
const { app } = require('electron')

class PythonBridge {
    constructor() {
        this.process = null
        this.pending = new Map()
        this.nextId = 1
        this.logCallback = null
        this.progressCallback = null
        this.statusCallback = null
        this.buffer = ''
        this.startPromise = null
    }

    _getPythonPath() {
        if (app.isPackaged) {
            return path.join(process.resourcesPath, 'backend', 'haumea-backend.exe')
        }
        return 'python'
    }

    _getArgs() {
        if (app.isPackaged) return []
        return [path.join(__dirname, '..', 'backend', 'server.py')]
    }

    _getCwd() {
        if (app.isPackaged) return app.getPath('userData')
        return path.join(__dirname, '..')
    }

    start() {
        if (this.process) return Promise.resolve({ ok: true })
        if (this.startPromise) return this.startPromise

        const pythonPath = this._getPythonPath()
        const args = this._getArgs()
        const cwd = this._getCwd()

        this.startPromise = new Promise((resolve) => {
            this.process = spawn(pythonPath, args, {
                cwd,
                stdio: ['pipe', 'pipe', 'pipe'],
                env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONPATH: path.join(__dirname, '..', 'backend') },
            })

            this.process.once('spawn', () => {
                resolve({ ok: true })
            })

            this.process.once('error', (err) => {
                console.error('[python:start:error]', err)
                this.process = null
                this.startPromise = null
                resolve({ ok: false, error: err.message })
            })

            this.process.stdout.on('data', (data) => this._onData(data.toString()))
            this.process.stderr.on('data', (data) => {
                const msg = data.toString().trim()
                if (msg) console.error('[python:stderr]', msg)
            })

            this.process.on('close', (code) => {
                console.log(`[python] process exited with code ${code}`)
                this.process = null
                this.startPromise = null
                for (const [id, { reject }] of this.pending) {
                    reject(new Error('Python process exited'))
                }
                this.pending.clear()
            })
        })

        return this.startPromise
    }

    stop() {
        if (!this.process) return
        try {
            this.send('shutdown', {}).catch(() => { })
            setTimeout(() => {
                if (this.process) {
                    this.process.kill()
                    this.process = null
                }
            }, 2000)
        } catch {
            this.process?.kill()
            this.process = null
        }
    }

    async send(method, params = {}) {
        if (!this.process) {
            const started = await this.start()
            if (!started?.ok || !this.process) {
                throw new Error(started?.error || 'Python process not running')
            }
        }

        return new Promise((resolve, reject) => {
            const id = this.nextId++
            const msg = JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'

            this.pending.set(id, { resolve, reject })

            // Timeout after 5 minutes for long operations
            const timeout = setTimeout(() => {
                if (this.pending.has(id)) {
                    this.pending.delete(id)
                    reject(new Error('Request timeout'))
                }
            }, 300000)

            this.pending.set(id, {
                resolve: (val) => { clearTimeout(timeout); resolve(val) },
                reject: (err) => { clearTimeout(timeout); reject(err) },
            })
            this.process.stdin.write(msg)
        })
    }

    _onData(raw) {
        this.buffer += raw
        const lines = this.buffer.split('\n')
        this.buffer = lines.pop() || ''

        for (const line of lines) {
            if (!line.trim()) continue
            try {
                const msg = JSON.parse(line)

                // Notification (no id) — events pushed from Python
                if (!msg.id && msg.method) {
                    if (msg.method === 'log' && this.logCallback) this.logCallback(msg.params)
                    else if (msg.method === 'progress' && this.progressCallback) this.progressCallback(msg.params)
                    else if (msg.method === 'status' && this.statusCallback) this.statusCallback(msg.params)
                    continue
                }

                // Response to a request
                if (msg.id && this.pending.has(msg.id)) {
                    const { resolve, reject } = this.pending.get(msg.id)
                    this.pending.delete(msg.id)
                    if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)))
                    else resolve(msg.result)
                }
            } catch {
                // Not JSON, ignore
            }
        }
    }

    onLog(cb) { this.logCallback = cb }
    onProgress(cb) { this.progressCallback = cb }
    onStatus(cb) { this.statusCallback = cb }
}

module.exports = { PythonBridge }
