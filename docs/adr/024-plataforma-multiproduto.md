# ADR-024: Plataforma da squad separada do produto — cadastro por produto, memória fora do repositório e painel multiproduto

**Status**: Proposto (2026-09-25, Arquiteto — D22 `b26da7851764`, fase 1). G1 ciclo 1: APPROVE com ressalvas
(`docs/squad/gates/G1-D22.json`, 0,75); ressalvas aplicadas nesta revisão, sem novo ciclo (§10). Aguarda decisão humana (§9).
**Q2 e Q3 respondidas** pelo humano na D23 (`6450aecde7f9`, F2a) — ver §11; errata da F2a no §11.
**Numeração**: 023 está com a D21 (`feature/D21-imagem-no-chat`, "imagens na conversa"); este é o próximo livre.
**Anexo (mapa completo, 74 pontos)**: [`docs/contracts/plataforma-multiproduto-mapa.md`](../contracts/plataforma-multiproduto-mapa.md).
**Afeta**: ADR-011 (sem mudança de regra), ADR-015, ADR-017, ADR-018, ADR-019, ADR-020 e ADR-023 (sem mudança de
regra: conversas e anexos continuam fora do git, §4.3), ADR-021, ADR-022 — mecanismos mantidos, valores e caminhos passam a vir do cadastro do produto; cada fase que mudar um deles cita este ADR.
**Revisão D25 (`233278d0cfa9`)**: §4.1, §4.3, §4.4.2, §4.12 (parte da Q4), §4.13 (parte da F3), as linhas F3/F4 do §6 e o item "banco de dados para a memória" do §8 são **substituídos** pelo [ADR-026](026-sentido-da-separacao-e-memoria-no-neon.md) (proposto): o produto sai do repositório, a memória vai para o Postgres (Neon) com cache local e a entrega usa uma exportação congelada. Os riscos novos estão no ADR-026 §7. As Q1 e Q4 do §9 passam a ser as Q-A1 e Q-B2 do ADR-026.

## 1. Contexto

O humano quer (D22): (1) Squad Control e ferramentas da squad num sistema à parte, independente de produto;
(2) produto cadastrado por configuração (repositório, branches, donos de diretório, build e testes, ambiente de teste,
produtivo, onde ficam ADRs e contratos); (3) memória da squad (log, gates, handoffs, conversas) fora do repositório do
produto, separada por produto; (4) painel com vários produtos, com demandas, alertas e ambientes separados;
(5) o checkout migrado como primeiro produto **sem perder o histórico D1–D21 e sem parar a squad**.
Esta fase entrega só a decisão, o mapa e o plano; cada fase seguinte vira demanda própria.

Fatos verificados no código e na memória viva (2026-09-25):
- **Tudo mora no repo do produto.** 10 ferramentas calculam `ROOT = Path(__file__).parents[2]` e tratam essa raiz
  ao mesmo tempo como "onde está a squad", "onde está o produto" e "onde está a memória" (mapa A1–A2).
- **A memória é versionada no produto e o suja o tempo todo.** `gitflow.py` tem uma maquinaria inteira só para
  isso — `STATE`, `snapshot_state` (os commits "Sincronização da memória da squad"), `import_memory`,
  `align_memory`, `discard_state` e o tratamento de `STATE` em `feature_sync`/`review_update` —, mais o critério G3
  "memória fora do PR", a tolerância a `docs/squad/**` sujo no `prod.py` e o estado "sujo" do ADR-021 (mapa B12).
  Os pareceres do Auditor (`docs/squad/gates/*.json`) **entram no PR** da feature (ex.: `G1-D21.json` em `428e06c`).
- **Costura parcial já existe.** `SQUAD_ROOT_DATA`/`SQUAD_LOG` separam dados do código em `server.py`, `testenv.py`,
  `pending.py`, `log.py`, `run_agent.py` (criada para testes), mas `gitflow.py`, `github_sync.py` e `triage.py`
  **ignoram** `SQUAD_LOG` (B1). `BugStore` já é uma interface (B5). `docs/squad/project.json` já é um cadastro
  embrionário com `products[]` e `current` (C10).
- **Os códigos de demanda são posicionais e já divergiram.** `D{n}` = n-ésimo `task` do humano no log, recalculado em
  6 lugares (B14). Os contratos citam `349e5b1bf818`=D8, `e31bdfb73679`=D7, `174084ec85d0`=D9, `f2324e0f25de`=D10;
  o cálculo de hoje dá D7, D8, D10, D9. Separar ou reordenar logs sem congelar os códigos quebraria mais referências.
- **O histórico é quase todo da fábrica.** Das 22 demandas, só D1, D2, D6 e D9 (pelo cálculo atual) são
  `produto`; as outras 18 mudaram o Squad Control, o protocolo ou as ferramentas. O log tem 619 eventos
  (2026-09-23 → 2026-09-25), 73 gates, 108 handoffs, 49 eventos com PR (14 PRs), 173 issues espelhadas.
- **Valores do checkout estão fixos no código**: repositório `jcrouzillard/checkout-saga-squad` (4 lugares), Project
  nº 1, `develop`/`main`, projetos Compose `checkout-saga`/`checkout-teste`, lista de serviços, regras caminho→serviço
  do `prod.py`, portas (em Python, no HTML e no `teste.env`), `mvn`/`pom.xml`, `plankton-dNN`/`plankton-teste`,
  chaves de PII de pedido (C1–C15).
- **Papéis e políticas misturam fábrica e produto**: `AGENTS.md`, `.claude/agents/*.md`, `orquestrador.md` e
  `gates.md` contêm regras genéricas e, no mesmo texto, Saga, Maven, `saga_*`, `checkout-console` (D1–D7).
- A squad está trabalhando: há worktrees `plankton-d12`, `-d21`, `-d22`, `plankton-teste`, o plantão e o servidor na
  cópia principal (`develop`, porta 7070). A migração não pode exigir parar tudo.

## 2. Decisão (resumo)

