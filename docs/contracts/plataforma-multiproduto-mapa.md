# Mapa do acoplamento squad × produto (D22 fase 1, `b26da7851764`, anexo do ADR-024)

Levantamento feito no código em 2026-09-25 sobre `feature/D22-plataforma-multiproduto` (base `20ba9fb`) e, para a
memória viva, sobre a cópia principal `plankton/` (`develop`, `98ba7a9`, log com 619 eventos). Cada linha é um
**ponto de acoplamento**: um lugar em que a squad (ferramentas, painel, papéis, memória) assume algo sobre **este**
produto ou sobre **estar dentro do repositório dele**. Linhas agrupam ocorrências do mesmo padrão; a coluna "Onde"
lista todas as ocorrências encontradas.

**Classes**
- **PLAT** — mecanismo genérico da plataforma: vai para o repositório da plataforma, sem nada do checkout.
- **CFG** — valor específico do produto hoje fixo no código: vira campo do cadastro `products/<id>/product.toml`.
- **PROD** — conhecimento do produto (regras, papéis especializados, critérios, documentos): fica no repo do produto.
- **MEM** — memória/estado da squad: sai do repositório do produto para o armazenamento de memória por produto.

**Fases** (detalhe no ADR-024 §6): F2a resolvedor e códigos congelados · F2b valores para o cadastro · F3 memória fora do repo ·
F4 repositório da plataforma · F5 painel multiproduto · F6 segundo produto (prova de isolamento).

Destinos citados: `$SQUAD_HOME` (padrão `~/.squad`), `mem:` = `$SQUAD_HOME/products/<id>/memory/` (repositório git
próprio), `run:` = `$SQUAD_HOME/products/<id>/runtime/` (fora do git; inclui `run:conversas/`, ADR-020/023), `plat:` = repositório `squad-platform`,
`cad:` = campo do cadastro `products/<id>/product.toml` no repositório da plataforma, `prod:` = repositório do produto.

## A. Raiz, caminhos e ponto de entrada (a plataforma assume que mora dentro do produto)

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| A1 | `ROOT = Path(__file__).parents[2]` em `server.py:41`, `gitflow.py:34`, `github_sync.py:28`, `conversa.py:38`, `run_agent.py:34`, `testenv.py:38`, `triage.py:16`, `log.py:24`, `pending.py:14`, `statusline_usage.py:29`; `instance.py`/`prod.py` via `testenv` | o código da squad e o código do produto são a mesma árvore | PLAT | `squad.product.resolve()` devolve `repo_path` do cadastro; `ROOT` da plataforma só para achar `squad-control/` | F2a |
| A2 | `DATA_ROOT = $SQUAD_ROOT_DATA or ROOT` em `server.py:43`, `testenv.py:39`, `pending.py:14`, `statusline_usage.py:36`; `cv.Store(DATA_ROOT)` `server.py:1172` | memória = raiz do repo do produto, salvo sobreposição de teste | MEM | costura já existente: passa a apontar para `mem:`; vira obrigatória por produto | F3 |
| A3 | `UI_DIR = ROOT / "squad-control"` `server.py:48`; `Instance(ROOT, …)` `server.py:1525,1826` | o painel é servido de dentro do produto | PLAT | `plat:squad-control/` | F4 |
| A4 | `Makefile` alvos `squad`, `github-sync`, `squad-inbox`, `feature-start/finish`, `release`, `plantao`, `run-agent`, `teste-*`, `e2e-teste`, `prod-atualizar` | a CLI da squad é o Makefile do produto | PLAT | CLI `squad --product <id> <comando>`; Makefile do produto mantém apelidos por 1 release | F4 |
| A5 | `tools/squad/plantao.sh:11-13` (cwd = raiz do produto, caminhos relativos, `infra/teste/teste.env`) | um plantão por repositório | PLAT | `squad plantao` itera os produtos ativos do cadastro | F4/F5 |
| A6 | `.gitignore:7` (`.squad/`) e o diretório `.squad/` (runs, conversas, locks, `pr-state.json`, `usage/`, `triagem-*.md`, `bug-drafts/`, `bug-pseudonym.key`, `after-review.log`, `server.log`, `sync.log`) | estado de execução vive no worktree do produto | MEM | `run:` (e `usage` global, ver B9) | F3 |
| A7 | `tests/squad/*.py` (13 arquivos com `parents[2]`/`REPO`) e `tests/ui/` do Squad Control (checklists D3–D20, `d*-*.js`, capturas) | testes da plataforma vivem e rodam no repo do produto | PLAT | `plat:tests/` (os de `tests/ui/checklist-console.md`, `console-*.png` ficam no produto) | F4 |
| A8 | `.github/workflows/ci.yml` só roda `mvn verify` e e2e do produto; `tests/squad` não roda em CI | a plataforma não tem CI própria | PROD | CI do produto intacta; `plat:.github/workflows/ci.yml` roda `tests/squad` | F4 |
| A9 | `CLAUDE.md` (importa `AGENTS.md`; plantão via `/loop` lendo `docs/squad/prompts/plantao.md`) | constituição e plantão são arquivos do produto | PROD | `CLAUDE.md` do produto importa `AGENTS.md` do produto + a constituição da plataforma (caminho do cadastro) | F4 |
| A10 | constantes do checkout nos testes da plataforma: `tests/squad/{d16_corpus.py, prova_produtivo_intacto.sh, test_bugs_d16.py, test_bugs_d16_qa.py, test_ambiente_teste_d15.py, test_e2e_compose_seguro_d15.py, test_entrega_por_pr.py}` e afins (projetos `checkout-saga`/`checkout-teste`, portas 808x, `orderId`, repo) | os testes da plataforma só valem para o checkout | CFG | testes leem o cadastro de um produto de teste (`tests/fixtures/product.toml`); o critério (b)/(c) da F2b inclui `tests/squad` | F2b |

