import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ProgressBar from '../components/ProgressBar'
import { resolveAntiFloodConfig } from '../lib/antiFlood'

export default function ForumClone({ telegram }) {
    const { status, forumClone, stopClone, progress, loadConfig } = telegram

    const [source, setSource] = useState('')
    const [dest, setDest] = useState('')
    const [running, setRunning] = useState(false)

    const connected = status === 'connected'
    const forumProgress = progress?.type === 'forum' ? progress : null
    const isDone = forumProgress?.status === 'done'

    useEffect(() => {
        if (isDone) setRunning(false)
    }, [isDone])

    const handleStart = async () => {
        if (!source || !dest) return
        setRunning(true)
        try {
            const config = await loadConfig().catch(() => ({}))
            const antiFlood = resolveAntiFloodConfig(config)
            await forumClone({
                source,
                dest,
                limit: 0,
                delay: 0.1,
                ...antiFlood,
            })
        } catch {
            setRunning(false)
        }
    }

    const percent = forumProgress?.total_topics
        ? (((forumProgress.topic_index || 0) + 1) / forumProgress.total_topics) * 100
        : isDone
            ? 100
            : 0

    return (
        <div className="data-grid">
            <Card eyebrow="ESTRUTURA" title="Clonar Fórum" description="Replicar tópicos e mensagens integralmente.">
                <div className="form-grid">
                    <Field label="Fórum de Origem" hint="ID ou @grupo">
                        <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="@origem" className="field-input" disabled={running} />
                    </Field>

                    <Field label="Fórum de Destino" hint="ID ou @grupo">
                        <input value={dest} onChange={(e) => setDest(e.target.value)} placeholder="@destino" className="field-input" disabled={running} />
                    </Field>

                    <div className="form-actions">
                        <button onClick={handleStart} disabled={!connected || running || !source || !dest} className="btn btn-primary" type="button">
                            {running ? 'CLONANDO...' : 'INICIAR PROCESSO'}
                        </button>
                        {running && (
                            <button onClick={() => { stopClone(); setRunning(false); }} className="btn btn-danger" type="button">
                                INTERROMPER
                            </button>
                        )}
                    </div>
                </div>
            </Card>

            <Card eyebrow="TELEMETRIA" title="Monitoramento" description="Acompanhamento iterativo de tópicos.">
                {running || isDone || percent > 0 ? (
                    <>
                        <ProgressBar value={percent} />
                        <div className="kpi-row">
                            <div>
                                <span className="kpi-val">{forumProgress ? (forumProgress.topic_index || 0) + 1 : '-'}</span>
                                <span className="kpi-lbl">Tópico Atual</span>
                            </div>
                            <div>
                                <span className="kpi-val">{forumProgress?.total_topics ?? '-'}</span>
                                <span className="kpi-lbl">Total Previsto</span>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className={`status-banner ${connected ? 'ready' : ''}`}>
                        <strong>{connected ? 'Sistema Preparado' : 'Aguardando Conexão'}</strong>
                        <p>{connected ? 'Origem e destino devem ter tópicos habilitados na configuração do grupo.' : 'Requer sessão ativa no Telegram.'}</p>
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
