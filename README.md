# Checkout Saga · Squad Agêntica

Checkout distribuído (Pedido, Estoque, Pagamento, Envio) coordenado por uma **Saga orquestrada**, construído de forma
autônoma por uma **squad de agentes de IA** (Claude Code) com gates de qualidade, memória compartilhada e intervenção
humana opcional, tudo auditável no painel **Squad Control**.

**Autor:** Julien Crouzillard, Software Engineer · Desafio técnico Itaú · 23/09/2026

> Desafio original: [`docs/desafio.md`](docs/desafio.md) · Roteiro da apresentação: [`docs/apresentacao.md`](docs/apresentacao.md)

## Sumário
1. [Visão geral](#1-visão-geral)
2. [Arquitetura](#2-arquitetura)
3. [Como executar](#3-como-executar)
4. [Como testar e reproduzir as falhas](#4-como-testar-e-reproduzir-as-falhas)
5. [Observabilidade](#5-observabilidade)
6. [Como a squad agêntica opera](#6-como-a-squad-agêntica-opera)
7. [Evidências](#7-evidências)
8. [Estrutura do repositório](#8-estrutura-do-repositório)

## 1. Visão geral

```mermaid
%%{init: {'theme':'neutral'}}%%
flowchart LR
    C([Cliente]) -- POST /orders --> O[order-service :8081]
    O -- order.created --> K[(Kafka)]
    K --> S[saga-orchestrator :8080]
    S -- inventory.reserve / release --> I[inventory-service :8082]
    S -- payment.authorize / refund --> P[payment-service :8083]
    S -- shipment.create --> E[shipping-service :8084]
    S -- order.confirm / cancel --> O
    O & S & I & P & E --- DB[(Postgres · 1 database por serviço)]
    O & S & I & P & E -. OTel .-> J[Jaeger] & PR[Prometheus → Grafana]
```

| Requisito | Onde |
|---|---|
| Fluxo e compensações | [`docs/architecture/saga.md`](docs/architecture/saga.md) |
| Contratos de eventos (6 eventos obrigatórios + comandos) | [`docs/contracts/events.md`](docs/contracts/events.md) |
| APIs, injeção de falhas e seeds | [`docs/contracts/api.md`](docs/contracts/api.md) |
| Idempotência, retries, timeouts, recuperação, rastreabilidade | [`docs/architecture/README.md` §4](docs/architecture/README.md) |
| Decisões (ADRs) | [`docs/adr/`](docs/adr/) |
| Pergunta: de um container para totalmente distribuído | [`docs/architecture/README.md` §6](docs/architecture/README.md) |
| Rastreabilidade requisito → teste | [`tests/TRACEABILITY.md`](tests/TRACEABILITY.md) |

## 2. Arquitetura
As três visões exigidas (negócio, técnica e agêntica) estão em [`docs/architecture/README.md`](docs/architecture/README.md).
Resumo das decisões:

- **Saga orquestrada** (ADR-001): o fluxo inteiro fica visível e testável num único lugar, e as compensações
  ficam explícitas na máquina de estados.
- **Outbox transacional** (ADR-002): estado e evento são gravados na mesma transação; um relay publica no Kafka.
- **Database por serviço** (ADR-003) e **Kafka** com chave `orderId`, o que preserva a ordem por pedido (ADR-004).
- **Idempotência e retries** (ADR-005): `processed_messages` + retry com o **mesmo** `messageId`; participantes
  republicam a resposta anterior ao receber um comando duplicado.
- **Timeouts** persistidos (`deadline_at`) e varridos por um scheduler: sobrevivem ao reinício do coordenador.

## 3. Como executar
Pré-requisitos: Docker (com Compose v2) e ~6 GB de memória para o Docker.

```bash
docker compose up -d --build     # ou: make up
docker compose ps                 # aguarde todos "healthy"
```

| Componente | URL |
|---|---|
| Pedidos (order-service) | http://localhost:8081/orders |
| Saga (diagnóstico) | http://localhost:8080/sagas/{sagaId} |
| Jaeger (traces) | http://localhost:16686 |
| Grafana (dashboard "Checkout Saga") | http://localhost:3000 (porta configurável: `GRAFANA_PORT=3001` no `.env`) |
| Prometheus | http://localhost:9090 |
| **Squad Control** (painel da squad) | `make squad` → http://localhost:7070 |
| **Console de Checkout** (produto: criar pedidos com injeção de falha e ver a Saga ao vivo) | http://localhost:8090 |

Pedido de exemplo:
```bash
curl -s -X POST localhost:8081/orders \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $(uuidgen)" \
  -d '{"customerId":"c-1","deliveryType":"PHYSICAL",
       "items":[{"sku":"SKU-BOOK-001","quantity":1,"unitPrice":49.90}],
       "shippingAddress":{"street":"Av. Paulista","number":"1000","city":"São Paulo","state":"SP","zipCode":"01310-100","country":"BR"}}'
curl -s localhost:8081/orders/<orderId>
```

## 4. Como testar e reproduzir as falhas
```bash
make test                          # testes unitários (mvn test)
mvn -B verify                      # + testes de integração *IT (Testcontainers: Postgres e Kafka reais; exige Docker)
make e2e                           # 12 cenários ponta a ponta contra o compose
bash tests/e2e/run.sh payment_failure   # um cenário específico
```
Falhas são injetadas pelo objeto `simulate` no `POST /orders` (ver [`docs/contracts/api.md`](docs/contracts/api.md)).
Cada cenário, com o `curl` equivalente e o resultado esperado, está em [`tests/e2e/scenarios.md`](tests/e2e/scenarios.md).
Estratégia de testes em camadas (unitário → integração → e2e): [`docs/architecture/testes.md`](docs/architecture/testes.md) (ADR-010).

| Cenário | Como reproduzir | Continuidade / compensações |
|---|---|---|
| Falha no pagamento | `"simulate":{"payment":"DECLINE"}` | libera estoque → cancela pedido |
| Falha no envio | `"simulate":{"shipping":"FAIL"}` | estorna pagamento → libera estoque → cancela pedido |
| Timeout no pagamento | `"simulate":{"payment":"TIMEOUT"}` | retries com o mesmo `messageId` → compensação (estorno idempotente) |
| Timeout no estoque | `"simulate":{"inventory":"TIMEOUT"}` | retries → libera a reserva real → cancela pedido |
| Timeout no envio | `"simulate":{"shipping":"TIMEOUT"}` | retries → cancela o envio → estorna pagamento → libera estoque → cancela pedido |
| Timeout só na 1ª tentativa | `"simulate":{"payment":"TIMEOUT_ONCE"}` | retry com o mesmo `messageId` → segue normalmente → **CONFIRMED** |
| Reinício do coordenador | `"simulate":{"payment":"SLOW"}` + `make kill-orchestrator` | estado e deadlines no banco; o scheduler retoma de onde parou |

O cenário `trace_end_to_end` verifica automaticamente, pela API do Jaeger, que um pedido gera **um único trace com os
5 serviços**. Detalhes e diagramas de sequência: [`docs/architecture/saga.md` §4-5](docs/architecture/saga.md).

## 5. Observabilidade
- **Traces**: OpenTelemetry Java Agent em todos os serviços; `traceparent` persistido no outbox, de modo que o trace
  atravessa HTTP → banco → Kafka → orquestrador → participantes num único trace no Jaeger.
- **Métricas de negócio**: `saga_started_total`, `saga_completed_total{outcome}`, `saga_compensations_total{step}`,
  `saga_timeouts_total{step}`, `saga_step_duration_seconds`, `saga_in_flight`.
- **Logs** JSON com `trace_id`, `orderId` e `sagaId`.
- Guia de investigação por cenário: [`docs/observability.md`](docs/observability.md).

## 6. Como a squad agêntica opera
A squad foi construída com **Claude Code**. A sessão principal é o **Orquestrador**; cada especialista é um subagente
com definição versionada em [`.claude/agents/`](.claude/agents/).

| Agente | Papel | Definição |
|---|---|---|
| Orquestrador | delega, coordena, consolida e controla o fluxo | [`docs/squad/orquestrador.md`](docs/squad/orquestrador.md) |
| Arquiteto | bounded contexts, Saga, eventos, ADRs | [`.claude/agents/arquiteto.md`](.claude/agents/arquiteto.md) |
| Backend | serviços, APIs, mensageria, persistência | [`.claude/agents/backend.md`](.claude/agents/backend.md) |
| DevOps | Dockerfile, compose, CI | [`.claude/agents/devops.md`](.claude/agents/devops.md) |
| Observabilidade | logs, traces, métricas, dashboards | [`.claude/agents/observabilidade.md`](.claude/agents/observabilidade.md) |
| QA | testes unitários, e2e e de falha | [`.claude/agents/qa.md`](.claude/agents/qa.md) |
| **Auditor** (agente extra) | gatekeeper independente: avalia cada passagem com evidências e confiança | [`.claude/agents/auditor.md`](.claude/agents/auditor.md) |

**Estrutura dos agentes.** Cada definição traz prompt, objetivo, responsabilidades, entradas, saídas, ferramentas,
regras de decisão e interação com os demais. As regras comuns ficam em [`AGENTS.md`](AGENTS.md), a constituição
carregada por todos (o `CLAUDE.md` apenas a importa).

**Comunicação.** Nunca é direta entre agentes: segue o padrão *blackboard*, em que o Orquestrador delega e os agentes
leem e escrevem artefatos no repositório. Por isso o protocolo **independe de fornecedor**: Copilot Coding Agent ou
Devin podem ocupar qualquer papel, desde que leiam e escrevam os mesmos arquivos.

**Passagem de contexto.** Ocorre por briefs de handoff em
[`docs/squad/memory/handoffs/`](docs/squad/memory/handoffs/) e pelo prompt de delegação, que inclui objetivo,
entradas, saídas, critérios de gate e limites.

**Conhecimento compartilhado (memory layer).**
- Longo prazo: ADRs e contratos.
- Episódico: [`decisions.jsonl`](docs/squad/memory/decisions.jsonl), um log append-only de tarefas, decisões,
  handoffs, gates e intervenções humanas.

**Conflitos.**
- *Prevenção*: propriedade single-writer por diretório e contrato antes do código.
- *Detecção*: o Auditor compara código × contrato.
- *Resolução*: hierarquia de verdade (desafio > ADR/contrato > código); o Orquestrador arbitra e o humano desempata
  quando há risco de negócio.

**Gates e autonomia.**
- G1, G2 e G3 são definidos em [`docs/squad/gates.md`](docs/squad/gates.md).
- O Auditor emite um parecer com **confiança** e **evidências**.
- A intervenção humana passa a ser **obrigatória** quando a confiança fica abaixo de 70%, o risco é alto ou é o 3º
  ciclo de devolução.
- Autocorreção: um `RETURN` gera nova delegação com as instruções do parecer.

**Como o painel monitora a squad** (sem banco: log de eventos + transcrições do Claude Code):
[`docs/squad/monitoramento.md`](docs/squad/monitoramento.md).

**Squad Control** (`make squad` → http://localhost:7070): linha do tempo das fases, recomendação do Auditor com
confiança, evidências, botões de intervenção humana (gravados no log) e o **feed ao vivo de cada agente**, lido das
transcrições das sessões do Claude Code.

**Como uma demanda entra na squad.** Na aba *Demandas* do Squad Control (ou por uma issue no GitHub), o humano
descreve o que quer e os critérios de aceite. A demanda vira um evento `task` no log e uma issue; o Orquestrador a
lê e a conduz pelo mesmo protocolo: Arquiteto (contrato/ADR) → G1 → Backend → G2 → QA → G3. Quem executa é a
sessão do Claude Code em que roda o Orquestrador; o painel registra, acompanha e permite intervir nos gates.

**Exemplo real (D1).** A demanda *"Listar os pedidos de um cliente"* foi registrada pelo painel e entregue pela
squad: contrato em `docs/contracts/api.md`, ADR-006, `GET /orders?customerId=` no order-service, cenário e2e
`customer_orders` e pareceres do Auditor em `docs/squad/gates/*-D1.json`. O Console de Checkout consome esse endpoint.

**Exemplo real (D2).** A demanda *"Melhorar o visual do checkout"* entrou pelo painel, foi iniciada com prioridade e rota, e passou por: Arquiteto (contrato de tela, ADR-007) → Auditor G1 (83%) → **Frontend** (agente incluído com justificativa) → Auditor G2 (88%) → QA (checklist CA1–CA12 com capturas reais) → Auditor G3 **devolvido** (65%: um comentário editado numa migração Flyway já aplicada mudaria o checksum no próximo rebuild) → **intervenção humana pelo painel** (aceitar devolução) → correção, rebuild e e2e 8/8 → Auditor G3 aprovado (100%).

**Fábrica × produto.** O Squad Control é genérico e pode gerenciar outros projetos: o projeto atual e seus links
vêm de `docs/squad/project.json`. O Console de Checkout faz parte do **produto** e sobe como container próprio
(`checkout-console`) no compose, ao lado dos serviços. A área **Observabilidade** do Squad Control escolhe o produto e
embute o Grafana e o Jaeger dele (o Auditor usa traces e métricas como evidência nos gates).

**Decisão: o Squad Control sobe fora do compose.** O `docker compose up --build` sobe só o **produto** (os 5
serviços, Kafka, Postgres, observabilidade e o `checkout-console`). O Squad Control é a **fábrica** e roda à parte,
com `make squad` (processo Python local, porta 7070). Motivos:
- **Ciclo de vida diferente:** a fábrica precisa continuar de pé enquanto o produto é derrubado, reconstruído e
  testado (`down -v`, `up --build`, e2e de restart do coordenador). Dentro do mesmo compose, cada rebuild do produto
  derrubaria o painel que acompanha esse rebuild.
- **Genérica:** a mesma fábrica gerencia outros produtos (`docs/squad/project.json`); amarrá-la a um compose
  específico a tornaria parte daquele produto.
- **Acesso local:** ela lê o repositório (git, `docs/squad/**`), as transcrições dos agentes em `~/.claude/` e usa as
  CLIs `gh`, `claude` e `codex` com as credenciais do desenvolvedor. Num container, isso exigiria montar o home e
  repassar credenciais, sem ganho para o produto.

## 6a. Portabilidade entre fornecedores (Claude Code, Codex, …)
As regras ficam em `AGENTS.md` (lido pelo Codex, Copilot e Devin; importado pelo `CLAUDE.md`). Qualquer papel roda
com qualquer fornecedor: `SQUAD_RUNNER=codex python3 tools/squad/run_agent.py <papel> "<tarefa>"`, e o plantão do
Orquestrador com `tools/squad/plantao.sh`. Testado com o Codex (Auditor executado pelo `codex exec`).
Detalhes: [`docs/squad/portabilidade.md`](docs/squad/portabilidade.md).

## 6b. Fluxo de branches (Git Flow)
`main` (produção, tags `vX.Y.Z`) ← `release/*` ← `develop` (integração, branch padrão) ← `feature/<demanda>`.
O merge de uma feature em `develop` exige o **G3 aprovado pelo Auditor**; `tools/squad/gitflow.py` aplica as regras.
Detalhes e diagrama: [`docs/squad/git-flow.md`](docs/squad/git-flow.md) · histórico: [`CHANGELOG.md`](CHANGELOG.md).

## 7. Evidências
- Log de execução da squad: [`docs/squad/memory/decisions.jsonl`](docs/squad/memory/decisions.jsonl)
- Pareceres do Auditor: [`docs/squad/gates/`](docs/squad/gates/)
- Handoffs entre agentes: [`docs/squad/memory/handoffs/`](docs/squad/memory/handoffs/)
- Relatório do último e2e: [`tests/e2e/last-report.json`](tests/e2e/last-report.json) — **12/12** (inclui timeouts de estoque, envio e com recuperação, e o trace ponta a ponta, da demanda D6) (1ª execução integrada 6/7 → defeito → autocorreção → 7/7; ver [`tests/TRACEABILITY.md`](tests/TRACEABILITY.md))
- Board da squad no GitHub: issues por agente + Project (kanban) espelhando o log (`make github-sync`)
- Histórico git: cada fase é um commit do Orquestrador

## 8. Estrutura do repositório
```
.claude/agents/        definições dos agentes (prompt, ferramentas, regras)
CLAUDE.md              constituição da squad (regras comuns, ownership, autonomia)
docs/                  desafio, arquitetura, contratos, ADRs, observabilidade, squad (memória, gates)
services/              common + saga-orchestrator + order/inventory/payment/shipping-service
infra/                 postgres (init), observability (prometheus, grafana)
tests/                 e2e, rastreabilidade
tools/squad/           log da memória compartilhada + servidor do Squad Control
checkout-console/      console web do produto (nginx: página + proxy para as APIs)
squad-control/         painel web da squad (genérico; o projeto gerenciado vem de docs/squad/project.json)
```

## 9. Limitações conhecidas e evolução
Todas vêm dos riscos em aberto dos pareceres do Auditor (`docs/squad/gates/`):
- **Uma réplica do orquestrador**: o `group.instance.id` é fixo (`saga-orchestrator-1`, sobrescrevível via
  `KAFKA_GROUP_INSTANCE_ID`). Com N réplicas, cada uma precisa de um id próprio (ex.: nome do pod de um StatefulSet).
- **Testes de integração (`*IT`, Testcontainers)**: rodam no `mvn -B verify` e exigem Docker disponível. O CI executa
  `mvn -B verify`, mas a execução dos `*IT` no CI ainda não foi comprovada nesta entrega (o Auditor registrou o ponto).
- **Ordem do outbox** garantida com 1 instância por serviço; para escalar o relay: particionamento por `orderId`
  ou CDC (Debezium).
- Limpeza de `outbox`/`processed_messages`, DLQ com reprocessamento e schema registry ficam como evolução
  (ver a resposta da seção 12 em [`docs/architecture/README.md`](docs/architecture/README.md) §6).
