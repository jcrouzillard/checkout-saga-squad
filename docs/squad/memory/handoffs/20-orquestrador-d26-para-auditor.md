# Handoff 20 — Orquestrador → Auditor · D26 (`50366913d891`) servidor e protocolo

Worktree `plankton-d26` (`feature/D26-executor-e-modelo-por-agente`), sem commit. Contrato D26, ADR-027, G1-D26.
## Feito (dono Orquestrador)
- `tools/squad/executores.py` (novo): resolvedor único (demanda > foto > agente > squad; `null` herda executor+modelo),
  runtime `<cópia principal>/.squad/executores.json` (ou `$SQUAD_ROOT_DATA`), migração das variáveis (evento
  `executor-config via:migracao`), trava flock reentrante + `baseVersion` + escrita atômica, foto `executor-snapshot`,
  checagem `claude auth status --json`/`codex login status` (cache 5 min, saída nunca gravada), política padrao|parar
  (`executor-fallback`), CLI §5 (códigos 0/2/3/4/5/6/7; `set`/`apply-all` recusam dentro de agente), `guard-agent`.
- `.claude/settings.json` (novo): PreToolUse `Agent|Task` → `guard-agent`; o comando sai 0 se o script não existir;
  erro inesperado falha ABERTO com aviso em stderr. Configuração padrão (tudo Claude, modelo padrão) nunca bloqueia:
  80 combinações papel×modelo testadas, 0 bloqueios.
- `perfis/leitura.json`, `perfis/auditoria.json` + `profile_cmd` (§7.1): leitura/auditoria no Claude com
  `--setting-sources project --settings …` e `dontAsk`; Codex `read-only` + `approval_policy="never"`.
- `run_agent.py`: resolve antes de rodar; `--runner/--model` só com `--dry-run` (senão 2); nunca herda `SQUAD_MODEL`;
  campos §9.2 na run e nos progress; falha de login na saída → 1 nova run `--fallback-of`; Auditor `auditoria` roda
  `gate.py verify` antes e `gate.py record` depois (`--gate Gn`).
- `gate.py` + `gate_checks.json` (§7.3/§7.4): lista fixa, sem shell, worktree temporário do ADR-019 removido sempre,
  `record` recusa bloco ausente/inválido e `pass` incoerente com a verificação.
- `triage.py` (`--context triagem --no-snapshot`, `--runner` ignorado com aviso), `conversa.py` (executor/modelo atuais
  do Orquestrador, troca de executor = sessão nova, 503 `executor_indisponivel`), `plantao.sh`, `log.py`
  (`--runner-configured/--model-configured/--config-source/--profile/--fallback`), `alerts.py` (B8, B9, A8),
  `server.py` (`GET/POST /api/executores`, `/aplicar-a-todos`, `/checar`, `POST /api/demand/executores`,
  `/api/state.demands[].executors[]`), `product.py` + `product.toml` `[executors]`.
- Docs: `plantao.md` §E (check-session, resolve/`via`), `orquestrador.md`, `gates.md`, `auditor.md`, `AGENTS.md`, `CLAUDE.md`.
## Desvios / decisões pendentes
- Q2 e Q3 sem resposta: `executores.DECISOES = {Q2: False, Q3: False}`. Orquestrador em Codex recusado (400/código 5);
  Auditor no Claude segue perfil `escrita` (como hoje); só no Codex usa `auditoria` + gate.py. auditor.md/gates.md
  descrevem os dois modos. Alerta de fallback em `padrao` = A8 (o contrato não numerou).
- B8 fecha também com qualquer `executor-config` posterior (o humano agiu).
## Evidências (scratchpad `…/scratchpad/d26/`, dados temporários, claude/codex/mvn falsos)
CA-1,2,3,4,5,6(dry-run),7,8,9,10,12,13,14,15,16(unit),19(dry-run),20 exercitados. Suítes `tests/squad` num clone:
OK alertas_d14, governanca_d14_qa, entrega_por_pr, produto_f2a, conversa_tz_d20, bugs_d16(+qa), ambiente_teste_d15,
e2e_compose_seguro_d15. Quebras PREVISTAS (QA ajusta): instancia_d18 ca14 (chave `demands` no /api/state);
conversa_d17 test_codex e anexos_d21 codex (flags do perfil leitura); delegacao_d19 G_AgenteParadoHttp (o `claude`
falso mata o pai já no `--version` da checagem §6.1). publicador_d24 não rodado (usa `--port 7070`).
## Falta / riscos
- QA: `test_executores_d26.py` + ajustes acima; CA-11/CA-H1..H3 (runs reais) com o humano. O runtime nasce na 1ª
  resolução na cópia principal após o merge (evento de migração no log real).
