# Constituição da Squad Agêntica — Checkout Saga

Este arquivo é carregado por **todos** os agentes da squad (Claude Code lê `CLAUDE.md` automaticamente).
Ele define as regras comuns, a divisão de responsabilidades e o protocolo de passagem de contexto.

## Missão
Construir, de forma autônoma, controlada e auditável, um checkout distribuído (Pedido, Estoque, Pagamento, Envio)
coordenado por uma **Saga orquestrada**, containerizado e observável.

## Decisões de base (ADR-000, tomadas pelo humano + Orquestrador — não alterar sem novo ADR)
- Java 21, Spring Boot 3.4 (logs estruturados JSON nativos), Maven multi-módulo, pacote base `com.checkout`.
- Layout: módulos em `services/<modulo>`; cada módulo gera `services/<modulo>/target/<modulo>.jar` (`finalName` = artifactId).
- Configuração dos serviços somente por variáveis de ambiente padrão do Spring (`SPRING_DATASOURCE_URL`, `SPRING_KAFKA_BOOTSTRAP_SERVERS`, ...) e `OTEL_*`.
- Topologia: **4 serviços de domínio + 1 orquestrador de Saga**, cada um em seu container.
  | Módulo              | Porta | Banco (Postgres) |
  |---------------------|-------|------------------|
  | `saga-orchestrator` | 8080  | `saga`           |
  | `order-service`     | 8081  | `orders`         |
  | `inventory-service` | 8082  | `inventory`      |
  | `payment-service`   | 8083  | `payments`       |
  | `shipping-service`  | 8084  | `shipping`       |
  | `common`            | —     | (lib compartilhada: envelope de eventos, outbox, idempotência) |
- Broker: Apache Kafka (KRaft, container único). Banco: 1 instância Postgres, **um database por serviço**.
- Observabilidade: OpenTelemetry Java Agent → Jaeger (traces), Micrometer → Prometheus → Grafana, logs JSON com `trace_id`.
- Inicialização única: `docker compose up --build`.

## Agentes e propriedade de artefatos (single-writer)
Cada diretório tem **um único dono**. Um agente só escreve no que é seu; para mudar algo de outro dono, abre uma
*solicitação de mudança* no log de decisões. Isso impede decisões conflitantes/divergentes.

| Agente            | Arquivo de definição                    | Dono de                                                        |
|-------------------|-----------------------------------------|----------------------------------------------------------------|
| Orquestrador      | `docs/squad/orquestrador.md`            | `CLAUDE.md`, `docs/squad/**`, plano e sequência de execução    |
| Arquiteto         | `.claude/agents/arquiteto.md`           | `docs/architecture/**`, `docs/adr/**`, `docs/contracts/**`      |
| Backend           | `.claude/agents/backend.md`             | `services/**` (código de produção), `pom.xml`                   |
| DevOps            | `.claude/agents/devops.md`              | `Dockerfile`, `docker-compose.yml`, `infra/**` (exceto observability), `.github/**`, `Makefile` |
| Observabilidade   | `.claude/agents/observabilidade.md`     | `infra/observability/**`, `docs/observability.md`               |
| QA                | `.claude/agents/qa.md`                  | `services/*/src/test/**`, `tests/**`                            |
| Frontend          | `.claude/agents/frontend.md`            | `checkout-console/**` (interface do produto)                    |
| Auditor (Gatekeeper)  | `.claude/agents/auditor.md`                 | `docs/squad/gates/**` (somente leitura no resto)               |

## Hierarquia de verdade (resolução de conflitos)
1. Requisitos do desafio (`docs/desafio.md`).
2. ADRs aceitos (`docs/adr/`) e contratos (`docs/contracts/`) — o **Arquiteto** é a autoridade.
3. Código. Se código e contrato divergem, o **código está errado** até que um ADR diga o contrário.
4. Empate ou conflito entre agentes → Orquestrador arbitra; se envolver risco de negócio → **humano decide**.

## Memória compartilhada (Memory Layer)
- `docs/squad/memory/decisions.jsonl` — log **append-only** de eventos da squad (handoffs, decisões, gates, evidências, intervenções humanas). Escreva **somente** via:
  `python3 tools/squad/log.py --agent <agente> --type <tipo> --title "..." [--detail "..."] [--to <agente>] [--evidence nome=status ...]`
- `docs/squad/memory/handoffs/<n>-<de>-para-<para>.md` — brief de passagem de contexto (o que foi feito, onde está, o que falta, riscos).
- ADRs e contratos são memória de longo prazo; o log é memória episódica.

## Protocolo de passagem de contexto (handoff)
Ao terminar sua tarefa, todo agente:
1. Escreve o brief em `docs/squad/memory/handoffs/` (≤ 40 linhas; links para arquivos, não cópias).
2. Registra `--type handoff` no log com as evidências produzidas.
3. O próximo agente só começa após o **Auditor** avaliar o gate correspondente (`docs/squad/gates.md`).

## Limites de autonomia
- Nenhum agente faz `git push`, altera credenciais ou remove dados fora do seu diretório.
- Mudança de contrato de evento/API → exige ADR do Arquiteto.
- Gate com confiança < 70% ou risco "alto" → intervenção humana **obrigatória**; caso contrário é opcional.
- Máximo de 2 ciclos de autocorreção por gate; no 3º, escala para o humano.

## Convenções de código
- Mensagens de commit e documentação em português; identificadores em inglês.
- Todo consumidor de evento é idempotente (tabela `processed_messages`); todo produtor usa outbox.
- Todo log carrega `orderId`/`sagaId` via MDC; o `trace_id` vem do OpenTelemetry.
