# Checklist — D24 (`cf7a120591b0`): publicação do Squad Control — validação do QA (G3)

Contrato: `docs/contracts/publicacao-do-squad-control.md` (CA-1..CA-24) · Parecer anterior: `docs/squad/gates/G2-D24.json`
(ressalvas R1..R6) · Brief das correções: `docs/squad/memory/handoffs/18-orquestrador-d24-r1r2-para-qa.md`.
Branch `feature/D24-publicar-squad-control` @ `2dfb206` + mudanças do QA só em `tests/**`, 25/09/2026.

**Ambiente:** repositórios git TEMPORÁRIOS no scratchpad (seed → `origin` bare local → cópia principal `main` em
`develop` + clone `dev` que faz os "PRs"), portas livres ≥ 20000, `SQUAD_CHAT_RUNNER=fake`, PATH sem `claude`/`codex`
em todo processo da squad, `SQUAD_GH=/usr/bin/false`, docker nunca consultado pelo servidor (`SQUAD_TESTENV_PROBE=0`),
navegador descartável `zenika/alpine-chrome:with-puppeteer`. A 7070 real, o pid 7606 e a cópia principal não foram
tocados (nenhuma conexão à 7070; a porta só aparece na asserção de recusa do CA-15); nenhum processo restante.

## Evidências
| Item | Arquivo | Resultado |
|---|---|---|
| Ensaio automatizado do publicador | `tests/squad/test_publicador_d24.py` + servidor falso `tests/squad/publicador_fake_server.py` | **29/29 OK** (Guardas 3 · ParadaGraciosa 1 com 3 subtestes · PublicadorFalso 17 · PublicadorReal 8), ~7 min |
| Navegador (mocks + supervisor REAL) | `tests/ui/d24-publicacao.js` → `tests/ui/d24-publicacao-result.json`, capturas `tests/ui/d24-*.png` | **22/22 OK**, 0 erros de página |
| Ressalva R6 do G2 (§4.5) | `test_alertas_d14.py:394` (`publication` tolerado), `test_instancia_d18.py` (`LIVE_KEYS` + `publication` null sem supervisor; `build.mode`/`build.pid` dentro de `build`, nível de cima inalterado) | 20/20 e 18/18 OK |
| `test_conversa_d17::test_03` | não está na `develop` (a D23 ainda não foi integrada); aplicado aqui o **mesmo** patch do QA da D23 (`7b7cbfe`, alerta B4 semeado) — hunks idênticos, o merge da D23 não conflita | 44/44 OK |
| Regressão `tests/squad/` uma a uma | d14 20 · d15 41 · d16_qa 18 · d16 38 · d21 27 · d17 44 · d20 7 · d19 27 · e2e_compose_seguro_d15 11 · entrega_por_pr (45 PASS, "Todas as verificações passaram") · governanca_d14_qa 19 · instancia_d18 18 | **todas verdes** |
| Regressão de UI (cópias) | `d18-ambiente-versao.js`, `d20-conversa-visual.js`, `d21-imagens.js` a partir de cópia de `tests/ui` (servidor do worktree, dados temporários, axe montado) | d18 **28/28** (axe 0 violações) · d20 **17/17** · d21 **23/23**, 0 erros de página |

