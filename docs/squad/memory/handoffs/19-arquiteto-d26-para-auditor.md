# Handoff 19 — Arquiteto → Auditor (G1) · D26 `50366913d891` · executor e modelo por agente

**Branch/worktree**: `feature/D26-executor-e-modelo-por-agente` em `plankton-d26` (sem commit; Orquestrador commita).

## Entregue
- ADR: `docs/adr/027-executor-e-modelo-por-agente.md` (Proposto).
- Contrato: `docs/contracts/executor-e-modelo-por-agente.md` (donos §1, formato §3, precedência §4, CLI §5,
  checagem/política §6, permissões §7, acionamentos §8, eventos §9, API §10, UI §11, aceite §12, Codex §13, riscos §14).

## Decisões centrais
- Resolvedor único `tools/squad/executores.py`; `SQUAD_RUNNER/SQUAD_MODEL/SQUAD_CHAT_*` só semeiam (migração) e passam
  a ser ignoradas; `run_agent --runner/--model` só com `--dry-run`.
- Onde mora: guarda `[executors]` no `product.toml` (PR); padrão/agente/política em `runtime_dir/executores.json` (por
  máquina e produto); troca por demanda e foto (`executor-snapshot`) no log; toda mudança = `executor-config`.
- Foto na entrada da demanda → "Aplicar a todos: Codex" vale inteira para a próxima demanda.
- Subagentes nativos: `via` do resolvedor + gancho `PreToolUse` (`guard-agent`) que nega + alerta `executor-divergente`
  no servidor (detecção independente). Plantão em sessão Claude Code suspende se o Orquestrador não for `claude`.
- Política `onUnavailable`: `padrao` (padrão) | `parar`; falha de login na saída → mesma política, uma vez.
- Perfis `leitura`/`auditoria`/`escrita`/`orquestracao`; Auditor somente leitura nos dois executores, parecer gravado
  por `gate.py record`.

## Achados no código atual (corrigidos pelo contrato)
- Plantão via ferramenta Agent ignora `SQUAD_RUNNER` (sempre Claude).
- `run_agent` aninhado herda `SQUAD_MODEL` do pai (modelo de outro fornecedor).
- Auditor via `run_agent` roda com perfil de escrita; triagem usa `--allowedTools` (não restringe).

## Pontos para o G1 olhar
- §7.1 Orquestrador no Codex = `danger-full-access` (pede aceite humano, Q2).
- Auditor deixa de rodar build/testes (Q3). `network_access`/`.git` no `workspace-write` a confirmar no CA-11.
- Conflito com a D24 (`server.py`, `log.py`, `index.html`): implementar após o merge dela.
- Regras de alerta B8/B9 supõem que a D24 não as ocupe.

## Perguntas ao humano
Q1 política padrão `padrao`? Q2 Orquestrador no Codex com `danger-full-access`? Q3 Auditor sem build/testes?
Q4 configuração por máquina (não sincronizada entre máquinas)? Q5 foto por demanda (não troca no meio)?
