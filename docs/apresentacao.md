# Roteiro da apresentação: a história do Checkout Saga (~25 min)

> Como usar: cada **ato** tem a fala principal, **o que mostrar na tela** e a frase de transição para o próximo.
> No fim há um **guia de bolso** ("onde está cada coisa") e as **perguntas prováveis** com a resposta curta.

## Preparação (5 min antes)
```bash
docker compose up -d --build && docker compose ps     # tudo healthy
make squad                                             # Squad Control em http://localhost:7070
```
Abas abertas, nesta ordem: **Squad Control** (7070) · **Console de Checkout** (8090) · **Jaeger** (16686) ·
**Grafana** (3000) · **GitHub** (Issues/Project) · **editor** com o repositório · **terminal**.

---

## Ato 1. O pedido (2 min): "precisamos de um checkout que não perca dinheiro"
**Fala:** Um e-commerce com quatro domínios (Pedido, Estoque, Pagamento, Envio). O problema não é o caminho feliz,
é o que acontece quando algo falha no meio: pagamento recusado, envio que dá erro, serviço que não responde,
coordenador que cai. E havia uma segunda exigência: quem constrói não sou eu sozinho, é uma **squad de agentes de
IA** que precisa ser autônoma, controlada e auditável.

**Mostrar:** `docs/desafio.md` (o desafio original versionado no repositório).

**Transição:** "Comecei pelas regras do jogo, antes de qualquer linha de código."

## Ato 2. As regras do jogo (3 min): a constituição da squad
**Fala:** Antes de delegar, escrevi uma constituição válida para qualquer fornecedor de IA:
- **Single-writer:** cada diretório tem um único dono, o que evita decisões conflitantes.
- **Hierarquia de verdade:** desafio > ADR/contrato > código. Se o código diverge do contrato, o código está errado.
- **Limites de autonomia:** subagente não faz push nem merge; mudança de contrato exige ADR.
- **Gates G1, G2 e G3 com um Auditor independente:** confiança abaixo de 70%, risco alto ou 3º ciclo exigem humano.

**Mostrar:**
- `AGENTS.md`: a constituição. O `CLAUDE.md` só a importa, e Codex, Copilot e Devin leem `AGENTS.md` nativamente.
- `docs/squad/gates.md`: o que cada gate cobra.

**Transição:** "Com as regras definidas, montei o time."

## Ato 3. O time (3 min): quem é quem
**Fala:** Seis papéis exigidos pelo desafio, mais dois extras justificados:
- o **Auditor**, gatekeeper somente leitura que avalia cada passagem;
- o **Frontend**, que entrou quando surgiu demanda de interface.

Cada agente é um arquivo Markdown com prompt, objetivo, responsabilidades, entradas, saídas, ferramentas, regras de
decisão e interação.

**Mostrar:**
- `.claude/agents/arquiteto.md` como exemplo completo;
- `docs/squad/orquestrador.md` com o prompt do Orquestrador e o fluxo;
- Squad Control, área **Agentes**: um quadrinho por agente com o feed real de ações.

**Transição:** "Mas como esses agentes conversam, se não falam entre si?"

## Ato 4. Como eles conversam (3 min): o quadro-negro
**Fala:** Os agentes nunca falam diretamente entre si. Usam o padrão *blackboard*: leem e escrevem artefatos no
repositório. A memória tem três camadas:
- **longo prazo:** ADRs e contratos;
- **passagem de bastão:** handoffs de até 40 linhas;
- **episódica:** um log append-only com cada tarefa, decisão, gate e intervenção humana.

Por isso o modelo independe de fornecedor: quem ocupar um papel só precisa ler e escrever os mesmos arquivos.

**Mostrar:**
- `docs/squad/memory/decisions.jsonl` (115 eventos);
- `docs/squad/memory/handoffs/` (8 briefs);
- Squad Control, área **Decisões**: o mesmo log em tabela.

**Transição:** "Vamos ver isso funcionando com uma demanda real."

## Ato 5. Uma demanda do começo ao fim (4 min): a D1
**Fala:** Registrei pela tela "Listar os pedidos de um cliente". A demanda percorreu:
Arquiteto (contrato + ADR-006) → Auditor G1 (89%) → Backend e QA em paralelo → e2e 8/8 → Auditor G2 e G3 → merge em
`develop` via Git Flow. O merge só é liberado com G3 aprovado.

