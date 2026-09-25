# Handoff 16 — Orquestrador → Auditor · D24 (`cf7a120591b0`): publicador do Squad Control (servidor)

Worktree `plankton-d24` (`feature/D24-publicar-squad-control`), sem commit. Base: [ADR-025](../../../adr/025-publicacao-do-squad-control.md), [contrato](../../../contracts/publicacao-do-squad-control.md), [G1-D24](../../gates/G1-D24.json).
## Feito (só `tools/squad/**`)
- `publisher.py` (novo): supervisor stdlib com `start|stop|status|publish|ensure|selftest|run`; `flock` único, pidfile,
  `status.json` (tmp+rename), logs `server.log`/`publisher.log` com rotação copytruncate (5 MB, 3 arquivos); `ls-remote` a
  cada 15 s + `fetch` só com SHA novo; travas §5.1.0 antes de qualquer escrita git (HEAD em develop, sem
  rebase/merge/cherry-pick/`index.lock`, cópia principal, código limpo, sem divergência — também antes do fetch);
  `merge --ff-only` sem autostash; pedidos do botão a cada 2 s; pré-voo (`py_compile` + candidato ≥ 17070 com dados
  sintéticos, `SQUAD_ENV=teste`, `SQUAD_TESTENV_SPAWN=0`, `SQUAD_TESTENV_PROBE=0`); ponto seguro via `busy`
  (20 s auto, 600 s botão `safe`); troca, saúde depois (20 s) e estabilidade (10 s); rollback por `plankton-squad-prev`;
  página de manutenção (503 em `/api/*`, "Tentar de novo"); quedas com backoff e rollback após 5 em 5 min; `execv`
  quando `publisher.py`/`publication.py` mudam (servidor mantém o pid); 1ª adoção só com `s` no terminal; `ensure` nunca adota.
  Guarda estrutural CA-15: porta 7070 exige cópia principal em develop e recusa diretório temporário.
- `publication.py` (novo): leitura de `status.json` com cache por mtime, `api_view`, `live_view` (≤ 1 KB), pedidos, §4.2 e SIGTERM gracioso.
- `server.py` (3 pontos): rotas `GET /api/squad-control/publication` e `POST /api/squad-control/publish` (`_local_ok`,
  evento `squad-publish-requested` agent humano), `publication` no `/api/live`, sinais no `main()`.
- `conversa.py`: `Engine.shutdown(reason)` → `interrompida`, `code=reinicio_publicacao`, texto parcial preservado.
- `instance.py`: `build.mode`, `build.pid`, `freshness.state=revertido` + `failedCommit`; rótulo "publicador (rollback)".
- `log.py`: 4 tipos novos · `testenv.py`: `plankton-squad-prev` recusado como teste · `plantao.sh`: `publisher.py ensure`.
## Ensaio completo (repo git temporário + origin bare local, porta 26070, candidato 27070+, dados sintéticos)
Merge → `squad-updated` em **26,8 s** (push→evento, com 10 s de estabilidade); import quebrado → `preflight` em 9,9 s,
pid do servidor intacto; quebra só com dados reais → `health` + `rolledBack=true` em 50,1 s, no ar o anterior
(`mode=anterior`, `freshness=revertido`), 0 novas tentativas em 50 s; ocupado → espera 20,1 s e interrompe
(texto "parcial" salvo, runner morto) + `execv` com o mesmo pid do servidor; botão: 409 sem `confirm`, `safe` espera o
fim, 2º pedido 409; `SIGKILL` no filho → volta em 1,5 s + `squad-server-crashed`; anterior também quebrado → manutenção
e volta com SHA novo; `MERGE_HEAD` → 0 escritas git e 0 eventos; divergência (memória local não enviada) → nada tocado
até o `review-sync`; código sujo → `guard`. A 7070 real (pid 7606) não foi tocada.
## Suítes `tests/squad` (uma a uma)
Quebram como previsto no §4.5 (QA atualiza): `test_alertas_d14::test_api_state_e_live_por_http`,
`test_instancia_d18::test_ca13_live_zero_subprocessos_e_formato`. `test_conversa_d17::test_03_lista_fechada` já falha
no HEAD sem as mudanças (depende do log copiado). Todas as demais passam.
## Desvios
1. SIGTERM gracioso só com `SQUAD_SUPERVISED=1` (senão quebraria `test_conversa_d17::test_reinicio`); CA-9 roda supervisionado.
2. Filho `principal` recebe `SQUAD_ENV=produtivo` (permite ensaio fora da 7070). 3. Estado extra `parado` após `stop`.
4. Variáveis só de teste: `SQUAD_PUBLISH_STABLE_S`, `_HEALTH_TIMEOUT_S`, `_STOP_GRACE_S`, `_CANDIDATE_PORT`, `_PREV_WORKTREE`.
5. Fora: alerta do sino para `squad-update-failed` e preenchimento de `demand`/`pr` (opcionais no §8).
## Riscos
`/api/state` real pode demorar na 1ª leitura (transcrições) dentro dos 20 s da saúde; a D23 mexe nos mesmos arquivos (merge, não rebase).
