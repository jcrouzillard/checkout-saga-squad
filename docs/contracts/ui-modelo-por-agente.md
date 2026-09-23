# Contrato — Modelo usado por agente na demanda (D9, `174084ec85d0`, operação)

> Decisão: ADR-012 (`docs/adr/012-modelo-no-log-da-squad.md`). Implementação: **Orquestrador** (`tools/squad/**`:
> `log.py`, `run_agent.py`, `server.py`) e **Frontend** (`squad-control/index.html`). Não toca contratos do checkout.

## 1. Estado atual (investigado)
- Transcrições de subagentes (`~/.claude/projects/<slug>/<sessão>/subagents/agent-*.jsonl`): cada linha
  `type:"assistant"` traz `message.model` com o **ID exato** (ex.: `claude-opus-5-5`, `claude-sonnet-5`,
  `claude-fable-5-1`); há linhas `<synthetic>` (geradas pelo harness, não são modelo). O `.meta.json` **não** tem
  `model` → hoje `run.model` sai vazio para subagentes (`server.py` `parse_run`: `meta.get("model", "")`).
- `.squad/runs/<id>.json` (`run_agent.py`) só tem `runner`; `server.py` `collect_external_runs` põe
  `"model": meta.get("runner")` → a UI mostra `codex`/`claude` como se fosse modelo (**incorreto**).
- Saída do Codex (`.squad/runs/<id>.log`) tem cabeçalho com `model: gpt-5.6-sol` e `provider: openai`.
- `claude -p` grava transcrição própria em `~/.claude/projects/<slug>/<session-id>.jsonl` (com `message.model`);
  o prompt gerado por `run_agent.py` contém o `run_id` (`--run <run_id>`).
- `log.py`: eventos sem campo de modelo. Frontmatter dos papéis tem só alias (`model: opus|sonnet`), não ID.
- UI: único ponto hoje é a tag `r.model` em `feedHtml()`.

## 2. Fonte de verdade do modelo, por caminho (ordem de precedência)
| Caminho | Fonte primária | Retroativo |
|---|---|---|
| Subagente nativo Claude Code | `message.model` das linhas `assistant` da transcrição do subagente (ignorar `<synthetic>`/vazio) | Sim (transcrições existem) |
| Sessão principal (Orquestrador) | `message.model` da transcrição principal | Sim |
| `run_agent.py` runner `claude` | `run_agent` gera `--session-id <uuid>` para `claude -p`, grava `sessionId` no run; ao terminar (e o servidor, ao vivo) lê `message.model` de `~/.claude/projects/<slug>/<sessionId>.jsonl` | Runs antigos: servidor procura a transcrição de topo cujo 1º prompt contém o `run_id` |
| `run_agent.py` runner `codex` | se `--model`/`SQUAD_MODEL` dado → passa `-m <id>` ao `codex exec`; o valor **gravado** é sempre o lido do cabeçalho `model:`/`provider:` do `.log` (reflete o que rodou) | Sim (cabeçalho no `.log`) |
| Evento manual (`log.py`) | `--model <id>`; se omitido, env `SQUAD_MODEL`; `--run` se omitido, env `SQUAD_RUN` | — |
| Evento sem `model` | servidor enriquece (seção 4) | Sim, se reconstruível |

`run_agent.py` exporta `SQUAD_RUN=<run_id>` e, quando já conhecido antes do início, `SQUAD_MODEL=<id>` para o
processo filho; assim `handoff`/`gate`/`progress` do agente herdam `run`/`model` sem mudar o prompt. Alias sem ID
(`opus`) **nunca** é gravado em `model`; vai em `modelRequested`.

## 3. Mapeamento ID → fornecedor (função única `provider_of(id, hint)` no servidor)
1. `hint` explícito (linha `provider:` do Codex; `anthropic` para transcrição Claude Code) vence.
2. Por prefixo do ID normalizado (minúsculas, sem sufixo `[...]` como `[1m]`, sem prefixo de região `us.`/`eu.`):
   `claude-`, `anthropic.` → **Anthropic**; `gpt-`, `o1`, `o3`, `o4`, `codex-`, `openai/` → **OpenAI**.
3. Senão, pelo runner: `claude` → Anthropic, `codex` → OpenAI. Senão **desconhecido**.
O ID exibido é o **original** (não normalizado).

## 4. Enriquecimento de eventos (servidor, somente leitura; o log continua append-only)
Para cada evento de agente ≠ `humano` sem `model`, na ordem: (a) `run` → `model` do run; (b) transcrição (subagente
ou principal) com `tool_use` Bash cujo `command` contém `log.py`, o mesmo `--agent` e o mesmo `--title`, com
`timestamp` a até 120 s do `ts` do evento → `message.model` dessa linha; (c) senão `model: null` (não registrado).
Resultado no evento da API: `model`, `modelProvider`, `modelSource` ∈ `logged|run|transcript|none`.
Eventos do `humano` e os gerados pelo servidor (`POST /api/*`) não recebem modelo (`modelSource: "n/a"`).