1. **Repositório novo `squad-platform`** (não monorepo): contém o código da squad, o Squad Control, papéis e prompts
   genéricos, políticas-base, os ADRs da fábrica e o **registro de produtos**. É instalado **uma vez por host**
   (clone em `$SQUAD_PLATFORM`, padrão `~/squad-platform`) e aponta para os produtos; o produto **não** carrega cópia,
   submódulo nem pacote da plataforma.
2. **Cadastro de produto em TOML no repositório da plataforma**: `products/<id>/product.toml`, lido com `tomllib`
   (stdlib, só leitura; a plataforma nunca o reescreve — mudança = PR revisado pelo humano).
3. **Memória fora de qualquer repositório de produto**, em `$SQUAD_HOME/products/<id>/memory/` (padrão
   `~/.squad`), que é **um repositório git próprio por produto** (commit automático, remoto privado opcional);
   estado de execução não versionado em `$SQUAD_HOME/products/<id>/runtime/`.
4. **Histórico D1–D21 migrado inteiro e congelado** para a memória do `checkout-saga`, com a história git do log
   preservada, códigos de demanda congelados por id e um evento `migration` de ponta a ponta verificável.
5. **Regras em duas camadas**: constituição, papéis-base, prompts e gates-base na plataforma; `AGENTS.md`,
   especialização dos papéis e critérios de gate no produto. O cadastro liga as duas.
6. **A plataforma é o segundo produto de si mesma** (`squad-platform`): demandas de tipo `operacao` passam a ser
   demandas desse produto, com repositório, gates e memória próprios.
7. **Migração em fases pequenas, cada uma reversível**, com o `checkout-saga` como produto padrão implícito durante
   toda a transição: nenhuma fase muda comportamento para quem não passa `--product`.

## 3. Arquitetura alvo

```
squad-platform/                      (novo repo; dono: Orquestrador; squad-control/: Frontend)
  squad/                             pacote stdlib: log, gitflow, server, conversa, testenv, prod, bugs, alerts, …
  squad-control/                     painel (um servidor por host, N produtos)
  roles/<papel>.md                   papéis-base genéricos (sem domínio)
  prompts/{plantao,delegacao,conversa,triagem}.md   com placeholders do cadastro
  policies/constitution.md           regras da fábrica (hoje metade do AGENTS.md)
  policies/gates-base.md             estrutura dos gates, pesos, confiança, autocorreção
  products/<id>/product.toml         CADASTRO (revisado por PR)
  docs/adr/  docs/contracts/         ADRs/contratos da fábrica (números preservados: 008, 009, 011, 012, 014–024)
  tests/                             tests/squad + tests/ui do Squad Control; CI própria

$SQUAD_HOME/ (~/.squad)              fora de qualquer repo de produto
  products/<id>/memory/   (git)      log/decisions.jsonl, gates/, handoffs/, inbox/, bugs/{produto,operacao}/,
                                     github-sync.json, codes.json, MIGRATION.md
  products/<id>/runtime/  (sem git)  conversas/<id>.jsonl + conversas/<id>/anexos/ (ADR-020/023), conversas/.sessao,
                                     runs/, locks/, pr-state.json, bug-drafts/, bug-pseudonym.key, logs
  usage/                             consumo da IA do host (global)

<produto>/ (ex.: checkout-saga-squad)
  AGENTS.md                          bloco GERADO com a constituição (§4.5) + regras do produto (ADR-000, topologia, convenções)
  CLAUDE.md                          importa AGENTS.md e a constituição (caminho resolvido pela plataforma)
  squad/roles/<papel>.md             especialização de cada papel para este produto
  squad/gates.md                     critérios de gate do produto
  .claude/agents/*.md                GERADOS (base + especialização) para subagentes nativos do Claude Code
  docs/adr, docs/contracts, …        conhecimento do produto (onde, diz o cadastro)
```

Esboço do cadastro (campos definitivos no contrato da F2):

```toml
[product]
id = "checkout-saga"
name = "Checkout Saga"
mission = "Checkout distribuído com Saga orquestrada"   # entra no prompt do Orquestrador
code_prefix = "D"                                        # D23, D24, … (ver §9, Q2)

[repo]
path = "~/orca/workspaces/Desafio Itau/plankton"         # cópia principal (produtivo sai daqui)
worktree_pattern = "{main}-{code}"                       # plankton-d23
[git]
integration = "develop"
stable = "main"
prefixes = { feature = "feature/", release = "release/", hotfix = "hotfix/" }
[github]
repo = "jcrouzillard/checkout-saga-squad"
project = 1
visibility = "public"

[docs]
requirements = "docs/desafio.md"
adr = "docs/adr"
contracts = "docs/contracts"
architecture = "docs/architecture"
[policies]
agents = "AGENTS.md"
gates = "squad/gates.md"
roles_dir = "squad/roles"

[owners]                                                 # substitui OWNERS do gitflow.py e a tabela do AGENTS.md
qa = ["services/*/src/test/**", "tests/**"]
backend = ["services/**", "pom.xml"]
devops = ["Dockerfile", "docker-compose.yml", "infra/**", ".github/**", "Makefile"]
observabilidade = ["infra/observability/**", "docs/observability.md"]
frontend = ["checkout-console/**"]
arquiteto = ["docs/architecture/**", "docs/adr/**", "docs/contracts/**"]

[build]
package = "mvn -q -B package -DskipTests"
unit_test = "mvn -q -B test"
e2e_test = "bash tests/e2e/run.sh"
version_get = { file = "pom.xml", xpath = "version" }
version_set = "mvn -q -B versions:set -DnewVersion={version} -DgenerateBackupPoms=false"
changelog = "CHANGELOG.md"

[env.prod]
enabled = true
kind = "compose"                                         # "compose" (prod.py) | "process" (ver abaixo) | "none"
compose_project = "checkout-saga"
env_file = ".env"
services = ["saga-orchestrator", "order-service", "inventory-service", "payment-service", "shipping-service"]
ports = { saga = 8080, order = 8081, inventory = 8082, payment = 8083, shipping = 8084, console = 8090, postgres = 5432, kafka = 29092, jaeger = 16686, prometheus = 9090, grafana = 3001 }
deploy_rules = [ { path = "services/{module}/**", rebuild = ["{module}"] }, { path = "services/common/**", rebuild = "all" },
                 { path = "checkout-console/nginx.conf", restart = ["checkout-console"] } ]   # etc. (hoje prod.py:77-95)
[env.test]
enabled = true
compose_project = "checkout-teste"
env_file = "infra/teste/teste.env"
port_offset = 10000
worktree = "{main_parent}/plankton-teste"
smoke = ["saga", "order", "inventory", "payment", "shipping", "console"]

[observability]
jaeger = "http://localhost:16686"
grafana = "http://localhost:{ports.grafana}/d/checkout-saga?kiosk&refresh=5s"
prometheus = "http://localhost:9090"
[evidence]
pii_keys = ["shippingAddress", "billingAddress", "zipCode", "cep", "recipient", "customerName"]
pseudonymize = ["customerId"]
correlation_keys = { orderId = ["orderId", "order.id", "order_id", "app.order.id"], sagaId = ["sagaId", "saga.id", "saga_id", "app.saga.id"] }
[[links]]
label = "Console de Checkout"
url = "http://localhost:8090"
[memory]
link_base = ""                                           # vazio = memória só local (Q4); senão URL do repo de memória
```

