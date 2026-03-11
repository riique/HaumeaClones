export default function Card({ eyebrow, title, description, action, children }) {
    return (
        <section className="content-section">
            {(eyebrow || title || description || action) && (
                <header className="content-header" style={{ borderBottom: '1px solid var(--color-border)', marginBottom: '32px', paddingBottom: '24px' }}>
                    {eyebrow && <span className="mono-tag" style={{ display: 'block', marginBottom: '8px' }}>{eyebrow}</span>}
                    {title && <h3 className="editorial-title" style={{ fontSize: '24px', marginBottom: '8px' }}>{title}</h3>}
                    {description && <p style={{ fontSize: '13px', marginTop: 0 }}>{description}</p>}
                    {action && <div style={{ marginTop: '16px' }}>{action}</div>}
                </header>
            )}
            <div>{children}</div>
        </section>
    )
}
