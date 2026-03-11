import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ProgressBar from '../components/ProgressBar'
import { resolveAntiFloodConfig } from '../lib/antiFlood'

export default function Restricted({ telegram }) {
    const { status, restrictedClone, stopClone, skipDownload, progress, loadConfig } = telegram

    const [source, setSource] = useState('')
    const [dest, setDest] = useState('')
    const [limit, setLimit] = useState('0')
    const [useTopic, setUseTopic] = useState(false)
    const [topicId, setTopicId] = useState('')
    const [running, setRunning] = useState(false)

    const connected = status === 'connected'

    const restrictedProgress = progress?.type === 'restricted' ? progress : null
    const downloadProgress = progress?.type === 'download' ? progress : null
    const uploadProgress = progress?.type === 'upload' ? progress : null
    const transferProgress = downloadProgress || uploadProgress
    const isDone = restrictedProgress?.status === 'done'
    const pct = restrictedProgress?.percent || 0

    useEffect(() => {
        if (isDone) setRunning(false)
    }, [isDone])

    const handleStart = async () => {
        if (!source || !dest) return
        setRunning(true)
        try {
            const config = await loadConfig().catch(() => ({}))
            const antiFlood = resolveAntiFloodConfig(config)
            await restrictedClone({
                source,
                dest,
                limit: parseInt(limit, 10) || 0,
                delay: 0.1,
                ...antiFlood,
                topic_id: useTopic && topicId ? parseInt(topicId, 10) : null,
            })
        } catch {
            setRunning(false)
        }
    }

    return (
        <div className="data-grid">
            <Card eyebrow="MÓDULO ISOLADO" title="Clonagem Protegida" description="Bypass de restrições via cache local com manipulação explícita de mídia.">
                <div className="form-grid">
                    <Field label="Canal de Origem" hint="COM PROTEÇÃO">
                        <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="@origem ou t.me/grupo/25964" className="field-input" disabled={running} />
                    </Field>

                    <Field label="Canal de Destino">
                        <input value={dest} onChange={(e) => setDest(e.target.value)} placeholder="@destino ou t.me/grupo/25964" className="field-input" disabled={running} />
                    </Field>

                    <div className="data-grid data-grid-half">
                        <Field label="Limite" hint="0 = TODAS">
                            <input type="number" value={limit} onChange={(e) => setLimit(e.target.value)} className="field-input" disabled={running} />
                        </Field>

                        <div className="field-group">
                            <label>Roteamento Específico</label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', padding: '12px 14px', border: '1px solid var(--color-border)', background: 'var(--color-panel)' }}>
                                <input type="checkbox" checked={useTopic} onChange={(e) => setUseTopic(e.target.value)} disabled={running} />
                                <span style={{ fontFamily: 'var(--font-primary-mono)', fontSize: '11px', fontWeight: 500 }}>DIRECIONAR A TÓPICO</span>
                            </label>
                        </div>
                    </div>

                    {useTopic && (
                        <Field label="ID do Tópico" hint="NUMÉRICO">
                            <input type="number" value={topicId} onChange={(e) => setTopicId(e.target.value)} placeholder="Ex: 5" className="field-input" disabled={running} />
                        </Field>
                    )}

                    <div className="form-actions">
                        <button onClick={handleStart} disabled={!connected || running || !source || !dest} className="btn btn-primary" type="button">
                            {running ? 'PROCESSANDO...' : 'INICIAR FLUXO RESTRITO'}
                        </button>

                        {running && (
                            <button onClick={() => { stopClone(); setRunning(false); }} className="btn btn-danger" type="button">
                                INTERROMPER
                            </button>
                        )}
                    </div>
                </div>
            </Card>

            <div className="data-grid data-grid-half">
                <Card eyebrow="TRANSFERÊNCIA" title="Metadados I/O">
                    {transferProgress ? (
                        <div className="form-grid">
                            <div>
                                <span className="mono-tag" style={{ display: 'block', marginBottom: '8px' }}>
                                    {downloadProgress ? 'DOWNLOAD CACHE' : 'UPLOAD SERVER'}
                                </span>
                                <span style={{ fontFamily: 'var(--font-primary-mono)', fontSize: '12px', wordBreak: 'break-all' }}>{transferProgress.filename}</span>
                            </div>
                            <ProgressBar value={transferProgress.percent || 0} />
                            <div className="kpi-row" style={{ marginTop: 0, paddingTop: '16px' }}>
                                <div>
                                    <span className="kpi-val" style={{ fontSize: '16px' }}>{transferProgress.percent || 0}%</span>
                                    <span className="kpi-lbl">Concluído</span>
                                </div>
                                {downloadProgress && running && (
                                    <button onClick={skipDownload} className="btn btn-ghost" type="button" style={{ height: 'fit-content' }}>
                                        IGNORAR ARQUIVO
                                    </button>
                                )}
                            </div>
                        </div>
                    ) : (
                        <p style={{ color: 'var(--color-ink-muted)', fontSize: '13px' }}>Aguardando submissão de arquivos.</p>
                    )}
                </Card>

                <Card eyebrow="ESTADO GLOBAL" title="Operações">
                    <ProgressBar value={pct} />
                    <div className="kpi-row" style={{ marginTop: '16px', paddingTop: '16px' }}>
                        <div>
                            <span className="kpi-val">{restrictedProgress?.cloned ?? 0}</span>
                            <span className="kpi-lbl">Processadas</span>
                        </div>
                        <div>
                            <span className="kpi-val">{restrictedProgress?.downloaded ?? 0}</span>
                            <span className="kpi-lbl">Mídias</span>
                        </div>
                        <div>
                            <span className="kpi-val" style={{ color: 'var(--color-error)' }}>{restrictedProgress?.errors ?? 0}</span>
                            <span className="kpi-lbl">Falhas</span>
                        </div>
                    </div>
                </Card>
            </div>
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