## Resultado por critério
| CA | Resultado | Evidência |
|---|---|---|
| CA-1 merge → função nova na aba em ≤ 60 s | **PASS no sandbox; aceite humano pendente (roteiro abaixo)** | `PublicadorReal.test_02`: merge que muda o `<title>` → `squad-updated` em 14 s (poll 15 s e estabilidade 10 s padrão), HTML novo servido. Navegador (`CA1-real-recarga-sozinha`): aba aberta em `#/demandas` recarrega sozinha na mesma rota com "Squad Control atualizado para … 9c1506e" 27,2 s depois do pronto (inclui o push) |
| CA-2 servidor quebrado volta sozinho | **PASS no sandbox; aceite humano pendente** | import quebrado (`server.py` real): `phase=preflight`, `rolledBack=false` 3 s após o merge, pid e commit no ar inalterados, `lastResult` no `/api/live`; quebra só em produção (`commit-errado`): `phase=health`, `rolledBack=true`, `/api/instance` com `build.mode=anterior` e `freshness.state=revertido`; faixas da UI `CA2-faixa-rollback` e `CA2-faixa-preflight` |
| CA-3 merge fora de `watch_paths` não reinicia | PASS | `docs/**` + `services/**`: HEAD avança por ff, pid igual, 0 eventos `squad-*` |
| CA-4 só a cópia principal em develop | PASS | `start` num clone em `release/9.9.9` → código 2 "cópia principal em develop", nada criado |
| CA-5 só avanço simples | PASS | HEAD à frente com código (`tools/squad/qa-local.txt`): executor git sem `ls-remote/fetch/merge/rebase/reset/checkout`, HEAD e eventos inalterados; depois de remover o commit local publica. HEAD à frente só com memória: coberto pelo R1 (log local não enviado) |
| CA-6 código sujo bloqueia; memória suja não | PASS | `squad-control/qa-marker.txt` alterado + `publisher.py publish` → `squad-update-failed phase=guard trigger=cli` "mudança rastreada…", `squad-publish-requested agent=humano trigger=cli` com o mesmo `requestId`. O log da cópia fica sujo o tempo todo (eventos do próprio supervisor) e nunca bloqueou; R1 prova a junção sem perda |
| CA-7 ponto seguro no automático | PASS (R5) | falso: livre antes → `waitedSec` 9,1, sem `interrupted`, estado `aguardando-ponto-seguro` com `deadline` e `busy`; ocupado → `waitedSec` 20,1 com `interrupted`. **Real, resposta longa (DORMIR, 200 s)**: `waitedSec` 20,1, `interrupted={conversa, turn}`, mensagem `interrompida/reinicio_publicacao` com "parcial" e runner encerrado |
| CA-8 botão | PASS | `server.py` real supervisionado: Host externo → 403 `origem_invalida`; `text/plain` → 400; `when` inválido → 400; turno ativo sem `confirm` → 409 `resposta_em_andamento` com `busy`; `confirm` → 202 e `squad-updated trigger=botao sameCommit=true interrupted=busy`; sem supervisor → 409 `sem_supervisor` ("make squad") e `publication=null` no `/api/live`; `safe` nos 5 paralelos → publicado. UI: diálogo modal, "Publicar agora" (`confirm:true`), "quando terminar" (`safe`), Esc fecha só o diálogo |
| CA-9 parada graciosa | PASS (R3) | com `SQUAD_SUPERVISED=1`: 3/3 (kill, killpg, kill) → saída 0 em ≤ 8 s, `interrompida/reinicio_publicacao` com "parcial", runner (filho) morto, e o SSE do servidor novo devolve o registro final. Também pelo fluxo real do botão e do automático |
| CA-10 eventos | PASS | exatamente 1 `squad-updated` ou 1 `squad-update-failed` por publicação (conferido por commit/`requestId`); 1 `squad-publish-requested` (humano) por pedido aceito; nenhum evento quando nada muda (CA-3, CA-23) |
| CA-11 painel / avisos | PASS | `CA11-contagem` (19 → 17 s), `CA11-aguardando-safe`, `CA11-verificando`, `queda-reiniciando`, `CA11-aviso-10s`, faixas de falha; real: aviso "atualizado" após a troca |
| CA-12 selo / botão | PASS | botão só no produtivo, motivo em texto sem supervisor, `[!] revertido (falhou ddddddd)` com texto e `aria-label` |
| CA-13 recarga | PASS | mocks: recarga na mesma rota sem rascunho; com rascunho não recarrega, "Recarregar" e rascunho preservado. **Real**: recarga sozinha em `#/demandas` |
| CA-14 conversa interrompida | PASS | registro REAL (SIGTERM com `SQUAD_SUPERVISED=1` num turno FXD20): texto parcial + "Resposta interrompida pela publicação…", "Reenviar" cria turno com a mesma pergunta |
| CA-15 segurança dos testes | PASS | `start/run --port 7070` → código 2, `ensure` → 0, "recusado… 7070", **0 comandos git** no executor gravador e nenhum arquivo criado; `make squad` num sandbox temporário → recusado da mesma forma. `grep 7070 tests/squad/test_publicador_d24.py`: só no teste de recusa |
| CA-16 supervisor único / stop | PASS | 2º `start` → código 0 "publicador no ar", pid do servidor igual, 1 servidor produtivo; `stop` → porta livre, `state=parado`, `status` código 1 |
| CA-17 queda | PASS (R5) | SIGKILL no filho → de volta em ≤ 5 s + `squad-server-crashed restarts=1`; `sai-apos-3s` → eventos na 1ª e 5ª queda e rollback `phase=health rolledBack=true` "5 quedas em 5 min" (~48 s) |
| CA-18 revertido persistente | PASS | mesmo SHA não tentado em 4 ciclos; `stop`+`start` com `failedCommit == HEAD` sobe o anterior (`revertido`/`anterior`); SHA novo publica |
| CA-19 o supervisor se atualiza | PASS (R5) | merge em `publisher.py` → `squad-updated` e execv: mesmo pid do supervisor, **mesmo pid do servidor**, `supervisor.commit` novo, 1 só resultado; `selftest` quebrado (`alerts.py` que levanta no import) → `squad-update-failed phase=supervisor`, supervisor antigo segue no ar |
| CA-20 orçamento e `/api/instance` | PASS | `/api/live` p95 ≤ 300 ms e ≤ 64 KB com `publication` (6 chaves, ≤ 1 KB); `/api/instance` = `{environment, build, freshness}` com `build.mode`/`build.pid`; `tests/squad` inteiro verde só com as mudanças do §4.5 |
| CA-21 `make` | PASS (parte automatizável) | `make -n`: `squad`→`publisher.py start`, `squad-primeiro-plano`→`server.py`, `squad-parar/status/logs/publicar`; `server.py --port N` sem supervisor → `supervised=false`. `make squad` real = passo 1 do aceite humano |
| CA-22 página de manutenção | PASS (R5) | novo e anterior quebrados → `phase=rollback rolledBack=false`, `fora-do-ar`; `/` = "Squad Control fora do ar" com o SHA e "Tentar de novo"; `/api/state` e `/api/live` 503 `fora_do_ar`; POST externo 403; após o conserto, POST local → 202 e `squad-updated trigger=botao` |
| CA-23 travas de git | PASS | com `.git/MERGE_HEAD`: 10 s só com `rev-parse`/`symbolic-ref` (0 `ls-remote`, 0 `fetch`, 0 `merge`, 0 `worktree`), HEAD e eventos inalterados; removido → publica no ciclo seguinte |
| CA-24 primeira adoção | PASS | servidor não supervisionado da cópia na porta: `ensure` → 0 e pid intacto; `start` sem TTY → código 2 "só com confirmação no terminal" e pid intacto; `start --yes` (só testes) → antigo encerrado, supervisionado na mesma porta com `build.pid` novo |
| **R1** memória suja + PR que muda a memória | PASS | escritor contínuo (0,1 s) no log da cópia + PR que muda `decisions.jsonl` (3 eventos), um handoff e o `index.html`: `squad-updated` em 27 s após o merge, HEAD = merge, **0 perdidos** (284 locais, 3 remotos), **0 duplicados por id**, handoff no disco, nenhuma cópia em `.squad/squad-control/merge/` |
| **R2** pedido pendente | PASS | 2 POST seguidos → 202 + 409 `publicacao_em_andamento`; 5 paralelos → 1×202 + 4×409; 1 `squad-publish-requested` e 1 `squad-updated` por rodada |

