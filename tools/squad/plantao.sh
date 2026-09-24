#!/usr/bin/env bash
# Plantão do Orquestrador fora de qualquer sessão interativa, com o fornecedor escolhido.
#   SQUAD_RUNNER=codex  tools/squad/plantao.sh          # a cada 180 s
#   SQUAD_RUNNER=claude PLANTAO_INTERVALO=60 tools/squad/plantao.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
INTERVALO="${PLANTAO_INTERVALO:-180}"
echo "plantão do Orquestrador · runner=${SQUAD_RUNNER:-claude} · a cada ${INTERVALO}s"
while true; do
  # D15 (contrato §4.6): pedidos do humano ao ambiente de teste parados pelo lock são retomados a cada ciclo.
  [ -f infra/teste/teste.env ] && python3 tools/squad/testenv.py reconcile >/dev/null 2>&1 || true
  if python3 tools/squad/pending.py; then
    python3 tools/squad/run_agent.py orquestrador @docs/squad/prompts/plantao.md || echo "execução do Orquestrador terminou com erro"
  fi
  sleep "$INTERVALO"
done
