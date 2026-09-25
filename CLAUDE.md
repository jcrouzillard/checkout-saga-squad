# Instruções para o Claude Code

As regras da squad são as mesmas para qualquer fornecedor e ficam em `AGENTS.md`:

@AGENTS.md

## Específico do Claude Code
- Os papéis em `.claude/agents/*.md` também são subagentes nativos do Claude Code (ferramenta Agent), **só** quando
  `tools/squad/executores.py resolve <papel>` devolve `via = "nativo"` (papel no Claude). O gancho `PreToolUse` de
  `.claude/settings.json` (`executores.py guard-agent`) nega o subagente de um papel configurado para outro executor ou
  modelo e indica o `run_agent.py` a usar; um erro no gancho não bloqueia (falha aberta, com aviso).
- O plantão do Orquestrador pode rodar nesta sessão com `/loop 3m` lendo `docs/squad/prompts/plantao.md` **somente
  com o Orquestrador configurado em `claude`** (o ciclo começa por `executores.py check-session`); caso contrário,
  o plantão é `tools/squad/plantao.sh`.
