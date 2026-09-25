# Checklist D26 — Executor e modelo por agente (`50366913d891`)

Contrato: `docs/contracts/executor-e-modelo-por-agente.md` §12 · ADR-027 · parecer `docs/squad/gates/G2-D26.json`.
Automático: `tests/squad/test_executores_d26.py` (41 testes, custo zero: `claude`/`codex` falsos em
`tests/squad/fixtures/d26/bin`, `CODEX_HOME` vazio = "sem login") e `tests/ui/d26-executores.js` (servidor REAL do
worktree, dados temporários, nenhuma rota simulada).

## Resultado por critério (QA, 25/09/2026)
| CA | Resultado | Evidência |
|---|---|---|
| CA-1 precedência demanda > foto > agente > squad; `null` herda | **pass** | `A_Resolvedor.test_ca1_*` |
| CA-2 migração única + variáveis ignoradas com aviso | **pass** | `test_ca2_*` (3 testes; Q2 fixa o Orquestrador; `SQUAD_MODEL` dentro de run não migra) |
| CA-3 arquivo ilegível → 4, `run_agent` não inicia | **pass** | `test_ca3_*` (JSON quebrado, esquema 2, executor inválido) |
| CA-4 `--runner` sem `--dry-run` → 2 | **pass** | `B_RunAgentPerfis.test_ca4_*` |
| CA-5 não herda `SQUAD_MODEL` do pai | **pass** | `test_ca5_*` (dry-run e execução real com o falso) |
| CA-6 comando por perfil × executor = §7.1 | **pass** | `test_ca6_*` (8 papéis × 2 executores + triagem + conversa + auditoria no Claude) |
| CA-7 foto por demanda | **pass** | `test_ca7_*` |
| CA-8 `guard-agent` | **pass** | `D_GuardAgent.test_ca8_decisoes` + matriz padrão 132 combinações = 0 bloqueios |
| CA-9 sem login `padrao`/`parar` | **pass** | `E_Execucao.test_ca9_*` (fallback aponta a run; `parar` = código 3, nenhum processo) |
| CA-10 falha de autenticação na saída → 1 nova run | **pass** | `test_ca10_*` (nunca 2; sem laço quando o padrão também falha) |
| CA-11 Codex `escrita` grava; Auditor Codex não grava | **pendente (humano)** | roteiro abaixo; comando montado conferido no CA-6 |
| CA-12 `gate.py record` | **pass** | `G_Gate.test_ca12_*` |
| CA-13 `POST /api/executores` | **pass** | `H_Servidor.test_1_*` (409 sem ack, 200 com, evento completo, 409 versão, 400 Q2/incompatível/formato) |
| CA-14 aplicar a todos | **pass** | `test_2_*` (Q2 fixa o Orquestrador em Claude com `runner=codex`) |
| CA-15 campos da run + `/api/state.demands[].diff` | **pass** | `test_ca15_*`, `test_3_*` |
| CA-16 B9 de run nativa | **pass** | `test_3_*` (transcrição de subagente) + `F_AlertasB9` |
| CA-17 conversa usa o executor do Orquestrador | **pass (parcial)** | `test_5_*`, `test_6_*`: resolução e troca de sessão verificadas no código/`build_cmd`, sem turno real |
| CA-18 tela | **pass** | `d26-executores.js`: fase `exec` 39/39, fase `dem` 22/22, 0 erro de página |
| CA-19 perfis leitura/auditoria só fonte `project` | **pass** | `test_ca19_*` (settings do usuário com `allow Bash` + `bypassPermissions` não entram) |
| CA-20 `gate.py verify` | **pass** | `G_Gate.test_ca20_*` (mvn falso; `record` recusa `pass` incoerente; worktree temporário removido; alvo fora do regex nunca roda) |
| Ressalvas G2 | **pass** | B9 não retroativo (foto no meio, troca e desfazer), fallback só da run, trava ocupada > 5 s = permite, `executor-dispatch` agregado, `audit-bash` nega `--output`/`--no-index`/`--ext-diff`/`--git-dir` e abreviações |
| CA-H1, CA-H2, CA-H3 | **pendente (humano)** | roteiro abaixo; CA-H2 depende da Q2 |

