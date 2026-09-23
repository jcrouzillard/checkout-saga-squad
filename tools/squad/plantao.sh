#!/usr/bin/env bash
# Plantão do Orquestrador fora de qualquer sessão interativa, com o fornecedor escolhido.
#   SQUAD_RUNNER=codex  tools/squad/plantao.sh          # a cada 180 s
#   SQUAD_RUNNER=claude PLANTAO_INTERVALO=60 tools/squad/plantao.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
INTERVALO="${PLANTAO_INTERVALO:-180}"
echo "plantão do Orquestrador · runner=${SQUAD_RUNNER:-claude} · a cada ${INTERVALO}s"
while true; do
  if python3 tools/squad/pending.py; then
    python3 tools/squad/run_agent.py orquestrador @docs/squad/prompts/plantao.md || echo "execução do Orquestrador terminou com erro"
  fi
  sleep "$INTERVALO"
done
