import { useEffect, useMemo, useState } from 'react'
import Card from '../components/Card'
import ProgressBar from '../components/ProgressBar'
import { resolveAntiFloodConfig } from '../lib/antiFlood'

export default function MultiGroup({ telegram }) {
    const { status, multiClone, stopClone, progress, loadConfig } = telegram

    const [sources, setSources] = useState('')
    const [dest, setDest] = useState('')
    const [running, setRunning] = useState(false)

    const connected = status === 'connected'
    const multiProgress = progress?.type === 'multi' ? progress : null
    const isDone = multiProgress?.status === 'done'
    const sourceCount = useMemo(
        () => sources.split('\n').map((value) => value.trim()).filter(Boolean).length,
        [sources],
    )

    useEffect(() => {
        if (isDone) setRunning(false)
    }, [isDone])

    const handleStart = async () => {
        const list = sources.split('\n').map((value) => value.trim()).filter(Boolean)
        if (!list.length || !dest) return
        setRunning(true)
        try {
            const config = await loadConfig().catch(() => ({}))
            const antiFlood = resolveAntiFloodConfig(config)
            await multiClone({
                sources: list,
                dest,
                limit: 0,
                delay: 0.1,
                ...antiFlood,
            })
        } catch {
            setRunning(false)
        }
    }

    const percent = multiProgress?.total_groups
        ? (((multiProgress.group_index || 0) + 1) / multiProgress.total_groups) * 100
        : isDone
            ? 100
            : 0

    return (
        <div className="data-grid">
            <Card eyebrow="LOTES" title="Clone Multi-Grupo" description="Consolide múltiplos grupos em um fórum de destino.">
                <div className="form-grid">
                    <Field label="Grupos de Origem" hint="UM POR LINHA">
                        <textarea
                            value={sources}
                            onChange={(e) => setSources(e.target.value)}
                            placeholder="@grupo1&#10;@grupo2&#10;@grupo3"
                            rows={7}
                            className="field-input"
                            style={{ resize: 'vertical' }}
                            disabled={running}
                        />
                    </Field>

                    <Field label="Grupo de Destino" hint="FÓRUM ATIVADO">
                        <input value={dest} onChange={(e) => setDest(e.target.value)} placeholder="@destino" className="field-input" disabled={running} />
                    </Field>

                    <div className="form-actions">
                        <button onClick={handleStart} disabled={!connected || running || !sourceCount || !dest} className="btn btn-primary" type="button">
                            {running ? 'PROCESSANDO...' : 'INICIAR MULTI-CLONE'}
                        </button>

                        {running && (
                            <button onClick={() => { stopClone(); setRunning(false); }} className="btn btn-danger" type="button">
                                INTERROMPER
                            </button>
                        )}
                    </div>
                </div>
            </Card>

            <Card eyebrow="TELEMETRIA" title="Monitoramento" description="Acompanhamento linear do processamento em lotes.">
                {running || isDone || percent > 0 ? (
                    <>
                        <ProgressBar value={percent} />
                        <div className="kpi-row">
                            <div>
                                <span className="kpi-val">{multiProgress ? (multiProgress.group_index || 0) + 1 : '-'}</span>
                                <span className="kpi-lbl">Lote Atual</span>
                            </div>
                            <div>
                                <span className="kpi-val">{multiProgress?.total_groups ?? (sourceCount || '-')}</span>
                                <span className="kpi-lbl">Total Lotes</span>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className={`status-banner ${connected ? 'ready' : ''}`}>
                        <strong>{connected ? 'Sistema Preparado' : 'Aguardando Conexão'}</strong>
                        <p>{connected ? `Fontes informadas: ${sourceCount}` : 'Requer sessão ativa no Telegram.'}</p>
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
