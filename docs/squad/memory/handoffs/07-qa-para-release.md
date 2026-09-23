# Handoff 07 — QA → Release (Jev)

## Resultado
Suíte e2e 7/7 verde (`tests/e2e/last-report.json`), 60 testes unitários verdes em
`services/*/src/test/**` (surefire reports). Matriz de rastreabilidade atualizada com status real
por requisito: `tests/TRACEABILITY.md`.

## Histórico relevante para o gate
1ª execução integrada: 6/7 (falha em `coordinator_restart` — rebalance do Kafka de 45s vs deadline
de 5s da Saga, ver defect `docs/squad/memory/decisions.jsonl` id `23d3ca1dd0de`). Backend corrigiu
com static membership + carência no startup (`docs/squad/memory/handoffs/04-backend-core-para-qa.md`,
seção "Correção pós-e2e"). 2ª execução: 7/7.

## Gaps conhecidos (não bloqueantes, documentados em TRACEABILITY.md §Observações)
- Timeout de `inventory`/`shipping` não tem cenário e2e dedicado (só `payment`, mesmo mecanismo).
- Rastreabilidade no Jaeger é evidência visual/manual, não automatizada.
- `order-service` e `common` não têm `src/test/**` próprio (cobertos só via e2e).
- `409` para `Idempotency-Key` repetida com corpo diferente não é assert obrigatório.

## Onde olhar
- `tests/TRACEABILITY.md` — matriz completa com evidência por requisito.
- `tests/e2e/scenarios.md` — roteiro de demo, `curl` validado contra `tests/e2e/run.sh`, com
  "o que mostrar na demo" por cenário.
- `tests/e2e/last-report.json` — última execução completa (7/7).

## Verificação feita nesta rodada
Checagem pontual `bash tests/e2e/run.sh happy_path_physical` — PASS. Não rodei a suíte completa de
novo (ambiente em avaliação paralela pelo Jev).