## B. Memória da squad (hoje versionada no repositório do produto)

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| B1 | `decisions.jsonl` em `log.py:24`, `server.py:44`, `testenv.py:40`, `pending.py:15`, `run_agent.py:36` (honram `SQUAD_LOG`) e em `gitflow.py:35`, `github_sync.py:29`, `triage.py:17` (**ignoram** `SQUAD_LOG`) | um log único, dentro do produto | MEM | `mem:log/decisions.jsonl`; os três que ignoram `SQUAD_LOG` passam a usar o resolvedor (pré-requisito de F3) | F2a→F3 |
| B2 | pareceres `docs/squad/gates/*.json` (`server.py:45`, `alerts.py:4`, `auditor.md:24`); **são commitados na branch da feature** (ex.: `G1-D21.json` em `428e06c`) e entram no PR | parecer do Auditor viaja com o código do produto | MEM | `mem:gates/`; o PR passa a citar o parecer por link | F3 |
| B3 | handoffs `docs/squad/memory/handoffs/` (`server.py:46`, `github_sync.py:31`, protocolo do `AGENTS.md`) | idem | MEM | `mem:handoffs/` | F3 |
| B4 | fila `docs/squad/inbox/*.json` + `done/` (`server.py:621,1725,1762`, `pending.py:51`, `Makefile squad-inbox`) | idem | MEM | `mem:inbox/` | F3 |
| B5 | bugs `docs/squad/{produto,operacao}/bugs/<demanda>/` + `index.jsonl` + evidências (`bugs.py:4,519`, `server.py:1404-1513`, `GitDirStore`) | evidências mascaradas versionadas no produto | MEM | `mem:bugs/<kind>/`; `BugStore` já é interface — ganha `MemoryDirStore` | F3 |
| B6 | `docs/squad/memory/github-sync.json` (`github_sync.py:30`, `gitflow.py:223`, `server.py:848`) — mantém o working tree da `develop` sempre sujo | estado do espelho do GitHub no produto | MEM | `mem:github-sync.json` | F3 |
| B7 | conversas `.squad/conversas/<id>.jsonl` e cwd `.sessao/` (`conversa.py:6-7,852`, `server.py:1117`) | uma conversa por instalação, não por produto | MEM | `run:conversas/` (histórico **fora do git**, como manda o ADR-020 §5/alt. G) + `run:conversas/.sessao`; nada de conversa em `mem:` | F3 |
| B8 | execuções `.squad/runs/*.json` (`run_agent.py:35`, `server.py:47`) | idem | MEM | `run:runs/` | F3 |
| B9 | consumo da IA `.squad/usage/claude.json` (`statusline_usage.py:5,199`, `server.py:871`) e sessões do Codex | consumo é do **host**, não do produto | PLAT | `$SQUAD_HOME/usage/` (global, mostrado em todos os produtos) | F3 |
| B10 | travas `.squad/test-env.lock` (`testenv.py:42`), `.squad/prod-update.lock` (`prod.py:29`), `prod-compose-*.yml` (`prod.py:168`) | uma trava por instalação | MEM | `run:locks/` por produto | F3 |
| B11 | chave de pseudônimo `.squad/bug-pseudonym.key` (`evidence_rules.py:340`, `conversa.py:245`) | segredo único | MEM | `run:bug-pseudonym.key` por produto (isolamento: pseudônimos não se correlacionam entre produtos) | F3 |
| B12 | maquinaria de "memória viva no git": `STATE` e `snapshot_state` (commits "Sincronização da memória da squad"), `import_memory`, `align_memory`, `discard_state`, `STATE` em `feature_sync`/`review_update` (`gitflow.py:66-106,151-178,447-458,488-590`); critério G3 "Memória fora do PR" (`gates.md:43-44`); `delegacao.md:13`; guarda de `prod.py:142` que tolera `docs/squad/**` sujo; estados "sujo" do ADR-021 (`instance.py`) | a memória muda o repositório do produto o tempo todo | PLAT | vira código morto com a memória fora (F3: no-op sob flag; F4: removido); critério G3 substituído por "PR não toca `mem:`" (trivial) | F3/F4 |
| B13 | pasta de transcrições `~/.claude/projects/<slug do caminho>` (`run_agent.py:50-52` pelo `ROOT`, `server.py:66-70` pelo `DATA_ROOT`) | um único caminho de repo por instalação | PLAT | slug calculado do `repo_path`/worktree do produto (cadastro); `SQUAD_TRANSCRIPTS` continua sobrepondo | F2a |
| B14 | código da demanda **posicional** `D{n}` = n-ésimo `task` do humano: `alerts.py:93`, `gitflow.py:415`, `pending.py:33`, `testenv.py:385`, `index.html:1832,2703`, `conversa.py:394` (`codes`) | numeração global, derivada da ordem do log | MEM | campo `code` gravado no `task` + `mem:codes.json` congelando o legado; **já divergiu**: contratos citam `e31bdfb73679`=D7, `349e5b1bf818`=D8, `174084ec85d0`=D9, `f2324e0f25de`=D10, e o cálculo atual dá D8, D7, D10, D9 | F2a |
| B15 | eventos gravados sem produto: `log.py` não tem `--product`; `AGENTS` e `TYPES` fixos (`log.py:25-33`) | só existe um produto | MEM | o produto é **implícito pelo local** do log (`mem:` por produto); `log.py` recusa gravar se `SQUAD_PRODUCT` e o log não baterem | F3 |
| B16 | anexos de imagem da conversa (D21, ADR-023): `<DATA_ROOT>/.squad/conversas/<id>/anexos/<sha256>.<ext>`, tetos 100 MB/conversa e 500 MB total, rota `POST /api/conversas/<id>/anexos` | anexos por instalação, ao lado da conversa | MEM | `run:conversas/<id>/anexos/` (fora do git, mesma pasta da conversa); tetos por produto; a rota ganha o produto (`/api/p/<id>/conversas/<c>/anexos`, F5) | F3 |

