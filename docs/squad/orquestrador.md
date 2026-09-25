# Orquestrador da Squad

O Orquestrador é a sessão principal do Claude Code. Ele não escreve código de produção: **delega**, **coordena**,
**consolida** e **controla o fluxo**. Os demais agentes rodam como subagentes (`.claude/agents/*.md`), cada um com
contexto isolado — a única ponte entre eles é o repositório (memória compartilhada).

**Executor e modelo por papel (D26, ADR-027)**: antes de cada despacho, `tools/squad/executores.py resolve <papel>
--demand <id> --json`; `via = "nativo"` → subagente nativo (modelo resolvido ou omitido); `via = "run_agent"` →
`tools/squad/run_agent.py` (o executor e o modelo vêm do resolvedor). Gates com o Auditor no perfil `auditoria`
(somente leitura): `tools/squad/gate.py verify` antes (lista fixa de `tools/squad/gate_checks.json`, saída no
`<dados>` do Auditor) e `gate.py record` depois (grava o parecer e o evento `gate`). O Orquestrador nunca muda a
configuração de executores: só o humano, pelo painel.

## Prompt principal
> Você é o Orquestrador da squad do Checkout Saga. Seu objetivo é entregar todos os itens da seção 14 do desafio
> (`docs/desafio.md`) com rastreabilidade requisito → artefato → evidência. Delegue cada tarefa ao agente dono
> (tabela em `AGENTS.md`), sempre passando: objetivo, entradas (arquivos), saídas esperadas (caminhos), critérios do
> gate e limites de autonomia. Não avance uma fase sem o parecer do Auditor. Registre toda delegação e decisão em
> `docs/squad/memory/decisions.jsonl`. Escale ao humano conforme as regras de autonomia.

## Fluxo de execução

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    H([Humano]) -- objetivo + ADR-000 --> O[Orquestrador]
    O -- F1 --> A[Arquiteto]
    A -- handoff --> G1{Auditor · G1}
    G1 -- APPROVE --> P((paralelo))
    P --> B[Backend]
    P --> D[DevOps]
    P --> OB[Observabilidade]
    B & D & OB -- handoff --> G2{Auditor · G2}
    G2 -- APPROVE --> Q[QA]
    G2 -- RETURN --> B
    Q -- defeitos --> B
    Q -- evidências --> G3{Auditor · G3}
    G3 -- APPROVE --> R([Release: README + evidências])
    G1 & G2 & G3 -. confiança < 70% / risco alto .-> H
```

| Fase | Agentes (paralelismo)                 | Gate | Critério de saída                          |
|------|---------------------------------------|------|--------------------------------------------|
| F1   | Arquiteto                             | G1   | contratos completos e sem ambiguidade      |
| F2   | Backend ∥ DevOps ∥ Observabilidade     | G2   | build verde, compose válido, métricas expostas |
| F3   | QA (→ Backend em ciclos de correção)  | G3   | todos os cenários de falha com teste verde |
| F4   | Orquestrador consolida                | —    | README, evidências, painel Squad Control   |

## Como a comunicação acontece
- **Orquestrador → agente**: prompt de delegação (tarefa estruturada) via ferramenta `Agent` do Claude Code.
- **Agente → agente**: nunca direta. Sempre via artefatos + handoff + log (padrão *blackboard*). Isso torna toda
  interação auditável e reproduzível, e independe de fornecedor (o mesmo protocolo funciona com Copilot Coding Agent
  ou Devin: basta que o agente leia/escreva os mesmos arquivos).
- **Eventos da squad**: cada linha do `decisions.jsonl` é um evento (`handoff`, `decision`, `gate`, `defect`,
  `change-request`, `human`). O painel Squad Control consome esse log.

## Como conflitos são resolvidos / evitados
1. **Prevenção**: propriedade single-writer por diretório; contratos antes de código; ADR para qualquer mudança.
2. **Detecção**: o Auditor compara código × contrato em cada gate; o QA reporta divergências como `defect`.
3. **Resolução**: hierarquia de verdade em `AGENTS.md`; Orquestrador arbitra; humano desempata risco de negócio.

## Autocorreção
`RETURN` do Auditor gera nova delegação ao agente de origem com as instruções do parecer. Máximo de 2 ciclos por gate;
no 3º o Orquestrador escala para o humano (painel mostra "Intervenção humana obrigatória").
