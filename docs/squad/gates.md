# Gates de qualidade (avaliados pelo Auditor)

Peso entre parênteses. **B** = bloqueante (falhou → `RETURN`).

## G1 · Arquitetura → Implementação
- (B, 3) Todos os 6 eventos obrigatórios modelados com tópico, chave e payload exato — `docs/contracts/events.md`.
- (B, 3) Máquina de estados da Saga com compensação para cada passo — `docs/architecture/saga.md`.
- (B, 2) Os 4 cenários de falha obrigatórios com mecanismo de continuidade e compensações.
- (2) Idempotência, retries, timeouts e rastreabilidade descritos.
- (1) ADRs para Saga orquestrada, outbox, database-per-service, broker.
- (1) Resposta à pergunta de evolução (seção 12).
- (B, 3) **Demanda de bug** (D16, ADR-019): teste falha antes da correção — existe o commit do teste que reproduz o
  bug (evento `evidence reproducao=FAIL` do QA) **antes** de qualquer commit de correção; no commit do teste ele falha
  pelo motivo do bug. Verificação sem trocar a branch: `git worktree add /tmp/g1-<id> <commit do teste>` e rodar o
  teste lá. Sem isso → `RETURN`. Não se aplica a demandas comuns.

## G2 · Backend (+ DevOps + Observabilidade) ou Frontend → QA
- Para entregas de **Frontend** (`checkout-console/`): (B, 3) página servida pelo container e fluxo de pedido funcionando contra o ambiente real; (B, 2) nenhuma chamada fora de `docs/contracts/api.md`; (2) acessibilidade básica (rótulos, foco, contraste) e responsividade; (1) aderência ao brief de UX do Arquiteto.

- (B, 3) `mvn -q package -DskipTests` passa; testes unitários da Saga passam.
- (B, 2) `docker compose config -q` válido; todos os serviços com healthcheck.
- (B, 2) Código aderente ao contrato (nomes de tópicos/campos iguais aos de `docs/contracts/events.md`).
- (2) Outbox + `processed_messages` presentes em todos os serviços que publicam/consomem.
- (1) Métricas de negócio da Saga expostas com os nomes definidos pela Observabilidade.
- (1) Pontos de injeção de falha implementados.

## G3 · QA → Release
- (B, 3) Suíte e2e verde para os 7 cenários de `.claude/agents/qa.md`.
- (B, 2) Matriz de rastreabilidade `tests/TRACEABILITY.md` cobre todos os requisitos.
- (2) Trace ponta a ponta visível no Jaeger para um pedido.
- (1) README explica como reproduzir cada falha.
- (B, 3) **Demanda de bug** (D16, ADR-019): teste falha antes da correção — `git log --reverse` da branch mostra o
  commit do teste antes do commit de correção; o teste **falha** no commit dele (rodado num `git worktree`
  temporário, sem trocar a branch) e **passa** no *head*. Sem isso → `RETURN`. Não se aplica a demandas comuns.

## Cálculo de confiança
`confiança = Σ pesos cumpridos com evidência / Σ pesos`. Critérios "validar" (evidência parcial) contam 50%.
