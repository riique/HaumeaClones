# Haumea Clones

Clone canais, grupos e fóruns do Telegram em uma interface desktop, retome operações interrompidas e acompanhe cada etapa sem depender do terminal.

O Haumea Clones combina Electron e React no aplicativo com um backend Python baseado em Telethon. O resultado é um fluxo visual para analisar a origem, controlar o ritmo, acompanhar progresso e manter checkpoints entre execuções.

> Use apenas em conversas às quais sua conta tenha acesso legítimo e somente quando você tiver autorização para copiar o conteúdo. Respeite direitos autorais, privacidade, permissões dos grupos e os Termos de Serviço do Telegram.

## O que o aplicativo oferece

- **Clone de canal ou grupo:** copie mensagens da origem para o destino com limite e intervalo configuráveis.
- **Análise prévia:** verifique o volume e a rota antes de iniciar.
- **Retomada por checkpoint:** continue uma execução interrompida a partir do progresso salvo.
- **Sincronização contínua:** monitore novas mensagens após o início da sync.
- **Múltiplas origens:** envie grupos diferentes para tópicos criados em um fórum de destino.
- **Clone de fórum:** recrie tópicos e copie suas mensagens.
- **Controle anti-flood:** configure frequência e duração de pausas, inclusive com intervalos aleatórios.
- **Deduplicação persistente:** evite reenviar itens já registrados pelo aplicativo.
- **Centro de operações:** acompanhe job atual, histórico, erros, mídia processada e throughput.
- **Atualizações no próprio app:** verifique, baixe e aplique versões publicadas no GitHub Releases.

## Tratamento de mensagens e mídia

O backend tenta copiar mensagens pelos recursos disponíveis no Telegram. Quando um envio direto não é possível, o código possui rotas alternativas de cópia e, para mídia compatível, processamento temporário em memória.

Isso não garante que todo conteúdo seja replicado. Restrições da plataforma, mensagens autodestrutivas, permissões insuficientes, referências de arquivo expiradas e tipos não suportados podem impedir ou alterar o resultado.

## Arquitetura

```text
Interface React
    ↓ IPC exposta pelo preload
Electron (processo principal)
    ↓ JSON-RPC 2.0 por stdin/stdout
Backend Python
    ↓ Telethon / MTProto
Telegram
```

- `contextIsolation` fica ativo;
- `nodeIntegration` fica desativado no renderer;
- o preload limita a ponte entre interface e processo principal;
- no aplicativo empacotado, o backend Python é distribuído como executável;
- no desenvolvimento, o Electron inicia `python backend/server.py`.

## Persistência local

O app mantém no computador:

- credenciais da API e sessão usadas para autenticar no Telegram;
- checkpoints em `progress/`;
- histórico e erros em `history/`;
- configuração, deduplicação e outros estados em `state/`.

Proteja a conta do Windows e não compartilhe a pasta de dados do aplicativo. O repositório não oferece garantia de cofre de credenciais nem sincronização segura desses arquivos.

## Tecnologias

- Electron 35
- React 19
- Vite 6 e Tailwind CSS 4
- Python 3.9+
- Telethon e MTProto
- JSON-RPC 2.0
- PyInstaller
- electron-builder e NSIS
- electron-updater com GitHub Releases

## Pré-requisitos

- Node.js 18 ou superior;
- npm;
- Python 3.9 ou superior disponível como `python`;
- credenciais `api_id` e `api_hash` obtidas em [my.telegram.org](https://my.telegram.org);
- Windows para gerar o instalador NSIS;
- PyInstaller instalado para compilar o backend.

## Instalação para desenvolvimento

```bash
git clone https://github.com/riique/HaumeaClones.git
cd HaumeaClones
npm install
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

Inicie o renderer, o Electron e o backend:

```bash
npm run dev
```

Na aba **Configuração**, informe suas credenciais do Telegram e conclua o login solicitado pela plataforma.

## Fluxo recomendado

1. Conecte sua conta na tela **Configuração**.
2. Informe origem e destino.
3. Execute a **Análise prévia**.
4. Defina limite, delay e pausas compatíveis com sua conta.
5. Faça um teste pequeno antes de copiar todo o histórico.
6. Acompanhe progresso e erros em **Monitoramento**.
7. Se necessário, retome pelo checkpoint salvo.

## Build

Somente o renderer:

```bash
npm run build:renderer
```

Backend Python:

```bash
npm run build:python
```

Pacote completo para Windows:

```bash
npm run build
```

Publicação pelo electron-builder:

```bash
npm run build:publish
```

Para a versão atual do `package.json`, as saídas esperadas incluem:

```text
dist-python/haumea-backend.exe
release/Haumea Clones Setup 1.0.4.exe
release/win-unpacked/Haumea Clones.exe
```

O nome exato pode mudar quando a versão do pacote for atualizada.

## Atualizações

O `package.json` aponta o provedor de atualização para `riique/HaumeaClones`. A verificação usa GitHub Releases e funciona no aplicativo empacotado. Um release precisa conter os metadados e artefatos esperados pelo `electron-updater`.

## Estrutura

```text
backend/server.py        servidor JSON-RPC e operações Telethon
electron/main.cjs        janela, IPC, armazenamento e atualizador
electron/preload.cjs     API exposta ao renderer
electron/python-bridge.cjs
                         ciclo de vida e comunicação com o backend
src/components/          interface compartilhada
src/hooks/               integração Telegram e atualização
src/pages/               configuração, clones e monitoramento
haumea_rpc.py            classificação de erros do Telegram
```

## Limitações

- FloodWait e outros limites continuam sendo definidos pelo Telegram.
- Delays e pausas reduzem risco operacional, mas não impedem bloqueios.
- A conta precisa conseguir ler a origem e publicar no destino.
- Tópicos exigem um supergrupo com fórum habilitado e permissões adequadas.
- Mudanças no MTProto ou no Telethon podem exigir manutenção.
- O projeto não contém suíte automatizada de testes no estado atual.
- Faça backup dos estados locais antes de atualizar ou alterar a implementação.

## Contribuição

Abra uma issue com a rota usada, tipo de conversa, etapa que falhou e logs sem dados sensíveis. Em pull requests:

- não inclua arquivos de sessão, números de telefone ou credenciais;
- mantenha a ponte do preload restrita;
- valide `npm run build:renderer`;
- teste uma cópia pequena em chats de sua propriedade.

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE).
