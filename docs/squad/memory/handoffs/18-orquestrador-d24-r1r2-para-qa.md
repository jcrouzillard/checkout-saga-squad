# D24 · ressalvas R1/R2 do G2 → QA (Orquestrador)
Worktree `plankton-d24` (feature/D24-publicar-squad-control), sem commit. Decisão `84b1d532e0da`.

**R1 (mitigado)** `tools/squad/publisher.py`: `sync()` → se o `merge --ff-only` falha, `memory_block()` confere se o
único bloqueio são arquivos de STATE (espelho de `gitflow.STATE`) que o PR também muda; `ff_with_memory()` faz, para
`decisions.jsonl`: link duro do log vivo em `.squad/squad-control/merge/`, troca atômica pelo blob do HEAD (o caminho
nunca some), `merge --ff-only` (até 5 tentativas) e SEMPRE `reattach()`: reanexa em O_APPEND os eventos das cópias
ausentes, por `id` (sem id: texto exato); cópias só são apagadas após conferir. Arquivo de STATE com conteúdo igual
ao do commit novo também passa (cópia devolvida se o ff falhar). Qualquer outro bloqueio (índice, `github-sync.json`
divergente, código) → comportamento antigo (espera o review-sync). Rejeitado: disparar o review-sync (rebase,
autostash, commit e push — fora do "só fast-forward"). Obs.: o `log.py` não tem trava; nenhum escritor usa flock.
**R2** `tools/squad/publication.py`: pedido em `requests/` = `publicacao_em_andamento` (409 com `pendingRequestId`);
conferência+gravação sob flock `requests.lock`; `api_view` já dá `canPublish=false` com pedido pendente.

**Ensaios** (scratchpad `d24-r1/`, origin bare local, porta 26371/27371, runner fake, PATH sem claude/codex):
- R1 `r1.py` com escritor a cada 0,1 s: r1a 24,4 s / r1c 17,9 s até `squad-updated`; 0 perdidos (254 e 190 locais,
  3 remotos), 0 duplicados por id, HEAD = merge, handoff novo no disco, nenhuma cópia restante.
- Estresse 500 eventos/s (r1b): 5 tentativas falham → espera o review-sync como antes; 0 perdidos, 0 duplicados.
- R2: 2 POST seguidos → 202 + 409; 5 paralelos → 1×202 + 4×409; 2 `squad-publish-requested` e 2 `squad-updated`.
- Suítes uma a uma (`d24-r1/suites.out`): mesmas 3 falhas previstas do G2 (d14 live, d18 LIVE_KEYS, d17 test_03).

**Para o QA**: cobrir R1 (log sujo + PR que muda memória ≤ 60 s, contagem por id; ff que falha → junção sem perda)
e R2 (409 com pedido pendente, concorrência). 7070/pid 7606/cópia principal não tocados; sandbox derrubado.
Risco residual: `github-sync.json` sujo e mudado pelo PR ainda espera o review-sync (o Arquiteto registra no §13).
