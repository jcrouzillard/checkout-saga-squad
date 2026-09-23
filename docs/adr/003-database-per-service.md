# ADR-003: Database por serviço (uma instância Postgres, cinco databases)

**Status**: Aceito (2026-09-23, Arquiteto) — refina ADR-000.

## Contexto
Cada contexto deve ser autônomo e a consistência entre eles deve vir da Saga (seção 13: "modelo de persistência",
"estratégia de consistência"). O ambiente local precisa subir com um único `docker compose up`.

## Decisão
- Um database por serviço: `saga`, `orders`, `inventory`, `payments`, `shipping`, cada um com usuário próprio e
  acesso apenas ao seu database. Esquema versionado por Flyway dentro de cada serviço.
- Uma única **instância** Postgres no compose (economia de recursos local); nenhuma consulta entre databases.
- Todos os serviços têm as tabelas `outbox` e `processed_messages` (ADR-002/005).

## Consequências
- (+) Fronteiras de dados explícitas; cada serviço pode migrar de instância sem mudança de código (só `SPRING_DATASOURCE_URL`).
- (+) Consistência eventual controlada pela Saga, com estados intermediários visíveis.
- (−) A instância única é ponto único de falha local (aceitável no desafio; em produção, instâncias separadas — README §6).
- (−) Consultas agregadas exigem composição via APIs/eventos.

## Alternativas consideradas
- **Banco compartilhado com schemas**: facilita joins, mas convida ao acoplamento e contradiz a Saga.
- **Uma instância Postgres por serviço no compose**: mais fiel à produção, porém 5× memória no ambiente local.
