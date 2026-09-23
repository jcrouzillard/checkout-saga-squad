.PHONY: up down ps logs build test e2e restart-orchestrator kill-orchestrator squad

## Sobe toda a stack (infra + observabilidade + serviços), (re)construindo as imagens.
up:
	docker compose up -d --build

## Derruba a stack e remove volumes (bancos ficam limpos na próxima subida).
down:
	docker compose down -v

## Status dos containers.
ps:
	docker compose ps

## Segue os logs de todos os containers.
logs:
	docker compose logs -f

## Build Maven multi-módulo (usado fora do Docker, ex. no CI).
build:
	mvn -q -B package -DskipTests

## Testes unitários Maven.
test:
	mvn -q -B test

## Suíte de testes ponta a ponta (propriedade do QA).
e2e:
	bash tests/e2e/run.sh

## Reinicia o orquestrador de Saga (cenário de restart durante uma saga em andamento).
restart-orchestrator:
	docker compose restart saga-orchestrator

## Mata e sobe de novo o orquestrador (cenário de falha abrupta / crash).
kill-orchestrator:
	docker compose kill saga-orchestrator && docker compose up -d saga-orchestrator

## Gera o dashboard da squad (propriedade do Orquestrador).
squad:
	python3 tools/squad/server.py # painel em http://localhost:7070

github-sync: ## Espelha o log da squad em Issues + GitHub Project (kanban)
	python3 tools/squad/github_sync.py --watch 20

squad-inbox: ## Lista as demandas iniciadas aguardando o Orquestrador
	@/bin/ls -1 docs/squad/inbox/*.json 2>/dev/null || echo "fila vazia"

feature-start: ## make feature-start CODE=D3 SLUG=cupom DEMAND=<id>
	python3 tools/squad/gitflow.py feature-start $(CODE) $(SLUG) $(if $(DEMAND),--demand $(DEMAND))

feature-finish: ## make feature-finish DEMAND=<id>
	python3 tools/squad/gitflow.py feature-finish $(if $(DEMAND),--demand $(DEMAND))

release: ## make release VERSION=1.1.0 (release-start + release-finish)
	python3 tools/squad/gitflow.py release-start $(VERSION) && python3 tools/squad/gitflow.py release-finish $(VERSION)

plantao: ## Plantão do Orquestrador fora da sessão (SQUAD_RUNNER=claude|codex)
	tools/squad/plantao.sh

run-agent: ## make run-agent ROLE=qa TASK="..." [RUNNER=codex]
	SQUAD_RUNNER=$(or $(RUNNER),claude) python3 tools/squad/run_agent.py $(ROLE) "$(TASK)"
