# Instruções para o Claude Code

As regras da squad são as mesmas para qualquer fornecedor e ficam em `AGENTS.md`:

@AGENTS.md

## Específico do Claude Code
- Os papéis em `.claude/agents/*.md` também são subagentes nativos do Claude Code (use a ferramenta Agent).
- O plantão do Orquestrador pode rodar nesta sessão com `/loop 3m` lendo `docs/squad/prompts/plantao.md`,
  ou fora dela com `tools/squad/plantao.sh`.
