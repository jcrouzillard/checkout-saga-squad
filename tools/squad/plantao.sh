#!/usr/bin/env bash
# Plantão do Orquestrador fora de qualquer sessão interativa, no executor configurado para o Orquestrador.
#   tools/squad/plantao.sh                      # a cada 180 s
#   PLANTAO_INTERVALO=60 tools/squad/plantao.sh
# D26 (ADR-027): o executor/modelo vêm do painel (Squad Control → Executores) ou de tools/squad/executores.py;
# SQUAD_RUNNER/SQUAD_MODEL não configuram mais (aviso se definidos). Código 3 do run_agent = executor indisponível
# com a política `parar`: registra e espera o próximo ciclo.
set -euo pipefail
cd "$(dirname "$0")/../.."
INTERVALO="${PLANTAO_INTERVALO:-180}"
for v in SQUAD_RUNNER SQUAD_MODEL; do
  if [ -n "${!v:-}" ]; then echo "aviso: $v ignorada (a configuração vem do painel/executores.py)" >&2; fi
done
echo "plantão do Orquestrador · a cada ${INTERVALO}s"
while true; do
  # D26: executor resolvido do Orquestrador a cada ciclo (configuração atual; sem checagem de login aqui)
  resolvido="$(python3 tools/squad/executores.py resolve orquestrador --context plantao --no-check --json 2>/dev/null \
    | python3 -c 'import json,sys; r=json.load(sys.stdin); print(r.get("runner") or ("erro: " + str(r.get("detail"))), r.get("model") or "(padrão do executor)")' 2>/dev/null || echo "desconhecido")"
  echo "$(date '+%H:%M:%S') Orquestrador: ${resolvido}"
  # D15 (contrato §4.6): pedidos do humano ao ambiente de teste parados pelo lock são retomados a cada ciclo.
  [ -f infra/teste/teste.env ] && python3 tools/squad/testenv.py reconcile >/dev/null 2>&1 || true
  # D24 (ADR-025): sobe o publicador do Squad Control se a 7070 estiver livre (nunca adota um servidor no ar).
  python3 tools/squad/publisher.py ensure >/dev/null 2>&1 || true
  if python3 tools/squad/pending.py; then
    code=0
    python3 tools/squad/run_agent.py orquestrador @docs/squad/prompts/plantao.md || code=$?
    if [ "$code" = 3 ]; then
      echo "Orquestrador não iniciado: executor indisponível (política parar); próximo ciclo em ${INTERVALO}s"
    elif [ "$code" != 0 ]; then
      echo "execução do Orquestrador terminou com erro (código $code)"
    fi
  fi
  sleep "$INTERVALO"
done
