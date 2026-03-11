import { useState, useEffect, useCallback, useRef } from 'react'
import { ipc } from '../lib/ipc'

const store = window.electron?.store

export function useTelegram() {
    const [status, setStatus] = useState('disconnected')
    const [logs, setLogs] = useState([])
    const [progress, setProgress] = useState(null)
    const [user, setUser] = useState(null)
    const initialized = useRef(false)
    const autoLoginAttempted = useRef(false)

    useEffect(() => {
        if (initialized.current) return
        initialized.current = true

        ipc.start()

        const unsubLog = ipc.onLog((data) => {
            setLogs((prev) => [...prev.slice(-500), data])
        })

        const unsubProgress = ipc.onProgress((data) => {
            setProgress(data)
        })

        const unsubStatus = ipc.onStatus((data) => {
            setStatus(data.status)
        })

        return () => {
            unsubLog?.()
            unsubProgress?.()
            unsubStatus?.()
        }
    }, [])

    const clearLogs = useCallback(() => setLogs([]), [])

    const persistCredentials = useCallback(async (apiId, apiHash, phone) => {
        if (!store) return
        await store.set('credentials', { api_id: apiId, api_hash: apiHash, phone })
    }, [])

    const connect = useCallback(async (apiId, apiHash, phone, password) => {
        setStatus('connecting')
        try {
            const res = await ipc.send('connect', { api_id: apiId, api_hash: apiHash, phone, password })
            if (res.needs_code) {
                setStatus('awaiting_code')
                // persist early so auto-login works after code/2fa completes
                await persistCredentials(apiId, apiHash, phone)
            } else if (res.user) {
                setUser(res.user)
                setStatus('connected')
                await persistCredentials(apiId, apiHash, phone)
            }
            return res
        } catch (e) {
            setStatus('disconnected')
            throw e
        }
    }, [persistCredentials])

    const submitCode = useCallback(async (phone, code, password) => {
        try {
            const res = await ipc.send('submit_code', { phone, code, password })
            if (res.needs_2fa) {
                setStatus('awaiting_2fa')
            } else if (res.user) {
                setUser(res.user)
                setStatus('connected')
            }
            return res
        } catch (e) {
            setStatus('disconnected')
            throw e
        }
    }, [])

    const submit2FA = useCallback(async (password) => {
        try {
            const res = await ipc.send('submit_2fa', { password })
            if (res.user) {
                setUser(res.user)
                setStatus('connected')
            }
            return res
        } catch (e) {
            setStatus('disconnected')
            throw e
        }
    }, [])

    const autoLogin = useCallback(async (apiId, apiHash) => {
        if (autoLoginAttempted.current || status === 'connected' || user) {
            return { ok: false, skipped: true }
        }

        autoLoginAttempted.current = true
        setStatus('connecting')
        try {
            const res = await ipc.send('auto_login', { api_id: apiId, api_hash: apiHash })
            if (res.ok && res.user) {
                setUser(res.user)
                setStatus('connected')
            } else {
                setStatus('disconnected')
            }
            return res
        } catch {
            setStatus('disconnected')
        }
    }, [status, user])

    const loadStoredCredentials = useCallback(async () => {
        if (!store) return null
        return store.get('credentials')
    }, [])

    const clone = useCallback((params) => ipc.send('clone', params), [])
    const multiClone = useCallback((params) => ipc.send('multi_clone', params), [])
    const forumClone = useCallback((params) => ipc.send('forum_clone', params), [])
    const restrictedClone = useCallback((params) => ipc.send('restricted_clone', params), [])
    const stopClone = useCallback(() => ipc.send('stop'), [])
    const skipDownload = useCallback(() => ipc.send('skip_download'), [])

    const loadConfig = useCallback(() => ipc.send('load_config'), [])
    const saveConfig = useCallback((config) => ipc.send('save_config', { config }), [])
    const getSavedProgress = useCallback(() => ipc.send('get_saved_progress'), [])
    const deleteProgress = useCallback((filePath) => ipc.send('delete_progress', { file_path: filePath }), [])

    return {
        status, logs, progress, user,
        connect, submitCode, submit2FA, autoLogin,
        clone, multiClone, forumClone, restrictedClone,
        stopClone, skipDownload,
        loadConfig, saveConfig,
        getSavedProgress, deleteProgress,
        clearLogs,
        loadStoredCredentials, persistCredentials,
    }
}
