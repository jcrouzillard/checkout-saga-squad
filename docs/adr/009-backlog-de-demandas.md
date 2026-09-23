# ADR-009: Backlog de demandas como estado pré-início, sem validação agêntica

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D5 (`d91b7a8b31d9`). Contrato: `docs/contracts/ui-backlog-de-demandas.md`.
Complementa ADR-008 (tipo + validação agêntica).

## Contexto
O humano quer registrar demandas para depois, numa lista de backlog, e escolher quando cada uma entra na fila do
Orquestrador. Nas respostas à validação ele definiu: backlog é um estado pré-início separado, escolhido na criação;
demanda em backlog não vai ao Arquiteto "agora"; ordenação pela prioridade existente; edição permitida no backlog;
o Orquestrador pega tudo da fila, menos o backlog.

## Decisão
1. `task` com `backlog: true` marca a demanda como em backlog; edições são eventos `edit` append-only (estado
   efetivo = `task` + `edit`s), preservando o log imutável e auditável.
2. Sair do backlog = `POST /api/demand/start` (mesmo gatilho do "Iniciar"), com `fromBacklog: true`.
3. **Validação**: a regra da D4 vale **somente** para demandas criadas para início imediato. Demandas de backlog
   **não** são validadas nem na criação nem ao entrar na fila. Motivos: (a) o humano disse explicitamente que o
   backlog não vai ao Arquiteto neste momento; (b) validar na saída adicionaria espera justamente quando o humano
   decidiu "é agora", contrariando o objetivo; (c) a rota padrão do plantão ainda envia critérios vagos ao Arquiteto
   antes da implementação (mitigação). "Validar com o Arquiteto" dentro do backlog fica como evolução.
4. A fila é consumida em ordem: prioridade efetiva (alta > normal > baixa), depois ordem de chegada (`startedAt`).
   A ordem é calculada pelo `pending.py`, fonte única para o plantão de qualquer fornecedor.
5. Fora de escopo: voltar da fila para o backlog, arquivar/remover, reordenação manual.

## Consequências
- (+) Humano controla o momento de entrada na fila; backlog não consome execução de agentes.
- (+) Nenhuma mudança no fluxo D4 para demandas imediatas; histórico completo de edições.
- (−) Demandas de backlog podem entrar na fila menos claras (sem perguntas antecipadas) — mitigado pela triagem do plantão.
- (−) Estado efetivo precisa ser recalculado (task + edits) no servidor, no painel e no `github_sync`.

## Alternativas consideradas
- **Validar ao sair do backlog**: mais segurança, mas contraria a resposta do humano e atrasa o início.
- **Editar reescrevendo o evento `task`**: mais simples de ler, mas quebra o log append-only.
- **Backlog como "Registrada" renomeada**: não separa pré-início de "pronta para iniciar" nem evita a validação.
