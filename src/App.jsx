import { useState } from 'react'
import NavigationSidebar from './components/NavigationSidebar'
import Sidebar from './components/Sidebar'
import WindowDragStrip from './components/WindowDragStrip'
import ApiConfig from './pages/ApiConfig'
import ChannelClone from './pages/ChannelClone'
import MultiGroup from './pages/MultiGroup'
import ForumClone from './pages/ForumClone'
import Restricted from './pages/Restricted'
import { useTelegram } from './hooks/useTelegram'

const TABS = [
    { id: 'config', label: 'Configuração', short: 'API', description: 'Credenciais e proteção da sessão.' },
    { id: 'clone', label: 'Clone Direto', short: 'CC', description: 'Fluxo principal de clonagem de canais.' },
    { id: 'multi', label: 'Multi-Grupo', short: 'MG', description: 'Automação e distribuição em lotes.' },
    { id: 'forum', label: 'Fórum', short: 'FM', description: 'Replicação estrita de tópicos.' },
    { id: 'restricted', label: 'Restrito', short: 'RS', description: 'Operações em ambientes controlados.' },
]

export default function App() {
    const [activeTab, setActiveTab] = useState('config')
    const telegram = useTelegram()

    const renderPage = () => {
        switch (activeTab) {
            case 'config': return <ApiConfig telegram={telegram} />
            case 'clone': return <ChannelClone telegram={telegram} />
            case 'multi': return <MultiGroup telegram={telegram} />
            case 'forum': return <ForumClone telegram={telegram} />
            case 'restricted': return <Restricted telegram={telegram} />
            default: return null
        }
    }

    const activeView = TABS.find((tab) => tab.id === activeTab) ?? TABS[0]

    return (
        <div className="app-layout">
            <aside className="layout-col layout-nav">
                <WindowDragStrip />
                <NavigationSidebar
                    activeTab={activeTab}
                    onSelect={setActiveTab}
                    status={telegram.status}
                    tabs={TABS}
                    user={telegram.user}
                />
            </aside>

            <main className="layout-col layout-main">
                <WindowDragStrip />
                <section className="main-content titlebar-nodrag">
                    <header className="content-header">
                        <span className="kicker">MÓDULO</span>
                        <h2 className="editorial-title">{activeView.label}</h2>
                        <p>{activeView.description}</p>
                    </header>
                    {renderPage()}
                </section>
            </main>

            <aside className="layout-col layout-log">
                <WindowDragStrip />
                <Sidebar logs={telegram.logs} onClear={telegram.clearLogs} />
            </aside>
        </div>
    )
}