O produtivo da **plataforma** não é Compose: é o servidor Python na porta 7070 servido da cópia principal. O cadastro
do `squad-platform` usa `kind = "process"`:

```toml
[env.prod]                                               # products/squad-platform/product.toml
enabled = true
kind = "process"
command = "python3 squad-control/server.py"              # cwd = repo.path (cópia principal da plataforma)
ports = { control = 7070 }
health = "http://localhost:7070/api/instance"
update = "restart"                                       # após merge: git pull --ff-only + reinício do processo
[env.test]
enabled = false                                          # teste da plataforma = tests/squad + tests/ui (servidor efêmero em porta livre)
```

`prod.py` só age sobre `kind = "compose"`; `kind = "process"` tem um atualizador próprio (mesmas guardas do ADR-018:
só a cópia principal, só `--ff-only`, sem apagar estado, trava em `run:locks/`, reinício só com health verde antes e
depois — senão volta ao SHA anterior). O registro de portas (§4.7) inclui as portas `process`.

## 4. Decisões detalhadas, com alternativas

### 4.1 Repositório da plataforma e distribuição — *substituída pelo ADR-026 §3 (sentido B)*
**Decisão**: repositório novo `jcrouzillard/squad-platform`, extraído com `git filter-repo` dos caminhos da fábrica
(`tools/squad`, `squad-control`, `tests/squad`, `tests/ui` do Squad Control, `docs/squad` sem a memória, ADRs e
contratos da fábrica), **preservando a história git e os SHAs de origem** numa tabela `docs/MIGRATION-SHAS.md`.
A plataforma roda de uma cópia no host (`$SQUAD_PLATFORM`) e recebe o produto por `--product`/`SQUAD_PRODUCT`.
A extração usa `git filter-repo` (ver §4.13: pré-requisito do host, não dependência da plataforma).
Durante um release, o produto mantém **calços** `tools/squad/<x>.py` que só fazem `exec` na plataforma (prompts,
worktrees e hábitos antigos seguem funcionando); depois são removidos.

| Alternativa | Por que não |
|---|---|
| Monorepo com pasta `platform/` no repo do checkout | não atende "sistema à parte, independente de produto"; um segundo produto dependeria do repo do checkout |
| Submódulo git da plataforma em cada produto | cada produto fixaria uma versão diferente do painel que é **um só** por host; atualizações exigiriam PR em todo produto |
| Pacote pip publicado | a plataforma é stdlib e muda várias vezes por dia; publicar/versionar pacote é custo sem ganho agora (fica como evolução) |
| Copiar (vendorizar) as ferramentas no produto | é o acoplamento de hoje com outro nome |

### 4.2 Formato e local do cadastro
**Decisão**: `products/<id>/product.toml` no repositório **da plataforma**. TOML porque a plataforma é só stdlib
(`tomllib` lê; YAML exigiria dependência) e porque o cadastro é editado por humano e precisa de comentários (JSON não
tem). O conhecimento do produto (AGENTS.md, papéis especializados, critérios de gate, ADRs) fica no produto e o
cadastro só **aponta** para ele.

| Alternativa | Por que não |
|---|---|
| Cadastro dentro do repo do produto (`squad.product.toml`) | um PR do produto poderia afrouxar as guardas do produtivo (projeto Compose, portas, `enabled`) que protegem o host; a plataforma precisaria clonar o produto para saber que ele existe; colisão de portas entre produtos não seria verificável num lugar só |
| YAML | exige PyYAML (quebra a regra "somente stdlib" de todas as ferramentas) |
| JSON (evolução do `project.json`) | sem comentários; aceitável como formato de troca — `/api/products` devolve o cadastro em JSON |
| Banco de dados | sem revisão por PR nem histórico; desproporcional para poucos produtos |

### 4.3 Onde fica a memória — *substituída pelo ADR-026 §4 (Neon com cache local)*
**Decisão**: um repositório git **local por produto** em `$SQUAD_HOME/products/<id>/memory/`, com commit automático
a cada gravação agrupada (mesma cadência de hoje) e remoto privado opcional (`<produto>-squad-memory`). O que não
precisa de auditoria (runs, travas, rascunhos, sessões, chave de pseudônimo) vai para `runtime/`, fora do git.
**Conversas e anexos ficam fora do git** (ADR-020 §5 e alternativa G; ADR-023): `run:conversas/<id>.jsonl`,
`run:conversas/<id>/anexos/<sha256>.<ext>` e `run:conversas/.sessao/`, exatamente como hoje em `.squad/conversas/`,
só que por produto. Não há mudança no ADR-020 nem no ADR-023: o que a conversa decide e que precisa de auditoria já
entra no log por evento (`task`, `human-intervention`, delegação) — esse sim vai para o git da memória. A versão
anterior deste ADR punha `conversas/` em `mem:`; foi corrigida (ressalva 1 do G1-D22).
Consequências: fim dos commits de memória no produto, de `STATE`/`align_memory`/`discard_state`, do critério G3
"memória fora do PR" e do estado "sujo" permanente; gates deixam de entrar nos PRs (o corpo do PR passa a linkar o
parecer). O ADR-019 (evidências mascaradas "no git") continua valendo: no git da memória.

