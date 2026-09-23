# Checklist QA — D9 · Modelo exato + fornecedor por agente (`174084ec85d0`)

Contrato: `docs/contracts/ui-modelo-por-agente.md` (CA1–CA11) · Gate anterior: `docs/squad/gates/G2-D9.json`.
Branch `feature/D9-modelo-usado-na-demanda` (HEAD `79ba3e3`), servidor do worktree na porta 7093 com
`SQUAD_ROOT_DATA` = cópia principal (dados reais: 278 eventos, 31 runs). Navegador: Chrome headless via Puppeteer
(`ghcr.io/puppeteer/puppeteer:latest`, script `tests/ui/d9-screenshots.js`).

## Resultado por critério

| CA | Status | Evidência |
|----|--------|-----------|
| CA1 | pass | `SQUAD_LOG` temporário: `--model X --run R1` grava `model:"X"`,`run:"R1"`; `SQUAD_MODEL=Y SQUAD_RUN=R2` grava `Y`/`R2`; sem ambos as chaves `model`/`run` não existem. |
| CA2 | pass | Run codex **real** (`run_agent.py qa "responda apenas OK" --read-only --runner codex`, `SQUAD_LOG` temporário): `.json` com `model: gpt-5.6-sol`, `modelProvider: OpenAI` = cabeçalho `model:`/`provider:` do `.log`; evento "Finalizado" com `model: gpt-5.6-sol`. `-m` no dry-run já coberto no G2. |
| CA3 | pass | Run claude **real**: `.json` com `sessionId: ea37f0e2-…`, `model: claude-opus-5-5` (= único `message.model` da transcrição `~/.claude/projects/…-plankton-d9/ea37f0e2-….jsonl`), `modelProvider: Anthropic`, `modelRequested: sonnet` (alias só aí). "Finalizado" com `model`; "Iniciado" sem (modelo desconhecido antes do início — conforme §2). |
| CA4 | pass | `/api/state`: 31 runs, nenhum `model` ∈ {claude, codex, opus, sonnet, `<synthetic>`, ""}; subagentes só `claude-*`; `models` sem duplicatas. |
| CA5 | pass | `20260923163500-auditor-9a491c` → `gpt-5.6-sol · OpenAI` (visível na gaveta do Auditor). `modelSource`: transcript 206, run 15, none 28, n/a 29. Amostra de 10 eventos `transcript` conferida contra as transcrições reais (agente + título, Δt 0–111 s): **10/10 iguais** (inclui `claude-sonnet-5`, `claude-fable-5-1`). Os 28 `none` são legítimos: gravados por scripts (`triage.py` "Triagem…/Validação…", `gitflow.py` "integrada…/Branch…/Entregue: PR…") ou gates antigos do Auditor sem chamada `log.py` em transcrição; as poucas menções de título em transcrição são textos (heredoc/grep) fora da janela de 120 s. UI mostra "não registrado". |
| CA6 | pass | `provider_of`: `claude-opus-5-5[1m]`→Anthropic, `us.anthropic.claude-x`→Anthropic, `gpt-5.6-sol`→OpenAI, `o3`→OpenAI, `llama-3`→None (UI: "fornecedor desconhecido"). |
| CA7 | pass | Gaveta do Auditor (`d9-gaveta-auditor-*.png`): cada cartão de execução com selo `claude-opus-5-5 · Anthropic` ou `gpt-5.6-sol · OpenAI`. |
| CA8 | pass | Resumo da demanda D9 (código D10 no painel) em Execuções e Demandas: "Modelos: Arquiteto / Auditor / Frontend / Orquestrador / outro / QA: claude-opus-5-5 · Anthropic" (`d9-execucoes-*.png`, `d9-demandas-*.png`). Outras demandas listam também `claude-sonnet-5` do QA. |
| CA9 | pass | Tabela Decisões (`d9-decisoes-*.png`): 278 linhas; 249 não-humanas **todas** com selo (28 "não registrado"); 29 do Humano, **nenhuma** com selo. `title` do selo traz a origem (run/transcrição). Linha do tempo da demanda ativa: 11 selos. |
| CA10 | pass (ressalva) | Console: **0 erros de JS** (único erro: 404 de `/favicon.ico`, pré-existente). Nenhum `undefined`/`null` gerado pela UI (as ocorrências de "undefined" são texto de detalhes de eventos antigos). Sem nova dependência externa no diff. `decisions.jsonl` do worktree intacto (`cmp` antes/depois). 1440 px: `scrollWidth = clientWidth`. **390 px: `scrollWidth 524 > 390`** — causado pela barra `.tabs` do topo e, na gaveta, por `<pre>`/detalhes de comandos longos; **idêntico em `develop`** (servidor 7070: 524 px e gaveta 532 px) → não é regressão da D9; os selos `.mchip` quebram linha e não contribuem. Defeito pré-existente aberto para o Frontend. |
| CA11 | pass | `git diff --stat cf405d2..HEAD`: `tools/squad/{log,run_agent,server}.py`, `squad-control/index.html` + parecer `docs/squad/gates/G2-D9.json` (do Auditor). Nada em `services/**` nem `docs/contracts/events.md`. |

## Observações (não bloqueiam)
- Resumo "Modelos:" mostra a chave crua `outro` para o run `a3fbc6d3ff7e61396` (subagente genérico do Orquestrador,
  "Orquestrador · D9: tools/squad") — sem rótulo em `AGENTS`. Cosmético.
- `run_agent.py` registra `modelRequested: sonnet` (frontmatter do QA), mas não repassa o alias ao `claude -p`: o run
  real rodou em `claude-opus-5-5`. O registro está correto (mostra o que rodou); o alias não é aplicado — comportamento
  anterior à D9, vale decisão do Orquestrador.
- Na tabela Decisões a 1440 px o selo quebra em 3 linhas por causa da largura da coluna "Agente" (legível).
- Eventos "Iniciado via …" sem `--model` explícito ficam com o modelo reconstruído pelo servidor via `run`.

## Capturas
`tests/ui/d9-{execucoes,demandas,decisoes,gaveta-auditor}-{1440,390}.png`.
