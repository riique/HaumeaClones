import { useEffect, useState } from 'react'
import Card from '../components/Card'
import Modal from '../components/Modal'

export default function ApiConfig({ telegram }) {
    const {
        status, user, connect, submitCode, submit2FA,
        autoLogin, loadConfig, saveConfig,
        loadStoredCredentials, persistCredentials,
    } = telegram

    const [apiId, setApiId] = useState('')
    const [apiHash, setApiHash] = useState('')
    const [phone, setPhone] = useState('')
    const [password, setPassword] = useState('')
    const [hideKeys, setHideKeys] = useState(false)

    const [antiFloodEnabled, setAntiFloodEnabled] = useState(true)
    const [pauseEveryMin, setPauseEveryMin] = useState('40')
    const [pauseEveryMax, setPauseEveryMax] = useState('60')
    const [pauseDurationMin, setPauseDurationMin] = useState('1.5')
    const [pauseDurationMax, setPauseDurationMax] = useState('3')

    const [codeModal, setCodeModal] = useState(false)
    const [tfaModal, setTfaModal] = useState(false)
    const [verifyCode, setVerifyCode] = useState('')
    const [tfaPassword, setTfaPassword] = useState('')
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        let cancelled = false

        async function init() {
            // 1. Try stored credentials for instant auto-login
            const stored = await loadStoredCredentials()
            if (!cancelled && stored?.api_id && stored?.api_hash) {
                setApiId(stored.api_id)
                setApiHash(stored.api_hash)
                if (stored.phone) setPhone(stored.phone)

                if (!user && status === 'disconnected') {
                    autoLogin(stored.api_id, stored.api_hash)
                }
            }

            // 2. Load remaining config (anti-flood, etc) from backend
            try {
                const cfg = await loadConfig()
                if (cancelled) return

                if (cfg.api_id && !stored?.api_id) setApiId(cfg.api_id)
                if (cfg.api_hash && !stored?.api_hash) setApiHash(cfg.api_hash)
                if (cfg.phone && !stored?.phone) setPhone(cfg.phone)
                if (cfg.anti_flood_enabled !== undefined) setAntiFloodEnabled(cfg.anti_flood_enabled)
                if (cfg.anti_flood_pause_every_min) setPauseEveryMin(String(cfg.anti_flood_pause_every_min))
                if (cfg.anti_flood_pause_every_max) setPauseEveryMax(String(cfg.anti_flood_pause_every_max))
                if (cfg.anti_flood_pause_every && !cfg.anti_flood_pause_every_min && !cfg.anti_flood_pause_every_max) {
                    setPauseEveryMin(String(cfg.anti_flood_pause_every))
                    setPauseEveryMax(String(cfg.anti_flood_pause_every))
                }
                if (cfg.anti_flood_pause_duration_min) setPauseDurationMin(String(cfg.anti_flood_pause_duration_min))
                if (cfg.anti_flood_pause_duration_max) setPauseDurationMax(String(cfg.anti_flood_pause_duration_max))
                if (cfg.anti_flood_pause_duration && !cfg.anti_flood_pause_duration_min && !cfg.anti_flood_pause_duration_max) {
                    setPauseDurationMin(String(cfg.anti_flood_pause_duration))
                    setPauseDurationMax(String(cfg.anti_flood_pause_duration))
                }
                if (cfg.hide_api_settings) setHideKeys(true)

                // Fallback: if no stored creds, try auto-login from config.json
                if (!stored?.api_id && !user && status === 'disconnected' && cfg.api_id && cfg.api_hash) {
                    autoLogin(cfg.api_id, cfg.api_hash)
                }
            } catch { }
        }

        init()
        return () => { cancelled = true }
    }, []) // single init, no deps to avoid re-runs

    useEffect(() => {
        if (status === 'awaiting_code') setCodeModal(true)
        if (status === 'awaiting_2fa') {
            setCodeModal(false)
            setTfaModal(true)
        }
        if (status === 'connected') {
            setCodeModal(false)
            setTfaModal(false)
        }
    }, [status])

    const handleConnect = async () => {
        if (!apiId || !apiHash || !phone) return
        setLoading(true)
        try {
            await connect(apiId, apiHash, phone, password)
        } catch { }
        setLoading(false)
    }

    const handleSave = async () => {
        // Persist credentials to electron-store
        await persistCredentials(apiId, apiHash, phone)

        // Save anti-flood config to backend config.json
        await saveConfig({
            api_id: apiId,
            api_hash: apiHash,
            phone,
            anti_flood_enabled: antiFloodEnabled,
            anti_flood_pause_every: pauseEveryMin,
            anti_flood_pause_every_min: pauseEveryMin,
            anti_flood_pause_every_max: pauseEveryMax,
            anti_flood_pause_duration: pauseDurationMin,
            anti_flood_pause_duration_min: pauseDurationMin,
            anti_flood_pause_duration_max: pauseDurationMax,
            hide_api_settings: hideKeys,
        })
    }

    const handleCodeSubmit = async () => {
        if (!verifyCode) return
        setLoading(true)
        try { await submitCode(phone, verifyCode, password) } catch { }
        setLoading(false)
        setVerifyCode('')
    }

    const handle2FASubmit = async () => {
        if (!tfaPassword) return
        setLoading(true)
        try { await submit2FA(tfaPassword) } catch { }
        setLoading(false)
        setTfaPassword('')
    }

    const inputType = hideKeys ? 'password' : 'text'
    const isConnected = status === 'connected'

    return (
        <div className="data-grid">
            <Card eyebrow="SESSAO" title="Credenciais Telegram" description="Vincule as credenciais de API do Telegram com sua sessao local.">
                <div className="form-grid">
                    <div className="toggle-item">
                        <div className="toggle-meta">
                            <strong>Ocultar Chaves</strong>
                            <p>Ofusca API ID e API Hash durante a configuracao.</p>
                        </div>
                        <input type="checkbox" checked={hideKeys} onChange={(e) => setHideKeys(e.target.checked)} />
                    </div>

                    <div className="data-grid data-grid-half">
                        <Field label="API ID" hint="TLG">
                            <input type={inputType} value={apiId} onChange={(e) => setApiId(e.target.value)} placeholder="0000000" className="field-input" />
                        </Field>

                        <Field label="API Hash" hint="HEX">
                            <input type={inputType} value={apiHash} onChange={(e) => setApiHash(e.target.value)} placeholder="000abc..." className="field-input" />
                        </Field>

                        <Field label="Telefone" hint="DDI+DDD">
                            <input type={inputType} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+5511999999999" className="field-input" />
                        </Field>

                        <Field label="Senha 2FA" hint="OPCIONAL">
                            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Senha (se ativada)" className="field-input" />
                        </Field>
                    </div>

                    <div className="form-actions" style={{ marginTop: '24px' }}>
                        <button onClick={handleConnect} disabled={loading || isConnected} className="btn btn-primary" type="button">
                            {isConnected ? 'SESSAO ATIVA' : loading ? 'VALIDANDO...' : 'INICIAR HANDSHAKE'}
                        </button>
                        <button onClick={handleSave} className="btn btn-ghost" type="button">
                            SALVAR CONFIGURACAO
                        </button>
                    </div>
                </div>
            </Card>

            <Card eyebrow="LIMITES" title="Protecao Local" description="Aplica parametros genericos de anti-flood nas conexoes via RPC.">
                <div className="form-grid">
                    <div className="toggle-item">
                        <div className="toggle-meta">
                            <strong>Limitar Frequencia</strong>
                            <p>Escolhe frequencia e tempo de pausa aleatorios dentro das faixas definidas para aplicar pausas durante processamentos em massa.</p>
                        </div>
                        <input type="checkbox" checked={antiFloodEnabled} onChange={(e) => setAntiFloodEnabled(e.target.checked)} />
                    </div>

                    {antiFloodEnabled && (
                        <div className="data-grid" style={{ marginTop: '16px', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
                            <Field label="Frequencia Minima" hint="MSGS">
                                <input type="number" min="1" value={pauseEveryMin} onChange={(e) => setPauseEveryMin(e.target.value)} className="field-input" />
                            </Field>
                            <Field label="Frequencia Maxima" hint="MSGS">
                                <input type="number" min="1" value={pauseEveryMax} onChange={(e) => setPauseEveryMax(e.target.value)} className="field-input" />
                            </Field>
                            <Field label="Pausa Minima (s)" hint="ESPERA">
                                <input type="number" min="0.1" step="0.1" value={pauseDurationMin} onChange={(e) => setPauseDurationMin(e.target.value)} className="field-input" />
                            </Field>
                            <Field label="Pausa Maxima (s)" hint="ESPERA">
                                <input type="number" min="0.1" step="0.1" value={pauseDurationMax} onChange={(e) => setPauseDurationMax(e.target.value)} className="field-input" />
                            </Field>
                        </div>
                    )}

                    <div className="form-actions">
                        <button onClick={handleSave} className="btn btn-ghost" type="button">
                            APLICAR PARAMETROS
                        </button>
                    </div>
                </div>
            </Card>

            <Modal open={codeModal} title="Codigo de Verificacao" onClose={() => setCodeModal(false)}>
                <p style={{ color: 'var(--color-ink-muted)', marginBottom: '16px', fontSize: '14px' }}>Insira o codigo enviado pelo Telegram.</p>
                <input
                    type="text"
                    value={verifyCode}
                    onChange={(e) => setVerifyCode(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCodeSubmit()}
                    placeholder="Ex: 00000"
                    autoFocus
                    className="field-input"
                />
                <button onClick={handleCodeSubmit} disabled={loading} className="btn btn-primary" type="button" style={{ marginTop: '16px', width: '100%' }}>
                    {loading ? 'VALIDANDO...' : 'CONFIRMAR'}
                </button>
            </Modal>

            <Modal open={tfaModal} title="Senha 2FA Exigida" onClose={() => setTfaModal(false)}>
                <p style={{ color: 'var(--color-ink-muted)', marginBottom: '16px', fontSize: '14px' }}>Sua conta possui verificacao em duas etapas ativa.</p>
                <input
                    type="password"
                    value={tfaPassword}
                    onChange={(e) => setTfaPassword(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handle2FASubmit()}
                    placeholder="Sua senha"
                    autoFocus
                    className="field-input"
                />
                <button onClick={handle2FASubmit} disabled={loading} className="btn btn-primary" type="button" style={{ marginTop: '16px', width: '100%' }}>
                    {loading ? 'VALIDANDO...' : 'CONFIRMAR'}
                </button>
            </Modal>
        </div>
    )
}

function Field({ label, hint, children }) {
    return (
        <div className="field-group">
            <label>
                {label}
                {hint && <span className="field-hint">{hint}</span>}
            </label>
            {children}
        </div>
    )
}
