import { useEffect, useRef } from 'react'

export default function Sidebar({ logs, onClear }) {
    const scrollRef = useRef(null)
    const stickToBottomRef = useRef(true)

    const handleScroll = () => {
        const node = scrollRef.current
        if (!node) return

        const distanceToBottom = node.scrollHeight - node.scrollTop - node.clientHeight
        stickToBottomRef.current = distanceToBottom <= 24
    }

    useEffect(() => {
        const node = scrollRef.current
        if (!node || !stickToBottomRef.current) return

        node.scrollTop = node.scrollHeight
    }, [logs])

    return (
        <>
            <header className="log-header titlebar-nodrag">
                <span>Atividade</span>
                <button className="btn btn-ghost" onClick={onClear} type="button">LIMPAR</button>
            </header>

            <div ref={scrollRef} className="log-list titlebar-nodrag" onScroll={handleScroll}>
                {logs.length === 0 ? (
                    <p className="log-empty">Sistema preparado.</p>
                ) : (
                    logs.map((entry, index) => (
                        <article key={`${entry.time}-${index}`} className="log-entry">
                            <div className="log-meta">
                                <span className="log-tag">{entry.tag ?? 'INFO'}</span>
                                <span className="log-time">{entry.time}</span>
                            </div>
                            <p className="log-msg">{entry.message}</p>
                        </article>
                    ))
                )}
            </div>
        </>
    )
}
