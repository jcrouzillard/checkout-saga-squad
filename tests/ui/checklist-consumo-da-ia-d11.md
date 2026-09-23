# Checklist QA — D11 Consumo da IA (`642a73cb38e5`)

Contrato: `docs/contracts/ui-consumo-da-ia.md` (CA1–CA11). Pareceres: `docs/squad/gates/G1-D11.json`, `G2-D11.json`.
Branch `feature/D11-consumo-da-ia` (worktree `plankton-d11`), 2026-09-23.

**Ambiente.** Dois servidores do worktree, derrubados no fim (7070 intacto):
- **7098 real**: `SQUAD_ROOT_DATA=plankton`, Codex real (`~/.codex/sessions`, só leitura), Claude sem statusline.
- **7099 fixture**: `SQUAD_ROOT_DATA` e `CODEX_HOME` = cópias mínimas no scratchpad; o script escreve o snapshot
  `.squad/usage/claude.json` e um rollout do Codex **só nesse diretório temporário**. Nada foi criado em `.squad/usage` do plankton, e `~/.claude`/`~/.codex` não foram alterados.
- Navegador: Puppeteer `ghcr.io/puppeteer/puppeteer:latest` (Docker → `host.docker.internal`), script
  `tests/ui/d11-screenshots.js` (o comando está no cabeçalho). Tee testado com `--data-root` no scratchpad e `--next` sintético
  (nenhum `--install`/`--uninstall`).

## Resultado por critério

| CA | Status | Evidência |
|---|---|---|
| CA1 | **pass** | `/api/usage` e `/api/state.usage` idênticos (comparação em Python), `providers` = `[claude, codex]`, formato do §3, valores separados (nada somado). |
| CA2 | **pass** | Último `token_count` real (5 rollouts mais recentes): ts `2026-09-23T21:24:49Z`, primary 9,0 % / 300 min / `1790199311` (=21:35:11Z), secondary 22,0 % / 10080 / `1790549991` (=27/09 22:59:51Z), plan plus → a API mostra exatamente isso. |
| CA3 | **validar após --install** | Depende de uma sessão interativa com o tee instalado pelo humano (a partir do checkout `plankton`, não do worktree: ver risco no G2). O caminho snapshot→API→UI foi provado com snapshot de fixture (estados fresh/atenção/crítico/stale). |
| CA4 | **pass** | stdin com `session_id`/`transcript_path`/`cwd` + `rate_limits`: saída com `--next` idêntica à do comando original (`cmp`, inclui aspas simples), rc 0/0; `--next 'exit 7'` → rc 7. JSON sem `rate_limits` e JSON inválido: rc 0, stderr vazio, snapshot inalterado (`cmp`). |
| CA5 | **pass** | Snapshot contém só `collectedAt`, `fiveHour`, `sevenDay` (`usedPercent`, `resetsAt`); `grep session\|/Users\|transcript\|@\|token` vazio no snapshot e na resposta da API. |
| CA6 | **pass** | Real: Claude `none` "Statusline não instalada", números `null`; UI "Indisponível — sem fonte real" + motivo, sem números nem barras (`d11-real-execucoes-*.png`, `d11-claude-none-*.png`). Codex com rollout vazio → `none` "Nenhum rate_limits nas sessões recentes do Codex". |
| CA7 | **pass** | Real: Codex `stale` "Janela de 5 h renovada às 18:35" — números 9 %/22 % esmaecidos + ícone + "Indisponível · coletado às 21:24" + `title` com o motivo. Fixture com coleta de 30 min atrás → `stale` "Coleta com mais de 15 min" (`d11-claude-stale-*.png`). |
| CA8 | **pass** (faixa) / **fail** (altura) | Sticky: nas 6 telas, a 1440 e a 390 px, depois de rolar até o fim (até 50 000 px), a faixa fica em `top = 0` e visível; em Observabilidade fica oculta (`hidden`) e reaparece ao voltar. **Altura ≤ 72 px não é cumprida:** 1440 px = 74 px (fresh com níveis), **110 px** (qualquer estado stale/none com motivo); 601–900 px = 106–187 px (ver defeito D11-QA-1). |
| CA9 | **pass** | Demandas, `#dem-title` e `#dem-detail` preenchidos, foco em `#dem-detail`; snapshot mudado 30→88 e depois 96: após 7 s (≥ 2 ciclos) a barra passou a 88, e após mais um ciclo a 96; o foco continuou em `#dem-detail` e o texto digitado (inclusive o digitado entre os ciclos) permaneceu, a 1440 e a 390 px (`d11-foco-demanda-*.png`). |
| CA10 | **pass com ressalva** | 390 px: blocos empilhados (tops 469/529), `scrollWidth = clientWidth = 390` em Execuções, Decisões, Políticas, Agentes e Demandas; 4 `role="meter"` com `aria-valuenow/min=0/max=100/label/valuetext`; nível em texto ("ATENÇÃO"/"CRÍTICO" e no `aria-valuetext`), sem `aria-live`. Evidências a 390 px tem rolagem horizontal (609 px) **pré-existente** (develop dá 625 px; é a tabela de evidências, não a faixa). Cabeçalho: sino e 3 abas com 44 px, dentro da tela e clicáveis; a aba Demandas funciona. **Painel de notificações sai 89 px pela esquerda** (defeito D11-QA-2). |
| CA11 | **pass** | Snapshot corrompido (`{isto não é json`): `/api/state` 200, Claude `none` "Snapshot ilegível", Codex `fresh` com os valores do rollout — UI mostra os dois blocos normalmente. |

