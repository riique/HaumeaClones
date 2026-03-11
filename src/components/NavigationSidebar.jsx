export default function NavigationSidebar({ activeTab, onSelect, status, tabs, user }) {
    const connected = status === 'connected'
    const pending = ['connecting', 'awaiting_code', 'awaiting_2fa'].includes(status)
    const indClass = connected ? 'on' : pending ? 'wait' : 'off'

    return (
        <div className="nav-shell">
            <div className="brand titlebar-nodrag">
                <h1 className="brand-name">Haumea</h1>
            </div>

            <div className="nav-scroll titlebar-nodrag">
                <nav className="nav-menu">
                    {tabs.map((tab) => {
                        const active = tab.id === activeTab
                        return (
                            <button
                                key={tab.id}
                                className={`nav-link ${active ? 'active' : ''}`}
                                onClick={() => onSelect(tab.id)}
                                type="button"
                            >
                                <span className="nav-icon">{tab.short}</span>
                                <span>{tab.label}</span>
                            </button>
                        )
                    })}
                </nav>
            </div>

            <footer className="nav-footer titlebar-nodrag">
                <div className="status-pill">
                    <span className={`indicator ${indClass}`} />
                    <span>{connected ? 'Sessão Ativa' : pending ? 'Conectando...' : 'Desconectado'}</span>
                </div>

                <div className="user-meta">
                    <strong>{user?.name ?? 'Sessão ausente'}</strong>
                    <span>{user?.username ? `@${user.username}` : 'Conecte-se à API'}</span>
                </div>
            </footer>
        </div>
    )
}