**Mostrar, nesta ordem:**
1. Squad Control, **Demandas**: a D1 com status e trilha.
2. Squad Control, **Evidências**: o parecer `G1-D1.json` com confiança, evidências e riscos.
3. `docs/contracts/api.md` e `docs/adr/006-consulta-de-pedidos-por-cliente.md`: o contrato veio antes do código.
4. GitHub: a mesma trilha como issues e comentários (espelhada por `make github-sync`).

**Frase de efeito:** "Quem executa é a sessão do Orquestrador no Claude Code; o painel é o cockpit do humano."

**Transição:** "E quando dá errado?"

## Ato 6. Quando dá errado (4 min): a squad se corrige
**Caso 1: o defeito do reinício (autocorreção).**
- A 1ª execução integrada deu 6/7: o reinício do coordenador terminou em CANCELED.
- Diagnóstico: depois de um SIGKILL, o Kafka só reatribui as partições após o `session.timeout` (45 s). Nesse
  intervalo os prazos da Saga (5 s) venceram e ela compensou.
- **A compensação estava correta; o erro era cobrar timeout pela queda do próprio coordenador.**
- QA registrou `defect` → Backend corrigiu (static membership + carência de prazos no startup) → 7/7 → Auditor aprovou G2.

**Caso 2: o Auditor devolve e o humano decide (D2, "Melhorar o visual do checkout").**
- G3 **devolvido com 65%**: um comentário editado numa migração Flyway já aplicada mudaria o checksum no próximo rebuild.
- Como a confiança ficou abaixo de 70%, a intervenção humana era obrigatória. Decidi **na tela** (aceitar devolução).
- Correção feita, rebuild e e2e 8/8, G3 aprovado com 100% no 2º ciclo.

**Mostrar:** `docs/squad/gates/G3-D2.json` e `G3-D2-2.json`; os eventos `defect` e `human` na área **Decisões**.

**Transição:** "Agora o produto que essa squad construiu."

## Ato 7. O produto funcionando (5 min): a Saga ao vivo
1. **Console de Checkout** (8090): pedido físico sem falha, e a Saga andando ao vivo até CONFIRMED.
2. Mesmo console com "Pagamento recusado": estoque liberado, pedido CANCELED com motivo.
3. Terminal:
   ```bash
   bash tests/e2e/run.sh shipping_failure        # estorno + liberação → CANCELED
   bash tests/e2e/run.sh coordinator_restart     # kill -9 no orquestrador no meio → CONFIRMED
   ```
4. `GET /orders/{id}`: histórico de etapas e compensações.
5. **Jaeger:** um único trace atravessando HTTP → outbox → Kafka → 4 serviços (`traceparent` gravado no outbox).
6. **Grafana "Checkout Saga":** sagas por desfecho, compensações por passo, timeouts.

**Frase de efeito:** "Nenhum cenário perde dinheiro: ou confirma, ou desfaz tudo em ordem reversa."

## Ato 8. E daqui para frente (2 min)
**Pergunta da seção 12** (`docs/architecture/README.md` §6): a solução já nasce distribuída. Para produção faltam:
- Postgres por serviço em instâncias separadas;
- Kafka com RF=3 e schema registry;
- descoberta de serviços via Kubernetes e HPA por lag;
- DLQ com reprocessamento e limpeza do outbox.

**Honestidade que conta ponto:** diga o que você mesmo mapeou como próximo passo:
- MCP server da squad;
- execução real com Copilot/Devin;
- testes de integração com Testcontainers;
- e2e de timeout em todas as etapas.

São as próximas demandas, e a própria squad vai executá-las pelo mesmo protocolo.

---

## Guia de bolso: onde está cada coisa