| Alternativa | Por que não |
|---|---|
| Continuar no repo do produto, só em pasta própria | é exatamente o acoplamento que o humano quer eliminar (item 3) |
| Pasta fora do git | perde o histórico auditável e o append-only verificável que o desafio pede como evidência |
| Banco (SQLite/Postgres) | exige migrar leitores e o painel inteiro de uma vez; perde diff e revisão; fica como evolução atrás da mesma interface (`MemoryStore`) |
| Um repositório de memória único para todos os produtos | mistura produtos no mesmo histórico e nas mesmas permissões (§4.9) |

### 4.4 Migração do histórico D1–D21 com rastreabilidade
**Decisão**:
1. Congelar os códigos **antes** de mover qualquer coisa (F2): o evento `task` do humano passa a gravar `code`;
   `codes.json` fixa o legado pelo **id** (ids são a chave canônica; o código é rótulo). A tabela registra os
   códigos citados nos contratos quando diferem (`aliases`), para que "D7" em `ui-cancelar-demanda.md` continue
   resolvendo para `e31bdfb73679`.
2. Na F3, `git filter-repo` (ou o caminho alternativo de §4.13) com `--path docs/squad/memory --path docs/squad/gates --path docs/squad/inbox --path
   docs/squad/produto --path docs/squad/operacao` gera o repositório de memória **com a história git do log**; as
   linhas do log não são reescritas (append-only), só o caminho muda. `MIGRATION.md` registra origem (repo, SHA),
   contagem de linhas e o sha256 de cada arquivo.
3. Um evento `migration` é gravado no fim do log antigo **e** no começo do novo, com o mesmo id, contagem e hash —
   quem lê qualquer um dos dois sabe onde está o outro.
4. No produto, `docs/squad/memory/` e afins viram um `README.md` "movido para …" (os arquivos saem numa fase
   posterior, só com o humano de acordo; o histórico git do produto continua tendo tudo).
5. Links para PRs e issues não mudam (continuam no repo `checkout-saga-squad`); `github-sync.json` vai junto.
6. O histórico **não é dividido** entre `checkout-saga` e `squad-platform`, embora 18 das 22 demandas sejam da
   fábrica: dividir reescreveria o log, quebraria referências cruzadas (handoffs, gates, delegações citam outras
   demandas) e a numeração. O produto `squad-platform` começa com um evento `migration` apontando para o histórico
   legado, e o painel mostra esse legado nos dois produtos (somente leitura no segundo).

### 4.5 Ownership, AGENTS.md e papéis
**Decisão**: a tabela de donos passa a ser `[owners]` do cadastro (fonte única usada por `gitflow`, alertas e
Auditor); o `AGENTS.md` do produto deixa de listá-la e passa a conter só as regras do produto; as regras da fábrica
vão para `policies/constitution.md`. Cada papel = `roles/<papel>.md` (plataforma, genérico) + `squad/roles/<papel>.md`
(produto, especialização). O conjunto de papéis (orquestrador, arquiteto, backend, devops, observabilidade, frontend,
qa, auditor) é fixo na plataforma; o produto pode não usar algum (ex.: sem `observabilidade`), mas não inventa papel
sem ADR da plataforma. Para os subagentes nativos do Claude Code, o produto mantém `.claude/agents/*.md` **gerados**
pela plataforma (cabeçalho "gerado — não editar"), com verificação de sincronia no plantão.
**Como a constituição chega a Codex/Copilot/Devin**: esses runners leem só o `AGENTS.md` do diretório e **não seguem
link nem import**. Por isso o `AGENTS.md` do produto passa a ter um **bloco gerado** com o texto integral de
`plat:policies/constitution.md`, entre marcadores `<!-- squad:constituicao v<versão da plataforma> — gerado, não
editar -->` … `<!-- /squad:constituicao -->`, seguido da parte do produto (editada à mão pelo dono). O gerador
(`squad sync-policies --product <id>`) é o mesmo que gera `.claude/agents/*.md`; o plantão e o G3 verificam que o
bloco bate com a versão da plataforma em uso (bloco divergente = alerta, e o PR de atualização é do Orquestrador).
O `CLAUDE.md` continua só importando `AGENTS.md`. `run_agent` já compõe o prompt inteiro e não depende do bloco.
Alternativa rejeitada: um `AGENTS.md` só, na plataforma, com seções por produto — o produto deixaria de ser
compreensível por quem abre só o repositório dele, e Codex/Copilot/Devin leem o `AGENTS.md` **do cwd**. Rejeitado
também "link para a constituição": não chega a esses runners.

### 4.6 GitHub
Issues e Project **por produto** (`[github]` do cadastro). O `checkout-saga` mantém `jcrouzillard/checkout-saga-squad`
e o Project nº 1 com as 173 issues atuais; o `squad-platform` ganha issues e Project próprios no repo novo.
Todo `gh` passa a levar `-R <repo>` explícito (hoje parte depende do cwd). Autenticação `gh` segue sendo a do host.

### 4.7 Ambientes por produto
Mecanismo do ADR-018 (fila, trava, pedido do humano, produtivo inquebrável, nada de `down -v` sem APAGAR) vira código
genérico; projetos Compose, serviços, regras de deploy, smoke, portas e worktrees vêm de `[env.*]`. A plataforma
mantém um **registro de portas** derivado de todos os cadastros e recusa carregar um produto cujas portas (produtivo
ou teste = produtivo + `port_offset`) colidam com as de outro produto ou com a do Squad Control. As listas de portas
hoje fixas em `evidence_rules.py`, `bugs.py`, `testenv.py` e no HTML passam a ser calculadas do cadastro.
Produto sem Compose (`enabled = false`) simplesmente não mostra os cartões de ambiente.