## C. Valores do checkout fixos no código (viram cadastro)

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| C1 | repositório `jcrouzillard/checkout-saga-squad` em `gitflow.py:37`, `bugs.py:51`, `github_sync.py:32` (env), `index.html:2044` (`BUG_REPO`); Project nº `1` (`github_sync.py:34`); visibilidade `SQUAD_REPO_VISIBILITY` (`bugs.py:487`) | um repositório e um Project | CFG | `cad:github.{repo, owner, project, visibility}` | F2b |
| C2 | nomes de branch `develop`/`main`/`feature/`/`release/`/`hotfix/`: `gitflow.py` (4-13, 99-106, 132-135, 165-197, 207, 226, 285-294), `prod.py:134-140`, `testenv.py:125` e `instance.py:62-89` ("cópia principal = worktree em `develop`"), `pending.py:96`, `alerts.py:293`, tipo/rótulos `conflito-develop` (`conversa.py:459-786`, `index.html:1397,1424`), `gates.md:39-45`, `plantao.md:16-26`, `delegacao.md:7-8,22-23`, `git-flow.md` | Git Flow com esses nomes | CFG | `cad:git.{integration, stable, prefixes}`; o **modelo** Git Flow segue PLAT; o id `conflito-develop` fica estável, o rótulo vem do cadastro | F2b |
| C3 | tabela de donos `OWNERS` (`gitflow.py:397-412`), tabela do `AGENTS.md`, seções "Dono de" em `.claude/agents/*.md` | uma tabela de ownership | CFG | `cad:owners` (fonte única; o `AGENTS.md` do produto é validado contra ela) | F2b |
| C4 | build e versão: `mvn versions:set` (`gitflow.py:119`), versão lida do `pom.xml` (`instance.py:100`), `CHANGELOG.md` (`gitflow.py:36`), `mvn -q package` nos critérios G2 (`gates.md:20`) e em `backend.md:30,37` | produto Maven | CFG | `cad:build.{version_get, version_set, package, unit_test, changelog}` | F2b |
| C5 | projetos Compose `checkout-saga`/`checkout-teste`: `testenv.py:44-45`, `prod.py:48-53`, `evidence_rules.py:138`, `alerts.py:721`, `bugs.py:276,677`, `index.html:1482,1486,2086`, `Makefile TESTE_COMPOSE`, `docker-compose.yml:1`, `infra/teste/teste.env:9-10` | um produtivo e um teste | CFG | `cad:env.prod.compose_project`, `cad:env.test.compose_project` | F2b |
| C6 | serviços e regras caminho→serviço: `APP_SERVICES` (`testenv.py:47`), `prod.py:77-95` (`services/`, `pom.xml`, `Dockerfile`, `checkout-console/nginx.conf`, `infra/observability/*`, `infra/postgres/init/`), smoke (`testenv.py:665-667`) | topologia do checkout | CFG | `cad:env.services`, `cad:env.deploy_rules[]`, `cad:env.smoke[]` | F2b |
| C7 | portas: produtivo/teste `testenv.py:49-51,164-168`, `evidence_rules.py:139-140`, `bugs.py:50,86-100`, `index.html:1433,2062-2064,2176`, `teste.env`, `Makefile TESTE_E2E_ENV`, defaults `GRAFANA_PORT/CONSOLE_PORT` (`server.py:1589`) | um conjunto de portas no host | CFG | `cad:env.prod.ports`, `cad:env.test.port_offset`; a plataforma valida colisão **entre produtos** | F2b (F6 valida) |
| C8 | convenções de diretório: worktree `<nome da cópia>-dNN` (`gitflow.py:436-438`), `plankton-teste` (`testenv.py:139`), cópia principal (`testenv.py:110-134`, `prod.py:124-132`) | layout `plankton*` num mesmo pai | CFG | `cad:workspace.{main_root, worktree_pattern, test_worktree}` | F2b |
| C9 | recursos ligados pela **existência de arquivo**: `infra/teste/teste.env` (`plantao.sh:11`, `gitflow.py:256`, `plantao.md:8`, `testenv.py:145`), `docker-compose.yml` e `tools/squad/prod.py` (`gitflow.py:253-254`, `prod.py:131`) | o produto tem teste e produtivo Compose | CFG | `cad:env.test.enabled`, `cad:env.prod.enabled` + `env_file` | F2b |
| C10 | `docs/squad/project.json` (`server.py:1581-1589`, `index.html:1654-1659`, "não tem … configurado em docs/squad/project.json") com nome, links, Grafana/Jaeger | cadastro embrionário, dentro do produto, com `current` único | CFG | absorvido por `cad:[product]`, `cad:links`, `cad:observability` | F2b |
| C11 | onde ficam ADRs/contratos/arquitetura/requisitos: `conversa.py:534` (detecta risco por `docs/adr/`/`docs/contracts/`), `conversa.md:5-6`, `gates.md`, `arquiteto.md:24-31`, `AGENTS.md` (hierarquia: `docs/desafio.md`) | layout de docs do checkout | CFG | `cad:docs.{requirements, adr, contracts, architecture}` | F2b |
| C12 | máscara de PII com chaves do checkout (`shippingAddress`, CEP, destinatário, `customerId`) `evidence_rules.py:7,227-248,286` | domínio de pedidos | CFG | `cad:evidence.pii_keys` somado à base genérica (segredos, IP, e-mail seguem PLAT) | F2b |
| C13 | URLs de observabilidade do produtivo `SQUAD_PROD_JAEGER/GRAFANA/PROMETHEUS` e porta Grafana lida do `.env` da cópia principal (`bugs.py:7,86-100`, `server.py:1584`); validação de link do bug (`index.html:2055-2072`) | Jaeger/Grafana do checkout | CFG | `cad:observability.{jaeger, grafana, prometheus}` | F2b |
| C14 | e2e contra o teste: `Makefile TESTE_E2E_ENV`, `tests/e2e/run.sh` (`E2E_COMPOSE_PROJECT`) | comando de teste do produto | PROD | continua no produto; a plataforma só chama `cad:build.e2e_test` | F2b |
| C15 | `.env` da cópia principal lido pela plataforma (`bugs.py:86`, `server.py:1584`) | o produto usa `.env` | CFG | `cad:env.prod.env_file` | F2b |
| C16 | chaves de correlação `CORRELATION_KEYS = {orderId, sagaId}` (`bugs.py:185-186`) usadas para ligar evidências a pedido/saga | domínio de pedidos | CFG | `cad:evidence.correlation_keys` | F2b |
| C17 | cartões do ambiente de teste `TE_URLS` ("Console de Checkout", Grafana, Jaeger, Prometheus) e `TE_APIS` (5 serviços) em `index.html:1433-1434` | topologia do checkout no HTML | CFG | `/api/test-env` devolve rótulos e URLs de `cad:env.services` + `cad:links` | F2b |
| C18 | textos com porta do Jaeger/Grafana na demanda de bug (`index.html:2023, 2031, 2064-2072, 2174-2176`: ":16686", ":9090", "+10 000, ex.: :26686, :13001") | portas do checkout em texto | CFG | texto montado de `cad:observability` e `cad:env.test.port_offset` (a lista de portas em si é C7) | F2b |

