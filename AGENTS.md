# Constituição da Squad Agêntica — Checkout Saga

Este arquivo é carregado por **todos** os agentes da squad, de qualquer fornecedor: Codex, Copilot e Devin leem
`AGENTS.md`; o Claude Code o importa a partir de `CLAUDE.md`. É a fonte única das regras.
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
| Orquestrador      | `docs/squad/orquestrador.md`            | `AGENTS.md`, `CLAUDE.md`, `docs/squad/**`, `tools/squad/**`, plano e sequência |
| Arquiteto         | `.claude/agents/arquiteto.md`           | `docs/architecture/**`, `docs/adr/**`, `docs/contracts/**`      |
| Backend           | `.claude/agents/backend.md`             | `services/**` (código de produção), `pom.xml`                   |
| DevOps            | `.claude/agents/devops.md`              | `Dockerfile`, `docker-compose.yml`, `infra/**` (exceto observability), `.github/**`, `Makefile` |
| Observabilidade   | `.claude/agents/observabilidade.md`     | `infra/observability/**`, `docs/observability.md`               |
| QA                | `.claude/agents/qa.md`                  | `services/*/src/test/**`, `tests/**`                            |
| Frontend          | `.claude/agents/frontend.md`            | `checkout-console/**` (interface do produto) e `squad-control/**` (interface da fábrica) |
| Auditor (Gatekeeper)  | `.claude/agents/auditor.md`                 | `docs/squad/gates/**` (somente leitura no resto)               |

## Fluxo de branches (Git Flow) — obrigatório
| Branch | Origem | Destino | Quem | Regra |
|---|---|---|---|---|
| `main` | — | — | ninguém commita direto | só recebe `release/*` e `hotfix/*` por PR; cada merge gera tag `vX.Y.Z` |
| `develop` | `main` | — | integração | recebe features por PR; é a branch padrão do repositório |
| `feature/<código>-<slug>` | `develop` | `develop` (PR) | agente/Orquestrador | uma por demanda (`feature/D3-cupom-desconto`); PR **só após G3 APPROVE**; **merge é do humano** |
| `release/<x.y.z>` | `develop` | `main` + back-merge em `develop` | Orquestrador | com aprovação humana; fixa a versão do pom e o CHANGELOG |
| `hotfix/<x.y.z>-<slug>` | `main` | `main` + `develop` | Orquestrador | correção urgente em produção, mesmos gates |

- Use sempre `python3 tools/squad/gitflow.py` (feature-start/finish, release-start/finish, hotfix-start/finish):
  ele aplica as regras acima: só abre PR com G3 aprovado e **nunca faz merge** — o merge é sempre do revisor humano
  (ADR-011). Demanda "pronta" = PR aberto para revisão; "entregue" = PR integrado.
- Commits pequenos, em português, um por passo do protocolo (contrato, implementação, testes, parecer).
- O `--demand <id>` de cada evento do log liga demanda → branch → PR → release (rastreabilidade).

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
- Subagentes não fazem `git push` nem merge. O Orquestrador abre os PRs via `tools/squad/gitflow.py`;
  **quem integra (merge) é sempre o revisor humano** (ADR-011).
- Nenhum agente altera credenciais ou remove dados fora do seu diretório.
- Mudança de contrato de evento/API → exige ADR do Arquiteto.
- Gate com confiança < 70% ou risco "alto" → intervenção humana **obrigatória**; caso contrário é opcional.
- Máximo de 2 ciclos de autocorreção por gate; no 3º, escala para o humano.
- **Produtivo inquebrável** (ADR-018): nenhum agente roda `docker compose` sem `-p <projeto>` explícito. O produtivo
  (`checkout-saga`, cópia principal em `develop`) só é alterado por `tools/squad/prod.py` (atualização incremental
  após o merge, sem `down`/`-v`/`prune`/`--remove-orphans`/`--force-recreate`); o ambiente de teste (`checkout-teste`,
  portas = produtivo + 10 000) só por `tools/squad/testenv.py`, e só por pedido do humano (`test-env-request`).
  Agentes nunca gravam `test-env-request` nem apagam dados do teste; para verificar isolamento usam
  `testenv.py prod-fingerprint` (só leitura).
- **Publicação do Squad Control** (ADR-025): o supervisor `tools/squad/publisher.py` é o único processo autorizado a
  avançar a `develop` da cópia principal fora do `gitflow.py`, e só por avanço simples (fast-forward), com HEAD em
  `develop` e nenhuma operação git em andamento. O botão "Publicar Squad Control" e o evento `squad-publish-requested`
  são só do humano: nenhum agente os usa.

## Convenções de código
- Mensagens de commit e documentação em português; identificadores em inglês.
- Todo consumidor de evento é idempotente (tabela `processed_messages`); todo produtor usa outbox.
- Todo log carrega `orderId`/`sagaId` via MDC; o `trace_id` vem do OpenTelemetry.

## Execução independente de fornecedor
- Definições de papel: `.claude/agents/<papel>.md` — o **corpo** é o prompt do papel para qualquer fornecedor; o
  cabeçalho (frontmatter) só é usado pelo Claude Code. O Orquestrador está em `docs/squad/orquestrador.md`.
- Delegação: use a ferramenta nativa de subagentes do seu runner, se existir; caso contrário,
  `python3 tools/squad/run_agent.py <papel> "<tarefa>" [--demand <id>]` (runner em `SQUAD_RUNNER=claude|codex`).
- Progresso: registre marcos com `python3 tools/squad/log.py --agent <papel> --type progress --title "..."` para
  que o Squad Control mostre o trabalho ao vivo, qualquer que seja o fornecedor.
- Plantão do Orquestrador: `tools/squad/plantao.sh` (prompt em `docs/squad/prompts/plantao.md`).