### 4.8 Painel multiproduto
Um servidor por host. `GET /api/products` (cadastro resumido + contadores + pior alerta de cada produto);
`/api/p/<id>/state|live|demand*|test-env*|bug*|conversas*|delegacoes*|policy`; `/api/instance` e `/api/usage`
continuam globais. As rotas atuais continuam como **apelido do produto padrão** (`checkout-saga`) até um release
depois da F5. UI: seletor de produto no cabeçalho, rotas `#/p/<id>/…` (hash antigo redireciona para o padrão),
sino global agregado com etiqueta do produto, "Nova demanda" sempre dentro de um produto (o tipo `operacao` abre a
demanda no produto `squad-platform`). Conversa com o Orquestrador é **por produto** (sessão, histórico e contexto do
produto); o orçamento do `/api/live` (ADR-017: 300 ms, 64 KB) vale por produto.

### 4.9 Segurança e isolamento entre produtos
- Todo processo da squad roda com **um** produto resolvido (`SQUAD_PRODUCT`), exportado por `run_agent`; `log.py`
  recusa gravar se o log de destino não for o do produto resolvido.
- O servidor só lê/grava dentro de `products/<id>/memory|runtime` do produto da rota (validação de caminho resolvido,
  como já é feito para evidências de bug).
- A conversa (ADR-020) recebe `--add-dir` **só** da memória e do repo do produto dela; nunca de outro produto nem de
  `$SQUAD_HOME` inteiro.
- **Negação explícita dos outros produtos (runner claude)**: `--add-dir` não impede leitura fora dele; hoje
  `claude_deny_paths` nega só `.env`, `.git` e segredos do home. Passa a negar também, para **cada outro produto
  cadastrado**, `Read(//$SQUAD_HOME/products/<outro>/**)` e `Read(//<repo_path do outro>/**)` (e os worktrees dele);
  como no Claude Code negação vence permissão, a lista é "todos menos o meu", gerada do cadastro a cada sessão.
- **Runner codex: limitação declarada.** O sandbox read-only do Codex não restringe leitura (`CODEX_WARNING`,
  `readIsolation: "reduzida"`). Com dois ou mais produtos cadastrados, a conversa com codex mostra o aviso **com o nome
  dos outros produtos legíveis** e exige opção explícita do humano por produto (`chat_runner_codex_ack` no runtime);
  sem ela, o painel usa o runner claude. O mesmo vale para `run_agent` com `SQUAD_RUNNER=codex`.
- **Teste da F6 nos dois runners**: claude — ler um arquivo-sentinela de outro produto é negado; codex — a sentinela
  é legível (limitação), e o teste verifica que o aviso e a exigência de opção explícita aparecem.
- Chave de pseudônimo de evidências por produto (pseudônimos não se correlacionam entre produtos).
- O cadastro (que define guardas do produtivo) só muda por PR na plataforma, revisado pelo humano.
- Limite conhecido: `gh`, `docker` e as credenciais dos runners são do host — os produtos **não** estão isolados
  entre si contra um agente malicioso; o isolamento é contra erro, não contra adversário (§8).

### 4.10 Compatibilidade durante a transição (a squad não para)
- **Produto padrão implícito**: sem `--product`/`SQUAD_PRODUCT`, tudo resolve para `checkout-saga` com os valores de
  hoje. Cada fase entrega um **teste de equivalência**: os valores lidos do cadastro são iguais às constantes antigas.
- **Sem dual-write**: dois logs append-only escritos em paralelo divergem. A troca da memória (F3) é um **corte
  curto** num ponto seguro — plantão pausado, nenhuma run ativa, nenhum pedido de ambiente de teste em andamento —,
  com cópia, verificação (contagem, sha256, ids) e virada de `SQUAD_ROOT_DATA` + um único reinício do servidor.
  Janela esperada: minutos; o humano escolhe o momento.
- **Demandas em voo** continuam nos seus worktrees; calços em `tools/squad/` (F4) mantêm caminhos antigos válidos.
- **Flag de retorno**: `SQUAD_MEMORY_MODE=repo|external` em F3 (padrão `repo` até o corte); voltar é mudar a flag e
  reimportar, pelo id, os eventos gravados depois do corte (mesma técnica de `import_memory`).

