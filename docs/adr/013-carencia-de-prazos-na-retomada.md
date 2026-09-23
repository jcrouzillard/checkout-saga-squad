# ADR-013: Carência de prazos na retomada do coordenador

**Status**: Aceito (2026-09-23, Arquiteto — D10, formaliza comportamento já implementado)

## Contexto
O requisito de reinício do coordenador (seção 7 do desafio; cenário 4 de `saga.md` §5) exige que a saga
**continue** após o `saga-orchestrator` cair. O ADR-005 persiste `deadline_at`/`next_retry_at` e manda o scheduler
agir "normalmente" ao voltar. Na prática (defeito do G3 inicial, handoff 04 do Backend), uma queda maior que
`SAGA_STEP_TIMEOUT_MS` fazia o primeiro ciclo cobrar o tempo de queda dos participantes: tentativas eram consumidas
e sagas saudáveis — cuja resposta já estava no Kafka esperando o consumidor — eram compensadas por `STEP_TIMEOUT`.
O Backend corrigiu com static membership do Kafka + uma carência no startup, sem ADR. A D10 identificou que
`saga.md` descrevia o comportamento antigo; pela hierarquia de verdade, a regra precisa estar decidida aqui.

## Decisão
1. No primeiro ciclo do `SagaTimeoutScheduler`, **antes** de qualquer busca de vencidos, o orquestrador executa
   `SagaService.resumeAfterRestart(SAGA_STEP_TIMEOUT_MS)` numa transação: toda saga não terminal com
   `deadline_at < now + SAGA_STEP_TIMEOUT_MS` (lida com `FOR UPDATE SKIP LOCKED`) recebe
   `deadline_at = now + SAGA_STEP_TIMEOUT_MS`.
2. A carência **não** incrementa `attempt`, **não** reenvia comando e **não** emite `saga.step-changed`; registra
   `RESUMED_AFTER_RESTART` no `saga_step_log` e incrementa `saga_resumed_total` (docs/observability.md).
3. Sagas em espera de retry (`next_retry_at`) e terminais não são alteradas.
4. Se a carência falhar, é repetida no ciclo seguinte; nenhum timeout é avaliado antes dela.
5. O consumidor do orquestrador usa static membership (`group.instance.id = KAFKA_GROUP_INSTANCE_ID`, padrão
   `saga-orchestrator-1`) para recuperar as partições sem esperar o `session.timeout.ms` do membro morto.

## Consequências
- (+) O tempo de indisponibilidade do coordenador não é cobrado dos participantes; o reinício não gera compensação
  espúria. Tentativas e contratos de mensagens não mudam (sem mudança em `events.md`/`api.md`).
- (+) Observável: `RESUMED_AFTER_RESTART` + `saga_resumed_total`.
- (−) Um timeout real que coincida com a queda é detectado até um prazo mais tarde (limitado a
  `SAGA_STEP_TIMEOUT_MS` por reinício). Um *crash loop* adiaria timeouts enquanto durar — aceitável, pois nesse caso
  o próprio coordenador está indisponível (visível no healthcheck e no Grafana).
- (−) Com N réplicas, cada réplica que sobe re-arma também as sagas das outras (mesmo efeito limitado acima) e cada
  réplica precisa de um `KAFKA_GROUP_INSTANCE_ID` próprio. A topologia atual (ADR-000) tem uma réplica.
- (−) A carência trava todas as sagas elegíveis numa única transação; em volume de produção, paginar.

## Alternativas consideradas
- **Sem carência (comportamento do ADR-005 literal)**: compensa sagas saudáveis após quedas > timeout — viola o
  "continuar" do requisito de reinício.
- **Descontar o tempo de queda (`deadline += downtime`)**: exige saber quando o coordenador caiu (heartbeat
  persistido); mais complexo e sem ganho observável para o desafio.
- **Reenviar o comando no startup (retry imediato)**: consome tentativa e duplica tráfego; a resposta
  provavelmente já está no tópico.
