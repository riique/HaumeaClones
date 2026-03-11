import { useEffect, useRef } from 'react'

export default function Modal({ open, onClose, title, children }) {
    const backdropRef = useRef(null)

    useEffect(() => {
        const handleEsc = (event) => {
            if (event.key === 'Escape') onClose?.()
        }
        if (open) {
            document.addEventListener('keydown', handleEsc)
        }
        return () => document.removeEventListener('keydown', handleEsc)
    }, [open, onClose])

    if (!open) return null

    return (
        <div
            ref={backdropRef}
            onClick={(event) => {
                if (event.target === backdropRef.current) onClose?.()
            }}
            style={{
                position: 'fixed',
                inset: 0,
                background: 'rgba(250, 250, 250, 0.9)',
                backdropFilter: 'blur(4px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                zIndex: 100,
                padding: '24px'
            }}
        >
            <div style={{
                background: 'var(--color-canvas)',
                border: '1px solid var(--color-ink)',
                width: '100%',
                maxWidth: '420px',
                padding: '32px'
            }}>
                {title && (
                    <h2 className="editorial-title" style={{ fontSize: '24px', marginBottom: '24px' }}>
                        {title}
                    </h2>
                )}
                <div>{children}</div>
            </div>
        </div>
    )
}
