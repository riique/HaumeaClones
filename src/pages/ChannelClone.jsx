import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ProgressBar from '../components/ProgressBar'
import { resolveAntiFloodConfig } from '../lib/antiFlood'

export default function ChannelClone({ telegram }) {
    const { status, clone, stopClone, progress, loadConfig } = telegram

    const [source, setSource] = useState('')
    const [dest, setDest] = useState('')
    const [limit, setLimit] = useState('0')
    const [delay, setDelay] = useState('0.1')
    const [running, setRunning] = useState(false)

    const connected = status === 'connected'

    useEffect(() => {
        loadConfig()
            .then((cfg) => {
                if (cfg.source) setSource(cfg.source)
                if (cfg.dest) setDest(cfg.dest)
                if (cfg.delay) setDelay(String(cfg.delay))
                if (cfg.limit) setLimit(String(cfg.limit))
            })
            .catch(() => { })
    }, [loadConfig])

    const cloneProgress = progress?.type === 'clone' ? progress : null
    const pct = cloneProgress?.percent || 0
    const isDone = cloneProgress?.status === 'done'

    useEffect(() => {
        if (isDone) setRunning(false)
    }, [isDone])

    const handleStart = async () => {
        if (!source || !dest) return
        setRunning(true)
        try {
            const config = await loadConfig().catch(() => ({}))
            const antiFlood = resolveAntiFloodConfig(config)
            await clone({
                source,
                dest,
                limit: parseInt(limit, 10) || 0,
                delay: parseFloat(delay) || 0.1,
                ...antiFlood,
            })
        } catch {
            setRunning(false)
        }
    }

    const handleStop = () => {
        stopClone()
        setRunning(false)
    }

    return (
        <div className="data-grid">
            <Card eyebrow="SETUP" title="Origem e Destino" description="Defina os parâmetros absolutos da clonagem.">
                <div className="form-grid">
                    <Field label="Canal de Origem" hint="URL ou ID">
                        <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="@origem ou t.me/grupo/25964" className="field-input" disabled={running} />
                    </Field>

                    <Field label="Canal de Destino" hint="URL ou ID">
                        <input value={dest} onChange={(e) => setDest(e.target.value)} placeholder="@destino ou t.me/grupo/25964" className="field-input" disabled={running} />
                    </Field>

                    <div className="data-grid data-grid-half">
                        <Field label="Limite" hint="0 = TODAS">
                            <input type="number" value={limit} onChange={(e) => setLimit(e.target.value)} className="field-input" disabled={running} />
                        </Field>
                        <Field label="Delay" hint="SEGUNDOS">
                            <input type="number" step="0.1" value={delay} onChange={(e) => setDelay(e.target.value)} className="field-input" disabled={running} />
                        </Field>
                    </div>

                    <div className="form-actions">
                        <button onClick={handleStart} disabled={!connected || running || !source || !dest} className="btn btn-primary" type="button">
                            {running ? 'EXECUTANDO...' : 'INICIAR PROCESSO'}
                        </button>
                        {running && (
                            <button onClick={handleStop} className="btn btn-danger" type="button">
                                INTERROMPER
                            </button>
                        )}
                    </div>
                </div>
            </Card>

            <Card eyebrow="TELEMETRIA" title="Monitoramento" description="Acompanhamento em tempo real da operação.">
                {running || isDone || pct > 0 ? (
                    <>
                        <ProgressBar value={pct} />
                        <div className="kpi-row">
                            <div>
                                <span className="kpi-val">{cloneProgress?.cloned ?? 0}</span>
                                <span className="kpi-lbl">Copiadas</span>
                            </div>
                            <div>
                                <span className="kpi-val">{cloneProgress?.total ?? '-'}</span>
                                <span className="kpi-lbl">Scope</span>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className={`status-banner ${connected ? 'ready' : ''}`}>
                        <strong>{connected ? 'Sistema Preparado' : 'Aguardando Conexão'}</strong>
                        <p>{connected ? 'Preencha os canais de origem e destino para iniciar o job de clonagem.' : 'Conecte-se à API para liberar o bloqueio de operações.'}</p>
                    </div>
                )}
            </Card>
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