### Squad (a fábrica)
| Pergunta | Onde ver na tela (Squad Control :7070) | Onde está no repositório |
|---|---|---|
| Onde vejo as demandas? | Aba **Demandas** (registrar, iniciar, pausar, repriorizar) | Eventos `task` do humano em `docs/squad/memory/decisions.jsonl`; fila `docs/squad/inbox/`; issues no GitHub |
| Onde está o histórico? | Aba **Decisões** (log completo) e o sino de notificações | `docs/squad/memory/decisions.jsonl` (append-only, via `tools/squad/log.py`); `git log` |
| Onde estão as regras de cada agente (os MDs)? | Aba **Agentes** (feed ao vivo) | `.claude/agents/<papel>.md` (prompt + regras); Orquestrador em `docs/squad/orquestrador.md` |
| Onde estão as regras comuns da squad? | Aba **Políticas** | `AGENTS.md` (constituição); `CLAUDE.md` só importa |
| Onde estão os gates e os pareceres? | Aba **Execuções** (recomendação atual) e aba **Evidências** | Regras em `docs/squad/gates.md`; pareceres em `docs/squad/gates/*.json` (13) |
| Como o contexto passa de um agente a outro? | Aba **Evidências** → Handoffs | `docs/squad/memory/handoffs/*.md` (8) |
| O que cada agente fez de fato? | Aba **Agentes** | Transcrições do Claude Code (`~/.claude/projects/…`) e `.squad/runs/` para outros fornecedores |
| Onde o humano intervém? | Botões de **Intervenção humana** (Execuções) e controles em **Demandas** | Eventos `human`/`control` em `decisions.jsonl` |
| Como roda em outro fornecedor? | Card do agente marcado com o runner | `docs/squad/portabilidade.md`; `tools/squad/run_agent.py` |
| Como é o fluxo de branches? | — | `docs/squad/git-flow.md`; `tools/squad/gitflow.py` (bloqueia merge sem G3) |

### Produto (o checkout)
| Pergunta | Onde |
|---|---|
| Contratos de eventos e de API | `docs/contracts/events.md`, `docs/contracts/api.md` |
| Decisões de arquitetura | `docs/adr/001` a `007` |
| Máquina de estados e compensações | `docs/architecture/saga.md` (§1 estados, §5 falhas) |
| Três visões (negócio, técnica, agêntica) | `docs/architecture/README.md` §1 a §3 |
| Rastreabilidade requisito → teste | `tests/TRACEABILITY.md`; `tests/e2e/scenarios.md`; `tests/e2e/last-report.json` |
| Código da Saga | `services/saga-orchestrator/.../SagaStateMachine.java` |

### De onde o Squad Control lê (se perguntarem "tem banco?")
Não tem banco. `tools/squad/server.py` (Python, só stdlib) lê arquivos a cada 3 s:
- `decisions.jsonl` alimenta Demandas, Decisões, linha do tempo e notificações;
- `gates/*.json` alimenta a recomendação e Evidências;
- `handoffs/*.md` alimenta a lista de handoffs;
- as transcrições do Claude Code alimentam Agentes;
- `project.json` alimenta os links e a área Observabilidade (Grafana e Jaeger embutidos).

---

## Perguntas prováveis
| Pergunta | Resposta curta | Onde |
|---|---|---|
| Por que orquestração e não coreografia? | Fluxo e compensações num lugar só; sem acoplamento temporal escondido | ADR-001 |
| E se a compensação falhar? | Retry infinito com backoff + alerta `COMPENSATION_STUCK`; nunca desiste | saga.md §5.3 |
| Timeout ambíguo (pagou tarde)? | Retry com o mesmo `messageId`; refund idempotente; refund sem autorização = no-op registrado (tombstone) | saga.md §5.1 |
| Exactly-once? | At-least-once + idempotência (outbox + `processed_messages` + mesmo `messageId`) | ADR-002, ADR-005 |
| O que acontece se o coordenador cair? | Estado e prazos no Postgres; offset só após o commit; retoma de onde parou | saga.md §5; cenário `coordinator_restart` |
| Como os agentes não se contradizem? | Single-writer + contrato antes do código + Auditor compara código × contrato | `AGENTS.md` |
| Como o humano controla a squad? | Gates do Auditor; humano obrigatório com confiança < 70%, risco alto ou 3º ciclo | `docs/squad/gates.md` |
| Funciona com outro fornecedor? | Sim: regras em `AGENTS.md`, runner genérico; o Auditor já rodou no Codex. Copilot e Devin estão com o protocolo pronto, falta executar | `docs/squad/portabilidade.md` |
| Usaram MCP? | Ainda não. A memória é por arquivos (portável entre fornecedores); expô-la via MCP server é a próxima demanda | este roteiro, Ato 8 |
| A squad é realmente autônoma? | Autônoma dentro de limites: executa sozinha entre gates; o humano entra por regra, não por acaso | `AGENTS.md` (limites de autonomia) |
