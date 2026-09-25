.PHONY: up down ps logs build test e2e restart-orchestrator kill-orchestrator squad \
	squad-primeiro-plano squad-parar squad-status squad-logs squad-publicar \
	teste-publicar teste-status teste-liberar teste-derrubar teste-apagar-dados teste-config e2e-teste prod-atualizar

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

squad: ## Squad Control em segundo plano com publicação automática (http://localhost:7070)
	python3 tools/squad/publisher.py start

squad-primeiro-plano: ## Modo antigo, no terminal, sem publicação automática
	python3 tools/squad/server.py

squad-parar: ## Para o supervisor e o Squad Control graciosamente
	python3 tools/squad/publisher.py stop

squad-status: ## Estado do supervisor/publicação do Squad Control
	python3 tools/squad/publisher.py status

squad-logs: ## Segue o log do Squad Control supervisionado
	tail -n 100 -f .squad/squad-control/server.log

squad-publicar: ## Pede a publicação da develop no Squad Control (opcional WHEN=now|safe)
	python3 tools/squad/publisher.py publish$(if $(WHEN), --when $(WHEN))

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

## ---------------------------------------------------------------------------
## Ambiente de teste compartilhado e produtivo local (D15, ADR-018,
## docs/contracts/ambiente-de-teste.md). O teste é o projeto Compose
## checkout-teste (portas = produtivo + 10000); o produtivo é o checkout-saga.
## Toda operação que muda containers delega a tools/squad/ (testenv.py/prod.py):
## nenhum alvo aqui roda "docker compose up/down" direto no teste ou no produtivo.
## ---------------------------------------------------------------------------
TESTE_COMPOSE := docker compose -p checkout-teste --env-file infra/teste/teste.env
TESTE_E2E_ENV := ORDER_URL=http://localhost:18081 SAGA_URL=http://localhost:18080 \
	INVENTORY_URL=http://localhost:18082 PAYMENT_URL=http://localhost:18083 \
	SHIPPING_URL=http://localhost:18084 JAEGER_URL=http://localhost:26686 \
	E2E_COMPOSE_PROJECT=checkout-teste E2E_COMPOSE_ENV_FILE=infra/teste/teste.env

teste-publicar: ## make teste-publicar DEMAND=<id> — pede (como humano) a publicação do PR da demanda no teste
	@test -n "$(DEMAND)" || { echo "uso: make teste-publicar DEMAND=<id>"; exit 2; }
	python3 tools/squad/testenv.py request --action publish --demand $(DEMAND)
	python3 tools/squad/testenv.py reconcile

teste-status: ## Estado do ambiente de teste (ocupante, fila, saúde) — só leitura
	python3 tools/squad/testenv.py status

teste-liberar: ## make teste-liberar DEMAND=<id> — libera o teste (stop, mantém dados) e publica o próximo da fila
	@test -n "$(DEMAND)" || { echo "uso: make teste-liberar DEMAND=<id>"; exit 2; }
	python3 tools/squad/testenv.py release --demand $(DEMAND) --reason human

teste-derrubar: ## Derruba o teste sem -v (libera memória, preserva os dados)
	python3 tools/squad/testenv.py down

teste-apagar-dados: ## make teste-apagar-dados CONFIRMA=APAGAR — apaga o volume do teste (nunca o produtivo)
	@test "$(CONFIRMA)" = "APAGAR" || { echo "recusado: apagar os dados do teste exige CONFIRMA=APAGAR"; exit 2; }
	python3 tools/squad/testenv.py request --action reset-data --confirm APAGAR
	python3 tools/squad/testenv.py reset-data

teste-config: ## Configuração resolvida do teste (só leitura; base do guard de portas/imagens)
	$(TESTE_COMPOSE) config

e2e-teste: ## Suíte e2e contra o ambiente de teste (18080-18084, Jaeger 26686), sem tocar o produtivo
	$(TESTE_E2E_ENV) bash tests/e2e/run.sh

prod-atualizar: ## Atualiza o produtivo (checkout-saga) só nos serviços alterados desde o último deploy
	python3 tools/squad/prod.py update
