# Checklist QA — D11 Consumo da IA (`642a73cb38e5`)

Contrato: `docs/contracts/ui-consumo-da-ia.md` (CA1–CA11). Pareceres: `docs/squad/gates/G1-D11.json`, `G2-D11.json`.
Branch `feature/D11-consumo-da-ia` (worktree `plankton-d11`), 2026-09-23.

**Ambiente.** Dois servidores do worktree, derrubados no fim (7070 intacto):
- **7098 real**: `SQUAD_ROOT_DATA=plankton`, Codex real (`~/.codex/sessions`, só leitura), Claude sem statusline.
- **7099 fixture**: `SQUAD_ROOT_DATA` e `CODEX_HOME` = cópias mínimas no scratchpad; o script escreve o snapshot
  `.squad/usage/claude.json` e um rollout do Codex **só nesse diretório temporário**. Nada foi criado em `.squad/usage` do plankton, e `~/.claude`/`~/.codex` não foram alterados.
- Navegador: Puppeteer `ghcr.io/puppeteer/puppeteer:latest` (Docker → `host.docker.internal`), script
  `tests/ui/d11-screenshots.js` (o comando está no cabeçalho; `NODE_PATH` necessário). Tee testado com `--data-root` no scratchpad e `--next` sintético
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
| CA8 | **pass** (revalidado após `0f5b205`) | Altura de `#ai-usage` medida por estado × largura (seção 3 do script): **1440/900/700/601/600 px → 68 px** (fresh, atenção, crítico, none, texto mais longo) e **69 px** (stale, stale+none); lado a lado, sem rolagem horizontal. 390 px (só medido): 112–131 px, empilhado. Dados reais: 69 px a 1440. Sticky: a 1440 em Decisões/Evidências/Agentes/Demandas e a 390 nas 6 telas, depois de rolar até o fim (1 604–50 127 px), `top = 0` e visível; Execuções e Políticas a 1440 rolam só 59/80 px (menos que a posição da faixa, 89 px), então não há rolagem suficiente para testar lá. Observabilidade: oculta; volta ao sair. |
| CA9 | **pass** | Demandas, `#dem-title` e `#dem-detail` preenchidos, foco em `#dem-detail`; snapshot mudado 30→88 e depois 96: após 7 s (≥ 2 ciclos) a barra passou a 88, e após mais um ciclo a 96; o foco continuou em `#dem-detail` e o texto digitado (inclusive o digitado entre os ciclos) permaneceu, a 1440 e a 390 px (`d11-foco-demanda-*.png`). |
| CA10 | **pass com ressalva** | 390 px: blocos empilhados, `scrollWidth = clientWidth = 390` em Execuções, Decisões, Políticas, Agentes e Demandas; 4 `role="meter"` com `aria-valuenow/min=0/max=100/label/valuetext`; nível em texto ("ATENÇÃO"/"CRÍTICO") e no `aria-valuetext`, sem `aria-live`. Evidências a 390 px tem rolagem horizontal (609 px) **pré-existente** (tabela de evidências). Cabeçalho: sino e 3 abas com 44 px, dentro da tela e clicáveis; a aba Demandas funciona. **Painel de notificações: `left = 16`, `right = 374` com viewport 390, sem rolagem horizontal** (D11-QA-2 corrigido, `d11-real-sino-390.png`). |
| CA11 | **pass** | Snapshot corrompido (`{isto não é json`): `/api/state` 200, Claude `none` "Snapshot ilegível", Codex `fresh` com os valores do rollout — UI mostra os dois blocos normalmente. |

Níveis (fixture): 42,5 %/61 % neutro; 83 % "ATENÇÃO"; 85 % "ATENÇÃO"; 96 %, 97 %, 99,5 % "CRÍTICO" — cor + texto + `aria-valuetext`.
Console: nenhum `pageerror`; os dois únicos erros são `404 /favicon.ico` (pré-existente, também em develop).

## Defeitos
Revalidação em 2026-09-23 após o commit do Frontend `0f5b205` (handoff `2e3898549a5c`), com o mesmo script e dois servidores do worktree (7098 real, 7099 fixture no scratchpad).
- **D11-QA-1 (`4c25f9a37cd3`) — corrigido.** Antes: 74–110 px a 1440 e 106–187 px entre 601 e 900. Agora 68–69 px em todos os estados em 600–1440 px.
  Quando o texto encurta (container queries), a informação completa continua no `title` de cada janela e no `aria-valuetext`:
  ex. a 600 px o texto visível é "85% · falta 15% · ↻ 2h51 ATENÇÃO" e o `aria-valuetext` é "85% usado · falta 15% · renova em 2h51 (02:19) · Atenção".
  O motivo do stale some do texto em ≤ 900 px, mas fica no `title` do alerta ("Coleta com mais de 15 min"); "Indisponível · coletado às HH:MM" continua visível em todas as larguras;
  no estado none, "Indisponível — sem fonte real" e o motivo continuam visíveis.
- **D11-QA-2 (`830e8531a0b1`) — corrigido.** A 390 px o painel abre de 16 a 374 px (antes `left = −89`).
- **D11-QA-3 (`f9e575a63952`) — corrigido.** "coletado às 23:26 · plano plus" em todas as larguras (1440 a 390).

Sem regressão: foco em `#dem-detail` e o texto digitado mantidos após ≥ 2 ciclos de polling (30 → 88 → 96) a 1440 e 390 px; CA1/CA6/CA7/CA11 iguais pela API
(corrompido → Claude `none` "Snapshot ilegível", `/api/state` 200); console sem `pageerror` (só os dois `404 /favicon.ico` que já existiam).

## Observações (não bloqueantes)
- Em ≤ 900 px some "em"/hora do reset; em ≤ 700 px somem "usado" e "renova" (vira ↻) e "Semana" vira "7 d". O rótulo "falta" continua visível e o texto completo fica no `title`/`aria-valuetext`,
  mas para quem vê a tela o primeiro percentual passa a depender da barra para ser lido como "usado". Aceitável pelo contrato; fica como sugestão.
- A 390 px a faixa sticky mede 112–131 px (antes 149–190), ≈ 15 % de 844 px.
- No painel de notificações, uma linha de detalhe longa sem espaços é cortada na borda direita sem reticências (é o conteúdo da notificação, não a D11).
- Evidências a 390 px com rolagem horizontal é anterior à D11.

## Capturas (`tests/ui/`)
`d11-real-{execucoes,execucoes-scroll,demandas-scroll,observabilidade}-{1440,390}.png`, `d11-real-sino-390.png`,
`d11-claude-{fresh,atencao,critico,stale,none,corrompido}-{1440,390}.png`, `d11-largura-{600,700,900}.png`, `d11-foco-demanda-{1440,390}.png`.