## Como rodar o roteiro de navegador (sem simulação)
1. Dados: cópia do log em `$U/data`, `executores.json` criado pelo `executores.py resolve backend --no-check`;
   ambiente com `PATH=tests/squad/fixtures/d26/bin:<python3 ≥ 3.11>:/usr/bin:/bin`, `CODEX_HOME=$U/codexhome` (vazio),
   `CLAUDE_CONFIG_DIR=$U/claudecfg`, `SQUAD_ROOT_DATA/SQUAD_LOG/SQUAD_TRANSCRIPTS` em `$U`.
2. `SQUAD_RUNNER=codex python3 tools/squad/server.py --port <livre>` (a variável aparece como "ignorada").
3. Semente real: `POST /api/executores` (Orquestrador `claude-opus-5-5`, Arquiteto `sonnet`), `executores.py snapshot
   --demand 50366913d891`, uma run do Arquiteto em `codex` (meta em `.squad/runs`, fora do resolvedor → B9).
4. `PHASE=exec` no container `zenika/alpine-chrome:with-puppeteer` (comando no cabeçalho do script).
5. Entre as fases: troca do QA → Codex na demanda (ack), política `padrao` + padrão Claude, `run_agent.py qa` (fallback
   real), política `parar`, troca do DevOps → Codex, `run_agent.py devops` (código 3 → B8 real).
6. `PHASE=dem`. Depois de "Usar o padrão nesta demanda", `run_agent.py devops` roda (retomada) — conferido.

## Aceites humanos (preparados, NÃO executados pelo QA)
Prova de baixo custo: demanda de operação "Prova D26: responder OK" sem mudança de arquivo, cancelada após o G1;
menores modelos (`haiku` no Claude; o menor Codex da conta). Registrar cada resultado com
`log.py --agent humano --type decision --demand 50366913d891`.

### CA-11 — run real curta no Codex (escrita e Auditor) · resultado: ☐ pass ☐ fail
1. Painel → Executores: QA = Codex, modelo = menor da conta; salvar.
2. `python3 tools/squad/run_agent.py qa "Crie tests/prova-d26.txt com OK e registre um progress" --demand <prova>` num
   worktree da prova. Esperado: arquivo criado no worktree, `progress` no log da cópia principal, run `runner=codex`.
3. Rede: no mesmo prompt peça `curl -sI https://example.com` → cabeçalho HTTP na saída (rede ligada no `escrita`).
4. Auditor = Codex; `run_agent.py auditor "Tente criar tests/nao-pode.txt" --demand <prova> --gate G1` → a escrita
   falha (sandbox `read-only`), nenhum arquivo criado; o parecer só é gravado pelo `gate.py record`.

### CA-H1 — Orquestrador Anthropic, Arquiteto OpenAI · resultado: ☐ pass ☐ fail
Executores: Orquestrador = Claude Code (`haiku`), Arquiteto = Codex. Criar a demanda de prova. Na demanda → bloco
"Executores desta demanda": Arquiteto com chip `gpt-… · OpenAI`, Orquestrador `claude-… · Anthropic`, nenhuma marca
"Diferente". Cancelar a demanda após o G1.

### CA-H2 — Aplicar a todos: Codex · resultado: ☐ pendente (Q2) ☐ parcial pass ☐ fail
Parcial (vale até a resposta da Q2): "Aplicar a todos: Codex" → tela diz que o Orquestrador fica em Claude Code; próxima
demanda: 7 papéis `codex`, Orquestrador `claude`; a demanda anterior mantém a foto (sem "Diferente"). Aceite total só
com a Q2 aprovada (Orquestrador via `plantao.sh` no Codex).

### CA-H3 — Codex sem login não quebra a demanda · resultado: ☐ pass ☐ fail
Sem mexer no login real: rodar o plantão com `CODEX_HOME=$(mktemp -d)` só nesse processo.
- Política `padrao`: o passo roda no padrão, aviso A8 na demanda, run com "fallback: sem-login".
- Política `parar`: alerta B8 (bloqueio) na demanda, nada iniciado; "Usar o padrão nesta demanda" → o próximo ciclo
  retoma. (Automático equivalente já verde: `E_Execucao.test_ca9_*`, `H_Servidor.test_4_*`, fase `dem` do navegador.)
