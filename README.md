<p align="center">
  <img src=".github/assets/banner.png" alt="Haumea Clones" width="100%" />
</p>

<h3 align="center">
  Ferramenta profissional de clonagem de canais do Telegram
</h3>

<p align="center">
  <code>Electron</code> · <code>React</code> · <code>Python</code> · <code>Telethon</code>
</p>

<p align="center">
  <a href="#arquitetura">Arquitetura</a> ·
  <a href="#módulos">Módulos</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#build">Build</a> ·
  <a href="#contribuindo">Contribuindo</a>
</p>

---

## O que é

**Haumea Clones** é uma aplicação desktop que replica mensagens entre canais, grupos e fóruns do Telegram — incluindo mídia, formatação, stickers, enquetes e mensagens de voz.

Construída sobre uma arquitetura de duas camadas: um **frontend Electron/React** que renderiza a interface e um **backend Python** que opera a API do Telegram via [Telethon](https://github.com/LonamiWebs/Telethon). Comunicação entre as camadas acontece por **JSON-RPC 2.0** sobre stdin/stdout.

### Por que "Haumea"

> Haumea é um planeta-anão no cinturão de Kuiper, notável por sua forma alongada e pela capacidade de gerar fragmentos — seus "clones" orbitais. O nome reflete o propósito da ferramenta: replicar conteúdo com precisão cirúrgica.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                    ELECTRON SHELL                       │
│                                                         │
│   ┌──────────┐   IPC Bridge    ┌──────────────────┐     │
│   │  React   │◄──────────────►│  python-bridge   │     │
│   │  (Vite)  │                │     (.cjs)       │     │
│   └──────────┘                └────────┬─────────┘     │
│                                        │ stdin/stdout   │
│                                        ▼                │
│                               ┌──────────────────┐     │
│                               │  Python Server   │     │
│                               │  (JSON-RPC 2.0)  │     │
│                               └────────┬─────────┘     │
│                                        │                │
│                                        ▼                │
│                               ┌──────────────────┐     │
│                               │    Telethon      │     │
│                               │  (Telegram MTProto)│   │
│                               └──────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

| Camada | Tecnologia | Função |
|---|---|---|
| **Shell** | Electron 35 | Janela nativa, titlebar customizada, IPC |
| **Renderer** | React 19 + Vite 6 | UI reativa, estado de conexão, telemetria |
| **Bridge** | Node.js (CommonJS) | Spawn do processo Python, roteamento JSON-RPC |
| **Backend** | Python 3.9+ | Lógica de clonagem, gerenciamento de sessão, anti-flood |
| **Network** | Telethon + cryptg | MTProto, seleção automática IPv4/IPv6, aceleração crypto |

---

## Módulos

### `CC` — Clone Direto
Fluxo principal. Replica todas as mensagens de um canal origem para um destino, respeitando ordem cronológica, formatação original e mídia anexada.

### `MG` — Multi-Grupo
Distribuição em lotes. Clona o conteúdo de origem para múltiplos destinos simultâneos, criando tópicos de fórum automaticamente quando necessário.

### `FM` — Fórum
Replicação estrita de tópicos. Lê a estrutura de fórum do canal origem e recria cada tópico no destino preservando a hierarquia.

### `RS` — Restrito
Bypass de canais com proteção de forwarding. Faz download local da mídia e re-upload para o destino, com barra de progresso granular por arquivo e opção de skip.

---

## Quick Start

### Pré-requisitos

| Requisito | Versão |
|---|---|
| Node.js | 18+ |
| Python | 3.9+ |
| pip | latest |

### 1. Clone o repositório

```bash
git clone https://github.com/riique/Haumea-Clones-Via-Electron-.git
cd Haumea-Clones-Via-Electron-
```

### 2. Instale as dependências

```bash
# Frontend
npm install

# Backend
pip install -r requirements.txt
```

### 3. Configure suas credenciais

Crie o arquivo `config.json` a partir do exemplo:

```bash
cp config.example.json config.json
```

Preencha com suas credenciais da [Telegram API](https://my.telegram.org/apps):

```json
{
    "api_id": "SEU_API_ID",
    "api_hash": "SEU_API_HASH",
    "phone": "+SEU_NUMERO"
}
```

### 4. Execute em modo de desenvolvimento

```bash
npm run dev
```

> A janela Electron abre automaticamente após o Vite compilar o renderer.

---

## Build

### Gerar executável Windows (.exe)

```bash
# Compilar o backend Python em binário standalone
npm run build:python

# Build completo (renderer + electron-builder)
npm run build
```

O instalador será gerado em `release/`.

---

## Estrutura do Projeto

```
.
├── backend/
│   └── server.py              # JSON-RPC server (Telethon)
├── electron/
│   ├── main.cjs               # Electron main process
│   ├── preload.cjs            # Context bridge
│   └── python-bridge.cjs      # Spawn + comunicação com Python
├── src/
│   ├── components/            # UI components (Card, Modal, Sidebar...)
│   ├── hooks/                 # useTelegram — estado global
│   ├── lib/                   # Utilidades (anti-flood config)
│   ├── pages/                 # Módulos (Clone, Multi, Forum, Restricted)
│   ├── App.jsx                # Root layout
│   ├── index.css              # Design system
│   └── main.jsx               # Entry point
├── config.example.json        # Template de credenciais
├── haumea_rpc.py              # Helpers RPC compartilhados
├── requirements.txt           # Dependências Python
├── vite.config.js             # Configuração Vite
└── package.json               # Scripts e dependências Node
```

---

## Segurança

- **Sessão Telethon** (`.session`) nunca é commitada — está no `.gitignore`
- **Credenciais** (`config.json`) são excluídas do versionamento
- **Context Isolation** ativo no Electron — `nodeIntegration: false`
- **Preload script** expõe apenas os métodos necessários via `contextBridge`
- Credenciais salvas localmente via `electron-store` com escopo isolado

---

## Stack Detalhada

<table>
  <tr>
    <td><b>Frontend</b></td>
    <td>React 19 · Vite 6 · Tailwind CSS 4 · Vanilla CSS</td>
  </tr>
  <tr>
    <td><b>Desktop</b></td>
    <td>Electron 35 · electron-builder · electron-store</td>
  </tr>
  <tr>
    <td><b>Backend</b></td>
    <td>Python 3.9+ · Telethon · cryptg · PySocks</td>
  </tr>
  <tr>
    <td><b>Protocolo</b></td>
    <td>JSON-RPC 2.0 via stdin/stdout</td>
  </tr>
  <tr>
    <td><b>Build</b></td>
    <td>PyInstaller (backend) · electron-builder (desktop)</td>
  </tr>
</table>

---

## Contribuindo

1. Fork o repositório
2. Crie uma branch para sua feature (`git checkout -b feat/nova-feature`)
3. Commit suas mudanças (`git commit -m 'feat: descrição'`)
4. Push para a branch (`git push origin feat/nova-feature`)
5. Abra um Pull Request

---

## Licença

Distribuído sob a licença **MIT**. Veja [`LICENSE`](LICENSE) para mais detalhes.

---

<p align="center">
  <sub>Construído com precisão orbital por <a href="https://github.com/riique">@riique</a></sub>
</p>
