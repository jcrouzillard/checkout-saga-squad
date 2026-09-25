# Handoff 10 — Orquestrador → Auditor · D19 (`402e76f187f9`) servidor, log, alertas e gitflow da delegação

**Feito** (worktree `plankton-d19`, branch `feature/D19-delegar-tarefas-pela-conversa`, sem commit), conforme
[ADR-022](../../../adr/022-delegacao-pela-conversa.md) e o [contrato](../../../contracts/delegacao-pela-conversa.md):
- `tools/squad/conversa.py`: bloco ```delegar (`split_action`, streaming corta os dois blocos), `validate_delegation`
  (8 tipos, pré-condições §2, alvo canônico, agente e piso de risco pelo servidor, risco alto por gate < 70%/alto,
  `attemptKey` estável e limites 1/2, ok libera o próximo `ajuste-pontual`), `delegaveis`/`delegacaoAtiva` no
  contexto, confirmação com `task`/`riskAck` revalidada sob `log_lock` (409 obsoleta, 422 risco, 400 tarefa).
- `tools/squad/server.py`: `record_delegation` (único gravador), `GET /api/delegacoes`, `GET /api/conversas/pedido`,
  A6 no `/api/live`, anotação dos alertas delegáveis, `delegations` no `/api/state`, `--delegation-check <id>`.
- `tools/squad/alerts.py`: B6 e A7 na reprodução de `Rules`, A6 com relógio (`SQUAD_HANDOFF_STALLED_S`, 1 800 s),
  `delegations_of`/`active_delegation`; A2 traz `runStartedAt` e `delegation`.
- `tools/squad/log.py`: recusa `--type delegation` (código 2); tipos §3.2 com campos obrigatórios; `--delegation`
  (padrão `$SQUAD_DELEGATION`), `--change-request`/`--resolution`, `--refs`, `--sha`, `--mergeable`.
- `tools/squad/pending.py`: `mergeable` na mesma chamada com cache de 30 s; `conflito de PR`/`conflito resolvido`;
  `delegação: …` (não pausada) e `delegação cancelada: …`.
- `tools/squad/gitflow.py`: `demand-worktree`, `feature-sync` (merge, STATE = develop, dono por arquivo, código 3,
  `--abort`), `review-update` (G3 APPROVE com `--delegation`, mesmo PR, recusa código 4 se o diff tocar a tupla
  `STATE` inteira — ressalva 2 do G1-D19-2). Nunca switch/commit na cópia principal.
- `tools/squad/run_agent.py --delegation/--worktree/--dados` (ressalva 1): marca a run, exporta `SQUAD_DELEGATION` e
  `SQUAD_LOG` da cópia principal, monta `<tarefa_confirmada_pelo_humano>` + `<dados>` com `docs/squad/prompts/delegacao.md` (novo).
- Prompts `conversa.md` (Delegar), `plantao.md` (seções P e D) e `docs/squad/gates.md` (G3 da delegação).

**Evidências** (scratchpad `…/scratchpad/d19/`): `test_unit_d19.py` (11), `test_http_d19.py` (7),
`test_gitflow_d19.py` (fluxo completo em repo temporário com origin local e `gh` simulado) — todos OK. Suítes
`tests/squad/*.py` (8) passam, inclusive `test_conversa_d17.py` com runner simulado.
CAs cobertos: 2, 3, 4, 5, 6, 7, 8, 9, 10(a–d), 11, 12, 13, 14, 15, 16, 17, 18, 22 (inclui passo `"inicio"`, ressalva 3),
23, 25 (pending), 27, 28, 29(a–d), 30 (flag). Não cobertos aqui: CA-1 (real), 19/20/21/24/26 (execução do plantão/UI/QA).

**Desvios** (registrados em `decision` `94c228264536`): `delegations` só no `/api/state` (o `/api/live` mantém as
chaves, `test_alertas_d14`); `pending.py` parseia o JSON de `--json state,mergeable` em vez de `-q`; A6/A7 usam
"demanda encerrada" do `Rules._closed` (inclui G3 APPROVE sem PR) para não abrir avisos de demandas antigas.

**Riscos**: autenticidade do `delegation` é por convenção (log.py + par na conversa); `delegables()` roda o validador
por alerta a cada `/api/live` (barato com o log atual, vigiar com log grande); `review-update` exige o gate com
`--delegation` (Auditor precisa passar a flag, `gates.md`).
