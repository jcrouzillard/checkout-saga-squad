# Checklist QA — D23 (F2a): resolvedor de produto e códigos congelados

Demanda `6450aecde7f9` · branch `feature/D23-f2a-resolvedor-de-produto` · commits sob teste `33de93e`, `70b352d`
(parecer G2 `c7c3165`). Contrato: `docs/contracts/f2a-resolvedor-de-produto.md` §8. Data: 2026-09-25.

## Como foi executado
- **Isolamento**: log real (cópia principal) só **lido** e copiado para diretório temporário; servidores do worktree
  em porta livre com `SQUAD_ROOT_DATA`/`SQUAD_LOG` temporários; `HOME` temporário onde há `~/.claude`;
  `SQUAD_CHAT_RUNNER=fake`; PATH sem `claude`/`codex`/`docker` (só `claude`/`gh` **falsos** nos testes que precisam);
  nenhum acesso à 7070. `test_produto_f2a.py` monta o próprio PATH (`<tmp>/bin:/usr/bin:/bin`), nunca herda o do chamador.
- Suítes: `tests/squad/test_*.py`, **uma a uma**
  (`env -i … PATH=<scratch>/bin:/usr/bin:/bin SQUAD_CHAT_RUNNER=fake python3 <arquivo> -v`).
- Navegador: `tests/ui/d23-codigos.js` (container `zenika/alpine-chrome:with-puppeteer`, porta 7461 livre conferida com
  `lsof`), servidor do worktree sobre cópia do log real **reordenada** (linhas dos `task` D7/D8 trocadas), sem injetar
  `codes` (nenhuma requisição interceptada). Resultado: `tests/ui/d23-codigos-result.json`, capturas `d23-*.png`.

## Resultado por critério

| CA | Resultado | Evidência |
|---|---|---|
| CA-1 equivalência sem produto | PASS | `T01Resolvedor.test_ca1_*`: `resolve()` = checkout-saga/D/implícito; `log/gates/handoffs/inbox/runs/memory` = raiz do repo; `server.LOG/GATES_DIR/RUNS_DIR/DATA_ROOT`, `gitflow.LOG`, `github_sync.LOG/STATE/HANDOFFS`, `triage.LOG`, `run_agent.RUNS/MAIN_LOG`, `log.LOG` = constantes de hoje (comparação de `Path`) |
| CA-2 precedência e cadastro | PASS | argumento > `SQUAD_PRODUCT` > padrão; id inexistente → `ProductError`; sem `code_prefix`, `id` ≠ pasta, prefixo `DD` → erro citando campo e arquivo; `[env.prod]` aceito; implícito sem arquivo → embutido; explícito sem arquivo → erro |
| CA-3 paridade com o painel de hoje | PASS | `alerts.demand_codes` de `origin/develop` (arquivo temporário, sem `product.py` ao lado) ≡ `product.demand_codes` sobre cópia do log real (26 `task` do humano); D1–D24 = tabela §4.3; `codes.json` D1–D24 + 4 apelidos; origem só lida |
| CA-4 imunidade à reordenação | PASS | troca D7↔D8: regra antiga troca, nova não; mapa idêntico ao do log original |
| CA-5 apelidos | PASS | todas as `sources` resolvem para o id citado; sem `source` → congelado; `G1-D7.json` e `origin/feature/D9-…` resolvem; `product.py codes --check --log <cópia>` sai 0 sem problemas; conflito de `code` gravado detectado |
| CA-6 demandas novas + corrida | PASS | base **dinâmica** (maior código na cópia; o log já tem D25/D26): POST → B+1, B+2 com `code_prefix=D`; `log.py` → B+3; `task` do orquestrador sem `code`; 10 `log.py` + 10 POST concorrentes = 20 códigos distintos e consecutivos, `codes --check` limpo; `append_task` com `code` recusado; log sintético começa em D1; lacuna = posicional |
| — trava (§4.2) | PASS | `T04Trava`: com `codes.lock` preso por **outro processo**, POST → 503 `trava_de_codigos` após ≥ 4,5 s e log intacto; `log.py --agent humano --type task` → código 1, nada gravado; soltando a trava, POST 201 |
| CA-7 `gitflow.py` honra o log | PASS | repositório temporário: `gitflow.LOG` = temporário, `demand_code` resolve, `log()` grava no temporário, `import_memory`/`snapshot_state` "ignorada" (com `SQUAD_LOG=<caminho>`), nenhum commit de memória; `feature-start D99 … --demand <id>` com código errado sai 2 sem branch |
| CA-8 `github_sync`/`triage` | PASS | `gh` falso: estado gravado ao lado do log temporário, `github-sync.json` do worktree intacto; `triage` com `claude` falso grava `validation` no temporário, com `SQUAD_ROOT_DATA` temporário: **nenhuma** run nova em `plankton-d23/.squad/runs` |
| CA-9 nada no real | PASS | log e `github-sync.json` do worktree: sha256/tamanho/mtime iguais antes/depois (módulo e todas as suítes); log real da cópia principal: só append de terceiros, sem marca `F2A-QA` nem ids sintéticos |
| CA-10 transcrição a partir de worktree | PASS | `run_agent --worktree <tmp>` (`HOME` temporário): metadado em `data_root/.squad/runs` com `transcript` = `transcript_dir_for(<tmp>)/<sessionId>.jsonl`, modelo lido dele; `/api/state.runs` mostra o modelo |
| CA-11 dados em outro lugar | PASS (automatizado) | `T06…test_ca11`: `SQUAD_ROOT_DATA` ≠ raiz, `HOME` temporário, sem `SQUAD_TRANSCRIPTS`; transcrições sintéticas só nas pastas da **cópia principal** e de **outro worktree registrado** (lista real do `git worktree list`, só leitura): `transcript_dirs()` inclui as duas; `enrich_log` dá `modelSource=transcript` com o modelo de cada uma; evento sem transcrição = `none`; run do `run_agent` em `data_root/.squad/runs` aparece em `/api/state` com modelo |
| CA-12 `SQUAD_TRANSCRIPTS` exclusivo | PASS | definido → só essa pasta (e `transcript_dir_for` a devolve); suítes antigas que usam a variável verdes |
| CA-13 painel | PASS | API: `/api/state.codes` = `product.demand_codes`, `task` do humano com `code`, disco sem enriquecimento, `/api/live` com as 8 chaves de hoje (também com log reordenado). Navegador 1440 com log **reordenado** e sem injeção: lista "Todas" 26/26 código+título; cartão D7 = "Entrega de alterações no produto" (posicional daria o título de D8); rotas `#/demandas/D7/D8/D9/D10/D24` abrem `349e5b1bf818/e31bdfb73679/f2324e0f25de/174084ec85d0/cf7a120591b0`; 13 links do painel/alertas coerentes; sem erro de página e sem POST |
| CA-14 `tests/squad` verde | PASS | 13/13 arquivos verdes, um a um (quadro abaixo) |