## 5. Campos novos (todos opcionais/aditivos; nada removido ou renomeado)
- **Log** (`decisions.jsonl`, via `log.py`): `model` (string, ID exato). Omitido quando vazio (regra atual).
- **Run** (`.squad/runs/<id>.json`): `model`, `modelProvider`, `modelRequested`, `sessionId` (só claude).
- **`/api/state` → `runs[]`**: `model` = ID exato ou `null` (**deixa de conter o nome do runner**; o runner segue em
  `runner`), `models` = IDs distintos em ordem de 1º uso, `modelProvider`, `demand` (do meta ou, no subagente,
  do 1º `--demand <12 hex>` do prompt inicial; senão `null`). Se houver vários, `model` = o mais usado.
- **`/api/state` → `log[]`**: `model`, `modelProvider`, `modelSource` como na seção 4 (calculados, não gravados).
Consumidores atuais continuam válidos: campos antigos mantidos; o único ajuste semântico é `runs[].model`, cujo
único consumidor é `feedHtml()`.

## 6. Exibição (Frontend)
Formato canônico do chip: `<ID> · <Fornecedor>` em `mono`, ex.: `claude-opus-5-5 · Anthropic`,
`gpt-5.6-sol · OpenAI`. Fornecedor desconhecido: `<ID> · fornecedor desconhecido`. Sem modelo: `não registrado`
(estilo `muted`). `title` do chip com a origem (`modelSource`). Sem emoji/logo novo, sem lib externa.
- **(a) Execução** (`feedHtml`, cartão de cada run): chip no lugar da tag atual `r.model`; se `models.length > 1`,
  um chip por ID. Runner continua visível só se diferente do fornecedor óbvio (opcional).
- **(b) Resumo da demanda** (cabeçalho da demanda ativa em `renderExecucoes` e detalhe em `renderDemandas`):
  linha "Modelos: " com os pares distintos agente→modelo das runs `demand === id` e dos eventos da demanda,
  ex.: `Arquiteto: claude-opus-5-5 · Anthropic · Auditor: gpt-5.6-sol · OpenAI`. Se nenhum: `Modelos: não registrado`.
- **(c) Linha do tempo / eventos** (itens `handoff`, `gate`, `progress`, `decision`, ... da demanda e a tabela de
  Decisões): chip após o agente de cada evento. Evento do humano: sem chip.

## 7. Critérios de aceite
| # | Critério | Verificação |
|---|---|---|
| CA1 | `log.py --model X` grava `"model":"X"`; sem `--model` e com `SQUAD_MODEL=Y` grava `Y`; sem ambos, não grava a chave. Idem `--run`/`SQUAD_RUN`. | 3 chamadas + `tail -3 decisions.jsonl` (em log de teste) |
| CA2 | Run `codex` novo: `.squad/runs/<id>.json` tem `model` igual à linha `model:` do `.log` e `modelProvider: "OpenAI"`; `--model`/`SQUAD_MODEL` vira `-m` no `--dry-run`. | `run_agent.py ... --runner codex --dry-run` + run real curto |
| CA3 | Run `claude` novo: comando tem `--session-id`; run gravado com `sessionId` e `model` = `message.model` da transcrição (`claude-*`), `modelProvider: "Anthropic"`; alias do frontmatter só em `modelRequested`. | run real curto + inspeção do json |
| CA4 | `/api/state`: nenhum `runs[].model` é `claude`/`codex`; subagentes têm `model` com ID `claude-*` e nunca `<synthetic>`; `models` lista IDs distintos. | `curl /api/state \| jq '.runs[]\|{agent,model,models,runner}'` |
| CA5 | Retroativo: o run codex `20260923163500-auditor-9a491c` mostra `gpt-5.6-sol · OpenAI`; eventos antigos cujo `log.py` aparece numa transcrição ganham `modelSource:"transcript"`; os demais `model:null` e a UI mostra "não registrado". | `jq` no `/api/state` + painel |
| CA6 | `provider_of`: `claude-opus-5-5[1m]`→Anthropic, `us.anthropic.claude-x`→Anthropic, `gpt-5.6-sol`→OpenAI, `o3`→OpenAI, `llama-3`→desconhecido (sem runner). | teste unitário/`python3 -c` |
| CA7 | (a) cada cartão de execução mostra o chip no formato `<ID> · <Fornecedor>` ou `não registrado`. | painel, aba Agentes/gaveta |
| CA8 | (b) o resumo da demanda D9 lista os modelos distintos por agente que atuaram nela. | painel, demanda D9 |
| CA9 | (c) cada evento não-humano da linha do tempo e da tabela de Decisões mostra o chip; eventos do humano não. | painel |
| CA10 | Sem regressão: log continua append-only (servidor não reescreve `decisions.jsonl`); campos antigos intactos; nenhum `undefined`/`null` literal na tela; 390 px sem overflow horizontal; sem nova dependência externa. | `git diff --stat`, DevTools |
| CA11 | Escopo: diff apenas em `tools/squad/{log,run_agent,server}.py` e `squad-control/index.html`; nada em `services/**` nem `docs/contracts/events.md`. | `git diff --stat` |
