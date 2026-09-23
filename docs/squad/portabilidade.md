# Portabilidade entre fornecedores de IA

O desafio pede que a squad funcione **independentemente do modelo/fornecedor**. Aqui, o protocolo não depende de
fornecedor: ele vive em arquivos; o fornecedor é só quem executa cada papel.

| Camada | Arquivo | Claude Code | Codex (testado, codex-cli 0.156) | Outros (Copilot, Devin) |
|---|---|---|---|---|
| Regras comuns | `AGENTS.md` | importado por `CLAUDE.md` | lido nativamente | lido nativamente |
| Papéis | `.claude/agents/<papel>.md` (corpo) | subagente nativo | prompt montado pelo runner | prompt montado pelo runner |
| Delegação | `tools/squad/run_agent.py` | ferramenta Agent **ou** runner | runner (`codex exec`) | runner (novo adaptador) |
| Memória | `decisions.jsonl`, handoffs, gates | `log.py` | `log.py` | `log.py` |
| Git Flow | `tools/squad/gitflow.py` | igual | igual | igual |
| Plantão | `tools/squad/plantao.sh` + `docs/squad/prompts/plantao.md` | `/loop` ou script | script | script |
| Painel ao vivo | transcrições + `.squad/runs/` + eventos `progress` | transcrições nativas | saída do run + `progress` | saída do run + `progress` |

## Como usar com o Codex
```bash
SQUAD_RUNNER=codex python3 tools/squad/run_agent.py qa "Validar o cenário customer_orders" --demand <id>
SQUAD_RUNNER=codex tools/squad/plantao.sh          # Orquestrador em plantão executado pelo Codex
```
Cada execução aparece no Squad Control no card do papel, marcada com o runner, com os marcos `progress` e a saída.

## Evidência
Em 23/09/2026 o **Auditor foi executado pelo Codex** (`run_agent.py auditor ... --runner codex`): leu `AGENTS.md`,
registrou 3 marcos e uma evidência no log e apontou uma lacuna real (5 papéis não citavam `AGENTS.md`), corrigida
na mesma feature. Ver `docs/squad/memory/decisions.jsonl` (eventos com `runner: codex`).

## Adicionar um fornecedor
Inclua uma entrada em `RUNNERS` de `tools/squad/run_agent.py` com o comando não interativo do CLI. Nada mais muda.

## Limites
- A ferramenta de subagentes paralelos do Claude Code não existe em todos os fornecedores; com o runner, a
  delegação é sequencial (bloqueante). O paralelismo pode ser feito disparando vários runners em segundo plano.
- O feed "ação por ação" é mais rico no Claude Code (transcrição nativa); nos demais, o painel mostra os marcos
  `progress` e a saída do CLI.