## D. Papéis, prompts e políticas

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| D1 | `AGENTS.md` mistura regras da fábrica (single-writer, handoff, hierarquia, autonomia, Git Flow, produtivo inquebrável, portabilidade) com o produto (ADR-000: Java 21, portas, bancos, `com.checkout`, convenções de código) | constituição = documento do produto | PLAT | `plat:policies/constitution.md` (fábrica) | F4 |
| D2 | (mesmo arquivo) parte do produto do `AGENTS.md` | — | PROD | `prod:AGENTS.md` = bloco **gerado** com a constituição (entre marcadores, versão da plataforma) + ADR-000, topologia e convenções do produto; ver ADR-024 §4.5 | F4 |
| D3 | `.claude/agents/{arquiteto,backend,devops,observabilidade,qa,frontend}.md`: papel genérico + especialização do checkout (bounded contexts, módulos Maven, métricas `saga_*`, cenários de falha, `checkout-console`) | papel = papel no checkout | PLAT | `plat:roles/<papel>.md` (base genérica) | F4 |
| D4 | (mesmos arquivos) especialização | — | PROD | `prod:squad/roles/<papel>.md` (overlay); `.claude/agents/*.md` do produto passam a ser **gerados** (base+overlay) para os subagentes nativos do Claude Code, com verificação de sincronia | F4 |
| D5 | `.claude/agents/auditor.md` (gates em `docs/squad/gates/`), `docs/squad/orquestrador.md` ("Orquestrador da squad do Checkout Saga … seção 14 do desafio") | idem | PLAT | base em `plat:roles/`; missão do produto vem de `cad:mission` + `prod:AGENTS.md` | F4 |
| D6 | `docs/squad/gates.md`: estrutura (pesos, bloqueantes, confiança, G1/G2/G3, autocorreção) + critérios do checkout (6 eventos, Saga, `mvn`, compose, Jaeger, `checkout-console`) | um único conjunto de critérios | PLAT | `plat:policies/gates-base.md` | F4 |
| D7 | (mesmo arquivo) critérios do produto | — | PROD | `prod:squad/gates.md`, referenciado por `cad:policies.gates` | F4 |
| D8 | prompts `docs/squad/prompts/{plantao,delegacao,conversa,triagem}.md` com caminhos do produto (`tools/squad/…`, `plankton-teste`, `develop`, `docs/squad/<produto\|operacao>/bugs`) e `run_agent.py:89-90` (`{LOG_PY}`, `{GITFLOW_PY}`) | um produto por instalação | PLAT | `plat:prompts/` com placeholders preenchidos do cadastro (`{PRODUCT}`, `{MAIN}`, `{INTEGRATION_BRANCH}`, `{TEST_WORKTREE}`, `{MEMORY}`) | F2b (placeholders) / F4 (move) |
| D9 | `run_agent.py:108,169-193` (lê `.claude/agents/<papel>.md` e `docs/squad/orquestrador.md` do `ROOT`; texto "squad do projeto neste repositório"; reescreve `log.py` para caminho absoluto) e `triage.py:23-60` | papel e tarefa vêm do mesmo repo | PLAT | `run_agent` compõe base+overlay+`AGENTS.md` do produto; exporta `SQUAD_PRODUCT` e `SQUAD_LOG` do produto | F4 |
| D10 | conjunto fixo de papéis: `log.py:25` (`AGENTS`), `index.html:815-823` (rótulos com descrição do checkout: "Bounded contexts, Saga e contratos", "Interface do produto (Console de Checkout)"), `index.html:950` (`ROLES`), `index.html:1752` (`TARGETS`) | papéis e descrições do checkout | PLAT | conjunto de papéis fixo na plataforma; descrição por produto em `cad:roles.<papel>.description` | F5 |
| D11 | pipeline F1→G3 e pareceres da "squad base" `G*-1.json` (`index.html:826-833,1645`, alerta B2 squad-base `index.html:1086`) | houve uma construção inicial única | PLAT | "construção inicial" vira atributo do produto (`cad:bootstrap_gates`); legado do checkout preservado | F5 |
| D12 | `frontend` é dono de `checkout-console/**` **e** `squad-control/**` (`frontend.md:31`, `OWNERS`) | a interface da fábrica é artefato do produto | CFG | no produto, só `checkout-console/**`; `squad-control/**` passa a ser do Frontend **no produto `squad-platform`** | F4 |
| D13 | docs da fábrica `docs/squad/{portabilidade,monitoramento,git-flow}.md`, `docs/apresentacao.md` (parte squad) | documentação da fábrica no produto | PLAT | `plat:docs/` | F4 |
| D14 | marca/autoria fixa "Desafio Técnico \| Checkout Saga com Squad Agêntica · Julien Crouzillard" (`index.html:780,784`), título "`<produto>` · Orquestrador + Auditor" (`index.html:754,1658`) | um produto, um autor | CFG | `cad:[product].name`; rodapé de autoria da **plataforma** (`plat:` config global) | F5 |
| D15 | tipos de demanda `produto` ("muda o checkout") / `operacao` ("muda a fábrica") (`index.html:1755-1756`, `log.py:70-71`, `triagem.md:12`, pastas de bugs) | fábrica e produto no mesmo backlog | PLAT | `produto` = o produto selecionado; `operacao` = demanda do produto `squad-platform` (roteada para lá) | F5 |

