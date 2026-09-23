# ADR-010: Camadas de teste — integração com Testcontainers (`*IT` + failsafe) e trace verificado via Jaeger

**Status**: Aceito (2026-09-23, Arquiteto) — demanda D6 (`c6f83b5bb5c7`). Detalhes: `docs/architecture/testes.md`.

## Contexto
Os testes Java eram só unitários com mocks; o desafio pede testes de integração e evidência de rastreabilidade
ponta a ponta. Precisamos de testes com Postgres e Kafka reais sem tornar o build unitário dependente de Docker.

## Decisão
1. Três camadas: unitário (`*Test`, surefire), integração (`*IT`, failsafe, Testcontainers) e e2e (compose).
2. Separação por **sufixo `IT` + maven-failsafe-plugin**, não por `@Tag("integration")`: é a convenção padrão do
   Maven/Spring Boot, dispensa configuração de perfis/tags no surefire e dá `mvn test` (sem Docker) × `mvn verify`
   (com Docker) de graça; `-DskipITs` desliga explicitamente.
3. ITs concentrados no **order-service**, que exercita HTTP idempotente, outbox/relay, consumidor idempotente e DLT
   da lib `common` no mesmo contexto real; `@ServiceConnection` para Postgres (`postgres:16-alpine`) e Kafka
   (`apache/kafka-native:3.8.0`). Sem Docker, `verify` falha (nada de pular silenciosamente).
4. O e2e de rastreabilidade envia um `traceparent` conhecido no `POST /orders` e consulta
   `GET /api/traces/{traceId}` do Jaeger, exigindo os 5 serviços no mesmo trace.
5. Nenhuma mudança de contrato; dependências de teste entram por change-request ao Backend.

## Consequências
- (+) Mecanismos críticos (idempotência, outbox, DLT) provados contra infraestrutura real; busca de trace determinística.
- (+) Build unitário continua rápido e sem Docker.
- (−) `mvn verify` exige Docker e leva mais tempo (download de imagens na primeira vez).
- (−) Outros serviços não têm ITs próprios nesta demanda (cobertos pelo e2e); evolução: ITs por serviço.

## Alternativas consideradas
- **`@Tag("integration")` + perfis Maven**: mais configuração para o mesmo resultado.
- **Embedded Kafka (`spring-kafka-test`) + H2**: rápido, mas não é o Postgres/Kafka reais (dialeto, `SKIP LOCKED`, DLT).
- **Buscar trace no Jaeger por serviço + janela de tempo**: não determinístico com execuções concorrentes.
