# Handoff 14 — Orquestrador → Auditor · D23 (F2a) servidor/ferramentas (`6450aecde7f9`)

**Worktree**: `plankton-d23` (branch `feature/D23-f2a-resolvedor-de-produto`), sem commit. Contrato:
[`f2a-resolvedor-de-produto.md`](../../../contracts/f2a-resolvedor-de-produto.md); errata ADR-024 §11; parecer `G1-D23.json`.

## O que foi feito
- `tools/squad/product.py` (novo): `resolve` (argumento > `SQUAD_PRODUCT` > checkout-saga; `SQUAD_LOG` > `SQUAD_ROOT_DATA` > repo),
  `demand_codes` (congelado > `code` gravado > posicional com lacuna), `resolve_code` (apelido só com `source`),
  `append_task` (`flock` em `.squad/locks/codes.lock`, timeout 5 s, O_APPEND+fsync, recusa `code` pronto),
  `transcript_dir_for`/`transcript_dirs` (cache 30 s, cópia principal + worktrees), CLI `resolve`/`codes [--check]`/`freeze-codes`.
- `docs/squad/products/checkout-saga/product.toml` (mínimo) e `codes.json` **D1–D24** (`--until cf7a120591b0`, sobre CÓPIA
  do log de 666 linhas, sha256 `f90cf935…`), com os 4 apelidos D7–D10 e suas `sources`.
- `alerts`/`testenv`/`pending` → `product.demand_codes` (conversa e server via `alerts`); `server.py`: `task` do humano
  (comum e bug) por `append_task` (503 `trava_de_codigos`), `/api/state.codes` + `code` em cada `task`, `github_issues` ao lado
  do log, transcrições multi-pasta e caminho exato da run; `log.py --agent humano --type task` grava `code`/`code_prefix`.
- `gitflow`: LOG/`demand_code` pelo resolvedor, `SQUAD_LOG` explícito aos filhos `log.py`, `feature-start --demand` valida
  código (sai 2), snapshot/import/align/discard/STATE do feature_sync pulados com memória fora do repo ("… ignorada").
- `github_sync` (LOG/STATE/HANDOFFS resolvidos) e `triage` (LOG + `SQUAD_LOG` aos filhos); `run_agent`: runs em
  `data_root/.squad/runs`, `transcript` exato do cwd efetivo (worktree).

## Evidências
- Paridade (cópia do log real): `alerts.demand_codes` de `origin/develop` ≡ `product.demand_codes` (24/24); CA-4 (troca
  D7/D8) congelado não muda; CA-5 apelidos e `codes --check` = 0. Script: scratchpad `d23/verify_f2a.py` → **32/32 PASS**
  (CA-1…CA-10, CA-13; corrida 10 `log.py` + 10 `POST` = D28…D47 consecutivos).
- `tests/squad` um a um (`SQUAD_CHAT_RUNNER=fake`): 9/12 verdes; 3 falhas — ver riscos.
- Log real: prefixo de 666 linhas idêntico à cópia, nenhum id/título sintético; mudanças só de outros agentes.

## Riscos / pendências
- **QA (change-request)**: `test_bugs_d16::test_demanda_comum_byte_a_byte` (task agora traz `code`/`code_prefix`, §4.2) e
  `test_instancia_d18::test_ca14…` (chave `codes` nova no `/api/state`, §4.6) precisam do acréscimo. `test_conversa_d17::
  T08Destravar.test_03_lista_fechada` já falha no HEAD sem esta mudança (depende do log copiado).
- **Janela da tabela**: entrou `task` novo `233278d0cfa9` às 17:49 (posicional D25). Regenerar `codes.json` antes do
  `feature-finish` com `--until` no último `task` (§4.5).
- Scripts copiados sozinhos por testes antigos (gitflow/log/pending/testenv) caem na regra de antes (sem product.py ao lado).
- `log.py`/`gitflow` passam a honrar `SQUAD_ROOT_DATA` (antes só `SQUAD_LOG`/ROOT). Varredura de worktrees inclui `plankton-teste`.
- Conflito esperado com a **D24** em `server.py` (rotas/estado) — quem integrar por último resolve (decisão `31400c3b82d1`).