## E. ADRs e contratos existentes

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| E1 | ADR-001..007, 010, 013; contratos `api.md`, `events.md`, `ui-checkout-console.md`, `d10-alinhamento.md`; `docs/architecture/**`, `docs/observability.md`, `docs/desafio.md` | — | PROD | ficam no produto, sem mudança | — |
| E2 | ADR-008, 009, 011, 012, 014, 015 (D12, PR #104 em aberto), 016, 017, 019, 020, 021, 022, 023 (D21), 024; contratos `ui-*` do Squad Control, `entrega-por-pr.md`, `demandas-de-bug.md`, `conversa-com-o-orquestrador.md`, `delegacao-pela-conversa.md`, `ui-ambiente-e-versao.md` | decisões da fábrica registradas no produto | PLAT | `plat:docs/adr` e `plat:docs/contracts` com **mesmos números** (links antigos seguem válidos por um índice no produto) | F4 |
| E3 | ADR-018 + `ambiente-de-teste.md`: mecanismo (fila, trava, pedido do humano, produtivo inquebrável) **e** valores do checkout (projetos, portas, serviços) | — | CFG | mecanismo → PLAT (E2); valores → `cad:env` (C5–C9) | F2b/F4 |

## F. Integrações e variáveis de ambiente

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| F1 | chamadas `gh` (`pending.py:87`, `github_sync.py:43-126`, `gitflow.py:123`, sonda do teste `server.py:560`) sem `-R` em parte delas (dependem do cwd) | cwd = repo do produto | PLAT | sempre `-R cad:github.repo`; autenticação `gh` do host continua única (ver riscos) | F2b |
| F2 | chamadas `docker compose` (`testenv.py`, `prod.py`, `alerts.py`, `bugs.py:276`) | projeto e cwd do checkout | PLAT | parâmetros do `cad:env`; guardas do ADR-018 genéricas | F2b |
| F3 | variáveis globais da instalação: `SQUAD_PORT`, `SQUAD_RUNNER`, `SQUAD_CHAT_RUNNER/MODEL/TIMEOUT_S/FAKE`, `SQUAD_MODEL`, `SQUAD_RUN`, `SQUAD_DELEGATION`, `SQUAD_TRANSCRIPTS`, `SQUAD_ENV`, `SQUAD_STALLED_S`, `SQUAD_HANDOFF_STALLED_S`, `SQUAD_DOCKER/GH/GIT/LSOF`, `SQUAD_TESTENV_PROBE/SPAWN` | — | PLAT | continuam globais; novas: `SQUAD_HOME`, `SQUAD_PRODUCT` | F2b |
| F4 | variáveis que hoje descrevem **o** produto: `SQUAD_ROOT_DATA`, `SQUAD_LOG`, `SQUAD_GH_REPO/OWNER/PROJECT`, `SQUAD_PROD_JAEGER/GRAFANA/PROMETHEUS`, `SQUAD_PROD_AUTOUPDATE`, `SQUAD_MAIN_ROOT`, `SQUAD_TEST_WORKTREE`, `SQUAD_TEST_MIN_FREE_GB`, `SQUAD_TEST_SMOKE_SLEEP`, `SQUAD_REPO_VISIBILITY` | um produto por processo | CFG | viram campos do cadastro; a variável continua valendo como **sobreposição** (testes) só com `SQUAD_PRODUCT` explícito | F2b |
| F5 | links para a memória gravados nas issues pelo espelho: `github_sync.py:98-99` (`link()` → `blob/<branch>/docs/squad/…`), `:140` (diário → `decisions.jsonl`), `:194` (evidências de bug → `blob/develop/docs/squad/…/evidencias/`) | a memória é navegável no GitHub do produto | PLAT | `link()` passa a usar `cad:memory.link_base`: com remoto da memória (Q4 = sim) aponta para o repo privado de memória; sem remoto, a issue cita o caminho `mem:` e o id do evento em texto (sem link). As 173 issues antigas mantêm os links em `blob/develop/…` enquanto os arquivos não forem apagados do produto (Q7) — se Q7 = apagar, os links antigos passam a apontar para um SHA fixo (`blob/<sha do corte>/…`), reescritos uma vez pelo espelho | F3 |

## G. Servidor e painel

| # | Onde | O que assume | Classe | Destino | Fase |
|---|---|---|---|---|---|
| G1 | rotas sem produto: `/api/state`, `/api/live`, `/api/project`, `/api/policy`, `/api/demand*`, `/api/human`, `/api/test-env*`, `/api/bug*`, `/api/conversas*`, `/api/delegacoes*`, `/api/instance`, `/api/usage` | um produto por servidor | PLAT | `/api/products` + `/api/p/<id>/…`; rotas antigas = apelido do produto padrão até F5+1 release | F5 |
| G2 | `/api/policy` devolve `docs/squad/gates.md` e `CLAUDE.md` do produto (`server.py:1593-1594`) | constituição única | PLAT | devolve constituição + gates-base + critérios do produto | F4/F5 |
| G3 | versão/ambiente do Squad Control (ADR-021) lidos do `pom.xml` e tags **do checkout** e da cópia principal do produto (`instance.py:100-110`, `server.py:1521-1526`) | a versão da fábrica é a do produto | PLAT | versão da plataforma = tags/commit de `plat:`; produtivo do Squad Control = cópia principal da plataforma | F4 |
| G4 | alertas (`alerts.py`), estado de agentes, fila do teste e sino calculados sobre **um** log; A5 cita `checkout-teste` | — | PLAT | por produto + agregado no sino global com etiqueta do produto | F5 |
| G5 | rotas por hash sem produto `#/demandas/D7`, `#/auditoria/...`, `?conversa=` (`index.html`, ADR-016) | um produto | PLAT | `#/p/<id>/demandas/D7`; hash antigo redireciona para o produto padrão | F5 |
| G6 | uma instância do servidor por cópia de repositório (porta 7070 = produtivo do Squad Control, ADR-021) | painel acoplado ao checkout | PLAT | um servidor da plataforma por host servindo N produtos | F4/F5 |
| G7 | textos de caminho da memória no painel: `index.html:826` (`docs/squad/orquestrador.md`), `:2413` (`docs/squad/memory/decisions.jsonl`), `:2423` (`docs/squad/gates/`), `:2447` (`handoffs/`), `:2462` (`docs/squad/gates.md`), `:2487` (`docs/squad/project.json`) | a memória e as políticas moram em `docs/squad/` do produto | PLAT | textos vêm de `/api/p/<id>/policy` e de um campo `paths` do estado (caminho `mem:` real) | F3 |

## Contagem

74 pontos (67 do G1 + 7 acrescentados pelas ressalvas do G1-D22: A10, B16, C16–C18, F5, G7; cada linha agrupa todas as ocorrências do mesmo padrão; as ocorrências individuais citadas somam mais de
150 locais de código/documento).

| Classe | Pontos | Linhas |
|---|---|---|
| PLAT | 30 | A1, A3–A5, A7, B9, B12, B13, D1, D3, D5, D6, D8–D11, D13, D15, E2, F1–F3, F5, G1–G7 |
| CFG | 22 | A10, C1–C13, C15–C18, D12, D14, E3, F4 |
| MEM | 15 | A2, A6, B1–B8, B10, B11, B14–B16 |
| PROD | 7 | A8, A9, C14, D2, D4, D7, E1 |

Por fase de migração (primeira fase em que o ponto muda): **F2a = 4** (A1, B1, B13, B14), **F2b = 25**,
**F3 = 17**, **F4 = 20**, **F5 = 7**, sem mudança = 1 (E1).