### 4.11 Demandas em voo durante F2–F4 (D12, D21 e as que surgirem)
Hoje há branches longas abertas: `feature/D12-evidencias-na-demanda` (ADR-015, PR #104 aberto desde 23/09) e
`feature/D21-imagem-no-chat` (ADR-023). Regras:
1. **Antes de cada fase** (F2a, F2b, F3, F4) o Orquestrador lista as branches em voo no log (`progress`) e o humano
   escolhe, para cada uma: integrar antes da fase (preferido), ou continuar e absorver a fase depois.
2. **Quem absorve é a branch em voo**, nunca a fase: depois do merge da fase na `develop`, `gitflow.py feature-sync`
   traz a `develop` para a branch; conflitos são resolvidos pelo dono do arquivo na branch em voo e passam por novo G2.
3. **F3 e F4 não começam com PR aberto que toque `tools/squad/**`, `squad-control/**` ou `docs/squad/**`** — ou ele é
   integrado, ou é fechado e reaberto depois do corte a partir da nova base (o conteúdo não se perde: o commit fica
   referenciado no log). D12 e D21 caem nessa regra.
4. Pareceres, handoffs e eventos de uma demanda em voo no momento do corte da F3 são migrados como os demais (pelo id);
   o parecer que a branch tiver commitado em `docs/squad/gates/` é descartado do PR (fonte = `mem:gates/`).
5. ADR-015 (D12) entra na lista de ADRs da fábrica (§3, mapa E2); se for aceito depois da F4, nasce na plataforma.

### 4.12 Links para a memória nas issues e PRs
`github_sync.py` grava nas issues links `blob/<branch>/docs/squad/…` (log, handoffs, evidências de bug; mapa F5) e,
depois da F3, o PR citaria o parecer por link. O alvo depende da **Q4**:
- Q4 = remoto privado: `cad:memory.link_base` aponta para o repo de memória; links funcionam para quem tem acesso a ele
  (o revisor humano); issue pública passa a ter link que terceiros não abrem — aceitável, a memória é da squad.
- Q4 = só local: issue e PR citam **o id do evento e o caminho `mem:`** em texto, e o corpo do PR inclui o resumo do
  parecer (recomendação, confiança, risco, ressalvas) — o revisor não depende de link.
- Links antigos (173 issues): continuam válidos enquanto os arquivos existirem em `develop` do produto. Se **Q7** =
  apagar, o espelho reescreve uma vez esses links para `blob/<SHA do corte>/…` (permanente) antes da remoção.

### 4.13 `git filter-repo` e dependências fora da stdlib
A plataforma continua **só stdlib em tempo de execução**. `git filter-repo` é usado apenas uma vez, nas operações de
extração da F3 (memória) e F4 (repositório), como `gh` e `docker`: **ferramenta do host**, não importada. Hoje não
está instalada (`git filter-repo` → comando inexistente). Decisão: pré-requisito declarado da F3/F4
(`brew install git-filter-repo`), verificado por `squad doctor` antes do corte; se o humano preferir não instalar, o
caminho alternativo é só git: `git fast-export --all -- <caminhos>` → reescrita de caminho por script stdlib →
`git fast-import` num repo novo, com a mesma verificação (contagem, sha256, ids, `git log` do log). O critério de
aceite é o mesmo nos dois caminhos.

## 5. Consequências
- A fábrica deixa de sujar o produto: some a classe de defeitos de memória em PR/merge (a66b91c8a0d6 e afins) e o
  "sujo" permanente do selo do ADR-021.
- Um segundo produto passa a ser cadastro + `AGENTS.md` + especializações; nenhum código novo.
- Custo: 4 demandas de implementação (F2–F5) + 1 de prova (F6), mexendo em quase todas as ferramentas; o risco
  maior está em F3 (corte da memória) e F4 (extração do repo).
- Os ADRs 017–022 não mudam de regra; mudam de lugar (F4) e passam a receber valores do cadastro.
- O Frontend passa a trabalhar em dois repositórios (produto e plataforma), com PRs separados.

## 6. Plano de fases — *linhas F3 e F4 substituídas pelo ADR-026 §6 (F3a, F3b, F3c, F4 no sentido B)*

Cada fase é uma demanda (`operacao`), com branch, gates G1–G3 e PR com merge humano (ADR-011). A ordem é:
configuração antes de mover (barato e reversível) → memória (maior acoplamento) → repositório (depende das duas)
→ painel (depende do servidor já parametrizado) → segundo produto (prova).

| Fase | Entrega | Critério de aceite (verificável) | Rollback |
|---|---|---|---|
| **F1** (esta) | ADR-024 + mapa de 74 pontos | G1 aprovado; cada ponto com classe, destino e fase; perguntas §9 respondidas pelo humano | — |
| **F2a — resolvedor e códigos congelados** (bloqueada pela Q2) | `squad/product.py` (resolvedor, produto padrão implícito), `products/checkout-saga/product.toml` mínimo **ainda dentro deste repo** (`docs/squad/products/`); `code` gravado no `task` + `codes.json`/`aliases` do legado; `gitflow`/`github_sync`/`triage` honrando `SQUAD_LOG`/log resolvido; slug das transcrições calculado do `repo_path`/worktree (mapa A1, B1, B13, B14) | (a) códigos D1–D22 do painel iguais aos de hoje e `aliases` resolvem os códigos citados nos contratos; (b) teste: com `SQUAD_LOG` apontando para um log temporário, os três scripts não leem nem gravam o log real; (c) transcrições das runs aparecem no painel a partir de um worktree e de `SQUAD_ROOT_DATA` diferente; (d) `tests/squad` verde | reverter o PR (nada movido; `code` é campo a mais, ignorado pelo código antigo) |
| **F2b — valores para o cadastro** | cadastro completo (inclui `[env.prod] kind`, `correlation_keys`, `memory.link_base`) e todos os pontos F2b do mapa lendo dele; prompts com placeholders; `tests/squad` com cadastro de teste (A10) | (a) teste de equivalência: cada valor antes fixo (repo, branches, projetos, portas, serviços, regras de deploy, PII, correlação, owners, build, rótulos do teste) é igual ao do cadastro; (b) `grep` sem `checkout-saga\|checkout-teste\|jcrouzillard\|plankton` em `tools/squad/*.py`, `squad-control/index.html` e `tests/squad` fora de comentários e do cadastro de teste; (c) `tests/squad` inteiro verde; (d) plantão, `feature-start`, publicação no teste e `prod.py update --dry-run` funcionando num ciclo real | reverter o PR (nenhum arquivo foi movido; o cadastro é só lido) |
| **F3 — memória fora do repo** | `MemoryStore` (log, gates, handoffs, inbox, bugs, sync, conversas, runs, locks) com modo `repo`/`external`; `squad memory migrate --product checkout-saga` (filter-repo ou fast-export, §4.13 + verificação + evento `migration`); conversas/anexos para `run:`; links do espelho por `link_base` (§4.12); `gitflow` sem `STATE` no modo externo; `README` "movido para" no produto | (a) `migrate --verify`: mesma contagem de linhas, sha256 e conjunto de ids; (b) `git log` do `decisions.jsonl` no repo de memória mostra os commits desde 2026-09-23; (c) após o corte, um ciclo completo de demanda (start → G1 → G2 → G3 → PR) não gera nenhum commit em `docs/squad/**` no produto e o PR não contém gates; (d) painel e alertas idênticos antes/depois (snapshot de `/api/state` normalizado); (e) janela de corte ≤ 15 min, registrada no log | `SQUAD_MEMORY_MODE=repo` + reimportar por id os eventos pós-corte para o log do produto; memória externa preservada |
| **F4 — repositório da plataforma** | `squad-platform` extraído com história; constituição e papéis-base na plataforma, `AGENTS.md`/`squad/roles`/`squad/gates.md` no produto; `.claude/agents/*.md` gerados; CLI `squad`; calços `tools/squad/*.py` no produto; CI da plataforma rodando `tests/squad`; Squad Control servido da plataforma (versão = tags da plataforma) | (a) servidor, plantão e `run_agent` rodando a partir de `$SQUAD_PLATFORM` com o checkout como produto, sem nenhum arquivo da fábrica no produto além dos calços e dos gerados; (b) `git log --follow` de `server.py` na plataforma mostra a história D3–D21; (c) CI verde nos dois repositórios; (d) prompt composto de cada papel = base + especialização (teste de igualdade com os prompts de hoje, salvo o texto movido); (e) uma demanda `produto` e uma `operacao` entregues depois do corte, cada uma no seu repo | voltar os calços para as cópias originais (o produto ainda tem as ferramentas no histórico git); a plataforma extraída é descartável |
| **F5 — painel multiproduto** | `/api/products`, `/api/p/<id>/…`, seletor, rotas `#/p/<id>/…`, sino agregado, conversa por produto, `squad-platform` cadastrado como produto (demandas `operacao` vão para ele) | (a) com 2 produtos cadastrados, cada tela mostra só o produto escolhido; sino agrega com etiqueta; (b) rotas e hashes antigos continuam funcionando (produto padrão); (c) orçamento do `/api/live` do ADR-017 mantido por produto; (d) testes de UI 390/1440, claro/escuro, como nas D13–D20 | desligar o seletor (`SQUAD_MULTI=0`): o painel volta ao produto padrão, API antiga intacta |
| **F6 — segundo produto de prova** | produto sintético mínimo (`hello-squad`: 1 serviço, Compose, 1 teste) cadastrado; 1 demanda de ponta a ponta nele | (a) demanda completa (G1–G3, PR, publicação no teste, produtivo) sem tocar arquivos, memória, portas, containers nem issues do checkout (verificado por `prod-fingerprint` do checkout antes/depois e por diff da memória do checkout vazio); (b) colisão de portas proposital é recusada no carregamento; (c) conversa de um produto não lê arquivos do outro: teste de negação com runner claude e verificação do aviso/opção explícita com runner codex (§4.9) | descadastrar o produto; apagar sua memória e seus containers (só dele) |

Dependências: F2a exige a resposta da Q2; F2b exige F2a; F3 exige F2a (resolvedor e `code` congelado), a resposta
da Q4 antes do seu G1 e `git filter-repo` ou o caminho alternativo (§4.13); F2b pode correr em paralelo à F3, mas F4
exige F2b e F3; antes de F2a, F2b, F3 e F4 vale a regra das demandas em voo (§4.11); F4 exige F3 (sem memória no repo, a extração não carrega
estado vivo); F5 pode começar em paralelo a F4 na parte de API, mas só entrega com F4; F6 exige F5.

## 7. Riscos — *riscos novos (rede, Neon, segredo, sincronização, sentido B) no ADR-026 §7*

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Corte da memória (F3) perder ou duplicar eventos gravados durante a cópia | média | alto | ponto seguro + verificação por ids/sha256 + evento `migration` com hash; retorno por reimportação por id |
| Códigos de demanda mudarem na migração (já divergem hoje) | alta sem F2 | alto | congelar `code` na F2, antes de qualquer movimento; `aliases` para o legado |
| Transcrições das runs somem do painel: `server.py` deriva o slug de `~/.claude/projects` do `DATA_ROOT` e `run_agent.py` do `ROOT` | alta em F3 | médio | slug calculado do caminho do repo/worktree do produto (B13), com teste, **antes** do corte |
| Demandas em voo na F4 com prompts que citam `tools/squad/…` relativos | média | médio | calços por um release; plantão avisa uso de calço |
| Subagentes nativos do Claude Code dessincronizados dos papéis gerados | média | médio | geração + verificação no plantão; o runner genérico usa sempre a composição |
| Credenciais do host compartilhadas entre produtos (`gh`, docker, runners) | — | alto se houver produto de terceiros | isolamento declarado como contra erro; produto de terceiros exige host/usuário próprio (fora do escopo) |
| Duas fontes de verdade durante F2 (cadastro e constantes) | média | médio | F2 remove as constantes; teste de equivalência + grep no aceite |
| Branches em voo (D12, D21) conflitando com F2–F4 | alta | médio | regra do §4.11: integrar antes ou absorver depois; F3/F4 não começam com PR aberto em `tools/squad`/`squad-control`/`docs/squad` |
| Leitura de outro produto pela conversa com codex | média com 2+ produtos | alto | limitação declarada, aviso nominal e opção explícita por produto; claude com negação gerada (§4.9) |
| Links de issues/PRs para a memória sem alvo | alta se Q4 = local | baixo | id do evento + resumo do parecer no PR; reescrita para SHA fixo se Q7 = apagar (§4.12) |
| Squad trabalhando no próprio chão (D22 muda as ferramentas que executam a D22) | alta | médio | fases pequenas, produto padrão implícito, flag de retorno em cada fase |

## 8. Fora do escopo
Hospedar a plataforma fora do host local; multiusuário/autenticação no painel; isolamento contra agente malicioso;
banco de dados para a memória; publicar a plataforma como pacote.

## 9. Perguntas que só o humano decide
**Bloqueios**: a **Q2 bloqueia a F2** (F2a grava `code` e `code_prefix`; sem a resposta não há especificação).
A **Q4 precisa de resposta antes do G1 da F3** (define `link_base`, os links de parecer em PRs e issues, §4.12).
Recomendado responder a Q3 junto com a Q2. As demais não bloqueiam (Q1: F4; Q5: F3; Q6: F4/F5; Q7: pós-F3; Q8: F6).

1. **Repositório novo** `jcrouzillard/squad-platform` (público ou privado?) — ou prefere outro nome/dono?
2. **[bloqueia a F2] Numeração das demandas**: o checkout continua em `D23, D24…` e a plataforma usa prefixo próprio (proposta:
   `P1, P2…`), ou a numeração continua **global** entre produtos? E a D22 (esta), que é da fábrica, fica como D22?
3. **Histórico legado**: aceita manter D1–D21 inteiros na memória do `checkout-saga` (visível também no
   `squad-platform`), sem dividir por tipo, como proposto em §4.4.6?
4. **[responder antes do G1 da F3] Remoto da memória**: a memória de cada produto deve ter remoto privado no GitHub (backup e auditoria fora do
   host) ou fica só local? Se remoto: um repo privado por produto? (Decide para onde apontam os links de parecer e de
   evidência em PRs e issues, §4.12; conversas e anexos ficam fora do git em qualquer caso.)
5. **Janela de corte da F3**: autoriza pausar o plantão por até 15 min num momento escolhido por você?
6. **Calços e apelidos**: por quanto tempo manter os calços `tools/squad/*.py` e as rotas antigas da API (proposta:
   um release depois da F4/F5)?
7. **Arquivos antigos no produto**: depois da F3, apagar `docs/squad/memory/**`, `gates/`, `inbox/` e bugs do repo do
   produto (ficam no histórico git) ou manter congelados para sempre? (Se apagar, os links das 173 issues são
   reescritos antes para um SHA fixo, §4.12.)
8. **F6**: aceita um produto sintético (`hello-squad`) só como prova, ou já existe um segundo produto real em vista?

## 10. Ressalvas do G1-D22 (ciclo 1) e onde foram tratadas
| # | Ressalva | Tratamento |
|---|---|---|
| 1 | Conflito com ADR-020 (conversas no git) e anexos da D21 | §4.3: conversas e anexos em `run:` (fora do git); ADR-020/023 sem mudança; mapa B7, B16 |
| 2 | ADR-015/D12 ausente; branches em voo | §3, mapa E2; §4.11 |
| 3 | Links `blob/…/docs/squad/…` do `github_sync.py` | mapa F5; §4.12; Q4 e Q7 |
| 4 | `git filter-repo` fora da stdlib | §4.13 (pré-requisito do host + alternativa só git) |
| 5 | Produtivo da plataforma não é Compose | §3: `[env.prod] kind = "process"` (7070) |
| 6 | Isolamento da conversa entre produtos | §4.9: negação gerada (claude), limitação declarada (codex), teste F6 nos dois |
| 7 | Constituição para Codex/Copilot/Devin | §4.5: bloco gerado no `AGENTS.md`; mapa D2 |
| 8 | Valores menores | mapa A10, C16, C17, C18, G7 |
| 9 | F2 grande | §6: F2a e F2b; mapa com fase F2a/F2b |
| 10 | Brief de handoff | `docs/squad/memory/handoffs/12-arquiteto-d22-adr024-para-auditor.md` |

## 11. Respostas do humano e errata da F2a (D23, `6450aecde7f9`, Arquiteto, 2026-09-25)
Contrato da fase: [`docs/contracts/f2a-resolvedor-de-produto.md`](../contracts/f2a-resolvedor-de-produto.md).

**Respostas (cartão da D23)**: **Q2** — numeração `D` global (D23, D24…) até a F5; a partir da F5 o produto
`squad-platform` usa `P` (P1, P2…); o checkout continua em `D`; D1–D23 congeladas como aparecem hoje no painel (a D22
continua D22; a F2a é a D23). **Q3** — aceito: D1–D21 inteiras na memória do checkout, sem dividir por tipo, visíveis
como somente leitura na plataforma (§4.4.6 confirmado).

**Errata** (nenhuma muda uma decisão do §2; todas precisam o que a F2a entrega):
- **E1 — caminho do módulo.** Onde o §6 diz `squad/product.py`, na F2a lê-se `tools/squad/product.py` (a pasta
  `squad/` só existe na plataforma, F4). O cadastro fica em `docs/squad/products/checkout-saga/product.toml`.
- **E2 — local da tabela congelada.** Na F2a, `codes.json` **não** fica em `docs/squad/memory/` (memória viva, `STATE`
  do `gitflow.py`: descartada do worktree e proibida no PR pelo G3). Fica em
  `docs/squad/products/checkout-saga/codes.json`, como configuração imutável revisada no PR; na F3 vai para
  `mem:codes.json` sem mudar de formato. (Afeta §3, §4.4.1 e mapa B14.)
- **E3 — alcance do congelamento.** Pela resposta à Q2, o congelamento cobre **D1–D23** (o §6, F2a (a), dizia D1–D22); ressalva do G1: como a D24 (`cf7a120591b0`) já existe no log, a tabela congela **D1–D24** e a primeira demanda nova é a D25 (regenerada antes do `feature-finish` até o último `task` existente — contrato F2a §4.5).
- **E4 — semântica dos apelidos.** O apelido `D7` (citado para `e31bdfb73679`) colide com o código congelado `D7`
  (`349e5b1bf818`). "Continuar resolvendo" (§4.4.1) passa a significar: **no contexto do documento/branch/parecer que o
  cita**; um código sem contexto resolve sempre para o congelado.
- **E5 — divergências não estão só nos contratos.** As mesmas 4 demandas (`e31bdfb73679`, `349e5b1bf818`,
  `174084ec85d0`, `f2324e0f25de`) têm o código "antigo" também nos nomes das branches e dos pareceres
  (`G*-D7…D10.json`); a lista exata está no contrato §4.3. Nada é renomeado.
- **E6 — B13 inclui as runs.** Além do slug, `run_agent.py` grava `.squad/runs` no `ROOT` do script e não no
  `DATA_ROOT` do servidor; a F2a passa as runs para o `data_root` resolvido e grava o caminho exato da transcrição no
  metadado da run (contrato §6).