Observações (não bloqueiam):
- O `pendingRequestId` do brief só vem no caminho sob o flock; no caso comum (pedido já gravado) o 409 sai pelo `api_view`
  sem esse campo. O contrato (§4.2) só exige `code` e `state`.
- Um PR que só **reverte** o código quebrado volta ao commit no ar: `needs_publish` (diff vazio contra o commit no ar)
  corretamente não publica, e a faixa de falha do pré-voo fica até o humano fechá-la ou até o próximo `squad-updated`.

## Roteiro do aceite humano (NÃO executado pelo QA — 7070 real, após o merge da D24)
Pré-requisito: PR da D24 integrado na `develop`; o `make squad` antigo (pid 7606) no ar.
1. **Adoção (R9, CA-21, CA-24)** — na cópia principal, em `develop`: `make squad`. Confirmar com `s` a pergunta
   "Encerrar o Squad Control atual (pid 7606) e subir o supervisionado? [s/N]". Esperado: o terminal volta com a URL
   `http://localhost:7070`, o pid do supervisor e do servidor e os caminhos dos logs. `make squad-status` → "publicador no ar".
   Na aba aberta, o selo mostra "Publicação: no ar, nada pendente" e o botão "Publicar Squad Control" habilitado.
2. **CA-1** — abrir um PR de teste que muda um texto visível do painel (ex.: o subtítulo "Cada demanda tem uma página…"
   em `squad-control/index.html`), sem mexer em nada fora de `squad-control/`. Deixar a aba em `#/demandas`, **sem
   rascunho** no campo da conversa e sem resposta em andamento. Integrar o PR no GitHub e anotar o `mergedAt`
   (`gh pr view <n> --json mergedAt`). Esperado, sem tocar no terminal: evento `squad-updated` no log com `ts − mergedAt ≤ 45 s`
   (`grep squad-updated docs/squad/memory/decisions.jsonl | tail -1`), a aba recarrega sozinha na mesma rota, aparece
   "Squad Control atualizado para …" e o texto novo, tudo em ≤ 60 s do `mergedAt`.
3. **CA-2 (opcional, recomendado)** — PR de teste com `import conversa_inexistente` no topo de `tools/squad/server.py`.
   Esperado: faixa "Publicação de <sha7> não foi feita (verificação prévia)…", a 7070 continua respondendo com o commit
   anterior (selo). Reverter com um PR que também mude outro texto (um revert puro não dispara publicação).
4. Limpeza: nenhuma — o supervisor segue no ar. `make squad-parar` só se quiser voltar ao modo antigo (lembrar a R4 do
   G2: com o plantão ativo, o `ensure` sobe o publicador de novo em ≤ 3 min).

Registrar o resultado com `python3 tools/squad/log.py --agent humano --type human --demand cf7a120591b0 --title "D24: aceite CA-1/CA-2 na 7070" --evidence CA1=pass CA2=pass`.
