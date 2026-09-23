# Handoff 02 — DevOps → Backend / QA

## O que foi feito
- `Dockerfile` (raiz) multi-stage único, `ARG MODULE`: build compila **todos** os módulos de uma vez
  (`mvn -q -B package -DskipTests`, sem `-pl`) com cache mount `/root/.m2`, para que a camada de build
  seja idêntica e reaproveitada pelo BuildKit entre as 5 imagens. Runtime `eclipse-temurin:21-jre` com
  `curl`, OTel Java Agent v2.8.0 embutido em `/otel`, usuário não-root, `ENTRYPOINT` com `-javaagent` e
  `-XX:MaxRAMPercentage=75`.
- `.dockerignore` (target/, .git, docs, tests, tools, squad-control, *.md).
- `docker-compose.yml` (`name: checkout-saga`): postgres 5432, kafka (KRaft single-node, interno
  `kafka:9092`, externo `localhost:29092`), jaeger, prometheus, grafana (integrados aos arquivos já
  entregues por Observabilidade em `infra/observability/**`) + os 5 serviços via âncora `x-service`,
  healthchecks em `/actuator/health`, `depends_on: service_healthy`.
- `infra/postgres/init/01-databases.sql`: cria `saga`, `orders`, `inventory`, `payments`, `shipping`,
  owner `checkout`.
- `Makefile` (up/down/ps/logs/build/test/e2e/restart-orchestrator/kill-orchestrator/squad).
- `.github/workflows/ci.yml`: job `build-test` (JDK 21 + `mvn -B verify`) e job `e2e`
  (`docker compose up -d --build --wait` + `tests/e2e/run.sh`, com logs em caso de falha).
- `.env.example` (opcional, documental).

## Correção aplicada durante a verificação
- Os listeners do Kafka precisaram fazer bind em `0.0.0.0` (não no hostname `kafka`), senão o
  healthcheck (`kafka-broker-api-versions.sh --bootstrap-server localhost:9092`, executado **dentro**
  do container) falhava — `localhost` não estava sendo escutado. `KAFKA_ADVERTISED_LISTENERS` continua
  diferenciando `kafka:9092` (interno) de `localhost:29092` (externo).

## Verificações executadas
- `docker compose config -q` → **pass**.
- Subida apenas da infra (`postgres kafka jaeger prometheus grafana`): todos healthy/respondendo.
  Postgres healthy, Kafka healthy, `\l` confirma os 5 databases, Jaeger UI 200, Prometheus `/-/healthy`
  200 (carregou `infra/observability/prometheus/prometheus.yml`, já entregue). Grafana testado em porta
  alternativa (3000 do host ocupado por container **não relacionado** a este projeto) — `api/health` 200,
  provisiona datasource e dashboard `saga.json` sem erro.
- `docker compose down -v` → ambiente limpo (sem containers/volumes residuais).

## Riscos / pendências
- Os 5 serviços de aplicação **não foram construídos/testados** (código em `services/**` ainda não existe
  — é entrega do Backend). Assim que existirem `pom.xml` raiz e `services/<modulo>/pom.xml` com
  `finalName` = artifactId, rodar `docker compose up -d --build` completo para validar o Dockerfile fim a fim.
- Variáveis de ambiente de aplicação seguem o padrão Spring assumido no `CLAUDE.md`; se o Arquiteto/Backend
  definir nomes de env vars adicionais em `docs/contracts/`, adicionar ao bloco `environment` de cada serviço.

## Próximo agente
Backend cria `pom.xml` raiz + `services/<modulo>` (código); QA usa este compose para `tests/e2e/run.sh`.
