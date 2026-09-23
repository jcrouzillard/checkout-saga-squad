# syntax=docker/dockerfile:1.7
#
# Dockerfile único e multi-stage, parametrizado por ARG MODULE, usado para
# construir a imagem de qualquer um dos 5 serviços Spring Boot do checkout
# (saga-orchestrator, order-service, inventory-service, payment-service,
# shipping-service). Ver docker-compose.yml para o valor de MODULE de cada
# serviço.
#
# Build: docker build --build-arg MODULE=order-service -t checkout-saga/order-service:local .

########################################################################
# Estágio 1 — build: compila TODOS os módulos Maven de uma vez só.
#
# Copiamos o pom.xml raiz e a árvore inteira de services/ (em vez de copiar
# primeiro só os poms e depois o código) porque isso já é suficiente para o
# BuildKit reaproveitar esta camada entre as 5 imagens: o conteúdo copiado
# é idêntico para todos os serviços (não usamos "-pl", compilamos tudo), e o
# cache mount do repositório Maven local evita rebaixar dependências a cada
# build. É mais simples e igualmente robusto que separar um passo de
# "dependency:go-offline".
########################################################################
FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /workspace

COPY pom.xml ./
COPY services/ ./services/

RUN --mount=type=cache,target=/root/.m2 \
    mvn -q -B package -DskipTests

########################################################################
# Estágio 2 — runtime: imagem final enxuta, apenas com o JRE e o jar do
# módulo pedido via ARG MODULE.
########################################################################
FROM eclipse-temurin:21-jre AS runtime

ARG MODULE
ENV MODULE=${MODULE}

# curl é usado pelo healthcheck do docker-compose (GET /actuator/health).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# OpenTelemetry Java Agent (instrumentação automática -> OTLP -> Jaeger).
ADD https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.8.0/opentelemetry-javaagent.jar /otel/opentelemetry-javaagent.jar
RUN chmod a+r /otel/opentelemetry-javaagent.jar

# Usuário não-root.
RUN groupadd --system checkout \
    && useradd --system --gid checkout --home-dir /app --no-create-home checkout \
    && mkdir -p /app \
    && chown -R checkout:checkout /app

WORKDIR /app
COPY --from=build --chown=checkout:checkout /workspace/services/${MODULE}/target/${MODULE}.jar /app/app.jar

USER checkout

ENTRYPOINT ["java","-javaagent:/otel/opentelemetry-javaagent.jar","-XX:MaxRAMPercentage=75","-jar","/app/app.jar"]
