export default function ProgressBar({ value = 0, height = 4, className = '' }) {
    const safeValue = Math.max(0, Math.min(100, Number(value) || 0))
    return (
        <div className={`progress-wrap ${className}`}>
            <div className="progress-bar" style={{ height }}>
                <div className="progress-fill" style={{ width: `${safeValue}%` }} />
            </div>
            <div className="progress-meta">
                <span>PROGRESSO</span>
                <span>{Math.round(safeValue)}%</span>
            </div>
        </div>
    )
}
