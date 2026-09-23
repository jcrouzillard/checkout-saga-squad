# ADR-007: Contrato de tela do Console de Checkout

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D2 (`48b6ace91207`).

## Contexto
A demanda "melhorar o visual do checkout — mais intuitivo e fluido" é vaga e não pode alterar regras de negócio.
Sem um contrato, o Frontend não teria critério de pronto e o QA/Auditor não teria o que verificar.

## Decisão
- Formalizar a interface em `docs/contracts/ui-checkout-console.md`: escopo, 12 critérios de aceite verificáveis,
  estrutura da tela e plano de testes.
- A UI é **somente apresentação**: consome apenas endpoints de `docs/contracts/api.md`; o estado de cada etapa da
  Saga é derivado de `history[]` por uma tabela de mapeamento fixa; nenhum campo/API nova.
- O corpo do `POST /orders` deve permanecer equivalente ao atual (regressão verificável).

## Consequências
- (+) Demanda subjetiva vira critérios objetivos; Frontend, QA e Auditor usam a mesma referência.
- (+) Garantia explícita de não regressão de regras de negócio.
- (−) Mudanças de layout fora do contrato exigem atualizar o contrato (custo pequeno de governança).

## Alternativas consideradas
- **Deixar o Frontend decidir livremente**: rápido, mas sem critério de aceite e com risco de lógica de negócio no front.
- **Novo endpoint agregando saga + pedido para a UI (BFF)**: desnecessário; `GET /orders/{id}` já traz `history[]`.