Níveis (fixture): 42,5 %/61 % neutro; 83 % "ATENÇÃO"; 85 % "ATENÇÃO"; 96 %, 97 %, 99,5 % "CRÍTICO" — cor + texto + `aria-valuetext`.
Console: nenhum `pageerror`; os dois únicos erros são `404 /favicon.ico` (pré-existente, também em develop).

## Defeitos
- **D11-QA-1 (Frontend, médio)** — altura da faixa > 72 px: 110 px a 1440 px quando um bloco está `stale`/`none` (a coluna fixa de 104 px
  do nome quebra "Indisponível · coletado às 22:06" + motivo em 5 linhas); 74 px no estado fresh com níveis; 601–900 px: 106–187 px
  (colunas de meia largura quebram "renova em 2h51 (01:28)"). Como a faixa é sticky, ocupa até 20 % da altura útil. Repro: `tests/ui/d11-screenshots.js`, seção 3; `d11-claude-stale-1440.png`, `d11-largura-700.png`.
- **D11-QA-2 (Frontend, médio)** — a 390 px o `#notif-panel` abre com `left = −89 px` (`right: 0` do contêiner que termina em 269 px com
  largura 358 px): título e início das notificações ficam cortados. Repro: 390×844, clicar no sino; `d11-real-sino-390.png`.
- **D11-QA-3 (Frontend, baixo)** — falta espaço entre a hora e o plano no bloco do Codex a ≥ 600 px: "coletado às 22:36plano plus" (`d11-claude-fresh-1440.png`).

## Observações (não bloqueantes)
- A 390 px a faixa sticky mede 149–190 px (≈ 20 % de 844 px); o contrato só limita a altura no desktop, mas vale considerar compactá-la.
- Evidências a 390 px com rolagem horizontal é anterior à D11.

## Capturas (`tests/ui/`)
`d11-real-{execucoes,execucoes-scroll,demandas-scroll,observabilidade}-{1440,390}.png`, `d11-real-sino-390.png`,
`d11-claude-{fresh,atencao,critico,stale,none,corrompido}-{1440,390}.png`, `d11-largura-{600,700,900}.png`, `d11-foco-demanda-{1440,390}.png`.