## Testes ajustados (change-request `4ad036230cd8` e ressalvas do G2)
- `test_bugs_d16::test_demanda_comum_byte_a_byte` — linha do `task` agora termina com `code`/`code_prefix`; o código
  segue `^D[1-9][0-9]*$` e o segundo POST recebe o seguinte.
- `test_instancia_d18::test_ca14…` — `STATE_KEYS_ANTES` ganha `codes` (`/api/live` inalterado).
- `test_bugs_d16_qa::Q05CA13Real` — o clone recebe o `task` do humano `aaaaaaaaaaa1` com `code: D99` gravado (§4.4:
  código gravado vale) e o `product.py` atual; `feature-start D99 … --demand aaaaaaaaaaa1` volta a sair 0.
- `test_conversa_d17::T08Destravar.test_03_lista_fechada` — semeia o próprio alerta fora de `UNLOCK_KINDS`
  (`triage-open` da demanda `e2e2…`); não depende mais do log copiado.

## Suítes (uma a uma)
| Arquivo | Testes | Resultado |
|---|---|---|
| test_alertas_d14 | 20 | OK |
| test_ambiente_teste_d15 | 41 | OK |
| test_bugs_d16 | 38 | OK |
| test_bugs_d16_qa | 18 | OK |
| test_conversa_anexos_d21 | 27 | OK |
| test_conversa_d17 | 44 | OK |
| test_conversa_tz_d20 | 7 | OK |
| test_delegacao_d19 | 27 | OK |
| test_e2e_compose_seguro_d15 | 11 | OK |
| test_entrega_por_pr | roteiro | "Todas as verificações passaram" |
| test_governanca_d14_qa | 19 | OK |
| test_instancia_d18 | 18 | OK |
| test_produto_f2a (novo) | 26 | OK |

sha256 do log e do `github-sync.json` do worktree iguais antes/depois da bateria; nenhum skip. `test_bugs_d16_qa::Q07…test_entradas_patologicas_1mb`
tem limite de 1,0 s por campo e oscilou uma vez (1,04 s) sob carga; verde na repetição — não é regressão da D23.

## Defeitos
- **QA-D23-1 (Orquestrador, baixo)**: `gitflow.py feature-start <código> <slug> --demand <id ausente do log>` sai **1**
  (`sys.exit` em `demand_code`, `gitflow.py:474`) em vez de 2 como no §5.1. Reproduzir: repositório temporário com
  `SQUAD_LOG` sem o id → `feature-start D99 x --demand ffffffffffff` → rc 1.
- **QA-D23-2 (Orquestrador, moderado)**: no POST de bug, `store.put_bug` (`server.py:1546`) grava a pasta/índice do bug
  **antes** de `_append_log`; com a trava ocupada (503 `trava_de_codigos`) a pasta fica órfã sem `task`, e o reenvio cria
  outro id. Além disso o 503 segura `bugs.LOCK`/`LOG_WRITE_LOCK` por até 5 s. Correção sugerida: gravar o bug só depois
  de obter o código (ou desfazer `put_bug` no `LockTimeout`). Achado por leitura de código (`server.py:1546-1557`), não reproduzido em teste.
