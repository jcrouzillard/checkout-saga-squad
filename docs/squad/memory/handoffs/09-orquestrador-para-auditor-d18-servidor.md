# Handoff 09 — Orquestrador → Auditor: D18, servidor de ambiente e versão (`b72a6bd8caf3`)

**Branch**: `feature/D18-ambiente-e-versao-no-squad-control` (worktree `plankton-d18`, não commitado).
**Spec**: [ADR-021](../../../adr/021-ambiente-e-versao-do-squad-control.md), [contrato](../../../contracts/ui-ambiente-e-versao.md), ressalvas R1–R4/R6 de [G1-D18](../../gates/G1-D18.json).

## O que foi feito
- `tools/squad/instance.py` (novo): ambiente §1, versão §2, atualidade §3; `Instance.snapshot()` devolve o objeto `instance`.
- `tools/squad/server.py` (+18 linhas, localizadas): `import instance`, `INSTANCE` criado em `main()` com a porta real
  (fallback preguiçoso com `server_address[1]`), chave `instance` em `/api/state`, rota `GET /api/instance`
  (`Cache-Control: no-store`). `/api/live` intocado (0 subprocessos medidos).
- `tools/squad/testenv.py`: `find_main_root(root, timeout)` sem fallback (None se git falha ou nenhum worktree em
  `develop`); `main_root()` = `find_main_root() or ROOT` — comportamento da D15 preservado.

## Ressalvas aplicadas
- **R1**: regra 3 (`rev-parse --is-inside-work-tree`) roda antes e independe da 4; `find_main_root` com 2 s; worktree
  de feature na 7070 → `teste`; nenhum worktree em `develop` → `teste` com motivo.
- **R2**: por janela de 30 s, 1 `rev-parse HEAD` (+ `status`, R3); `git diff --name-only` só quando o HEAD muda
  (memorizado por HEAD); um único comando dá estado e `changedPaths` (não `--quiet` + `--name-only`).
- **R3**: `dirty` e `display` recalculados no mesmo cache de 30 s.
- **R4**: `dataIsMain` = `DATA_ROOT` == cópia principal **ou** `SQUAD_LOG` dentro dela; produtivo exige também log sob `ROOT`.
- **R6**: maior tag final `vX.Y.Z` por ordenação numérica em Python; pré-release só se não houver final.

## Evidências
- Teste unitário (12 casos, OK): `scratchpad/d18/test_instance.py` — CA1–CA13, CA20, R1 (sem develop), R6; repos git
  temporários (tag fora da história, commit só de memória, commit em `tools/squad`/`squad-control`, sujo), PATH sem git,
  `git` que dorme (< 5 s, `desconhecido`), contador de `subprocess`.
- Servidor do worktree na 7281 com cópia dos dados: `teste`, `v1.0.0 · 1.1.0-SNAPSHOT · 7aaf1c5 +alterações`,
  `freshness=atual`; `/api/state` manteve as chaves (incl. `version`) + `instance`; `/api/live` sem mudança. Derrubado.
- `tests/squad/` uma a uma: d14 alertas 20 OK, d15 ambiente OK, d16 bugs 38 OK, d16 QA 18 OK, e2e compose 11 OK,
  entrega por PR OK, governança 19 OK.

## Desvios / riscos
- Campo extra `environment.log` (caminho do log, para explicar R4). `commit` = `commitFull[:7]` (não `--short=7`).
- Subida com git lento e `SQUAD_ENV` definida pode levar até ~12 s (6 comandos × 2 s); sem `SQUAD_ENV`, ≤ 2 s.
- O teste unitário está no scratchpad: QA deve portá-lo para `tests/squad/test_instancia_d18.py` (dono QA).
- Conflito provável só em `server.py` com a D17 (trechos pequenos: import, `_instance`, rota, `main`).
- Falta: UI (Frontend, `squad-control/**`) e Playwright CA15–CA19 (QA).
