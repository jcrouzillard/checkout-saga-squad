#!/usr/bin/env bash
# shellcheck disable=SC2329
# SC2329: todas as funções abaixo são chamadas indiretamente (via "$fn" em
# run_scenario, ou dentro de outras funções), o que o shellcheck não infere.
#
# Suite e2e do Checkout Saga — escrita a partir dos contratos (docs/contracts/*.md,
# docs/architecture/saga.md), não do código do Backend (test-first, ver F2).
#
# Uso:
#   bash tests/e2e/run.sh                 # roda os 8 cenários
#   bash tests/e2e/run.sh payment_failure  # roda só um cenário
#   SKIP_RESTART=1 bash tests/e2e/run.sh   # pula o cenário 6 (reinício do coordenador)
#
# Variáveis de ambiente (todas com default de docker-compose.yml):
#   ORDER_URL SAGA_URL INVENTORY_URL PAYMENT_URL SHIPPING_URL JAEGER_URL SKIP_RESTART
#
# Requer: curl. Usa jq se disponível; senão cai para "python3 -c" (ver json_get/history_has).
# Nunca usa sleep fixo longo para esperar estado: todo poll é feito em passos de 1s com timeout.

set -uo pipefail

ORDER_URL="${ORDER_URL:-http://localhost:8081}"
SAGA_URL="${SAGA_URL:-http://localhost:8080}"
INVENTORY_URL="${INVENTORY_URL:-http://localhost:8082}"
PAYMENT_URL="${PAYMENT_URL:-http://localhost:8083}"
SHIPPING_URL="${SHIPPING_URL:-http://localhost:8084}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
SKIP_RESTART="${SKIP_RESTART:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="$SCRIPT_DIR/last-report.json"

if [ -t 1 ] && command -v tput >/dev/null 2>&1; then
  C_GREEN="$(tput setaf 2)"; C_RED="$(tput setaf 1)"; C_YELLOW="$(tput setaf 3)"
  C_BOLD="$(tput bold)"; C_RESET="$(tput sgr0)"
else
  C_GREEN=""; C_RED=""; C_YELLOW=""; C_BOLD=""; C_RESET=""
fi

HAS_JQ=false
if command -v jq >/dev/null 2>&1; then
  HAS_JQ=true
fi

HAS_PYTHON3=false
if command -v python3 >/dev/null 2>&1; then
  HAS_PYTHON3=true
fi

if ! $HAS_JQ && ! $HAS_PYTHON3; then
  echo "ERRO: nem jq nem python3 disponíveis; impossível parsear JSON das respostas." >&2
  exit 3
fi

OVERALL_EXIT=0
COUNT_PASS=0
COUNT_FAIL=0
COUNT_SKIP=0
RESULTS=()

# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------

gen_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]'
  else
    python3 -c 'import uuid; print(uuid.uuid4())'
  fi
}

# json_get JSON PATH  → imprime o valor de um campo top-level simples ("orderId",
# "status", "history"...) ou um caminho com pontos ("a.b"). Sem suporte a índice
# de array (não é necessário para os campos consultados por esta suíte).
json_get() {
  local json="$1" path="$2"
  if $HAS_JQ; then
    printf '%s' "$json" | jq -r ".${path} // empty" 2>/dev/null
  else
    printf '%s' "$json" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
parts = [p for p in sys.argv[1].split(".") if p]
cur = data
for p in parts:
    if isinstance(cur, dict) and p in cur:
        cur = cur[p]
    else:
        cur = None
        break
if cur is None:
    print("")
elif isinstance(cur, (dict, list)):
    print(json.dumps(cur))
else:
    print(cur)
' "$path" 2>/dev/null
  fi
}

# history_has JSON STEP STATUS [DETAIL_SUBSTR] → 0 se existe entrada em .history
# com esse step+status (e, opcionalmente, contendo DETAIL_SUBSTR em .detail).
history_has() {
  local json="$1" step="$2" status="$3" detail="${4:-}"
  if $HAS_JQ; then
    printf '%s' "$json" | jq -e --arg step "$step" --arg status "$status" --arg detail "$detail" \
      '(.history // []) | any(.step == $step and .status == $status and (($detail == "") or ((.detail // "") | contains($detail))))' \
      >/dev/null 2>&1
  else
    printf '%s' "$json" | python3 -c '
import sys, json
data = json.load(sys.stdin)
step, status, detail = sys.argv[1], sys.argv[2], sys.argv[3]
for h in (data.get("history") or []):
    if h.get("step") == step and h.get("status") == status:
        if not detail or detail in (h.get("detail") or ""):
            sys.exit(0)
sys.exit(1)
' "$step" "$status" "$detail"
  fi
}

# json_array_length JSON → tamanho de um array JSON top-level (0 se não for array/erro).
json_array_length() {
  local json="$1"
  if $HAS_JQ; then
    printf '%s' "$json" | jq 'if type == "array" then length else 0 end' 2>/dev/null
  else
    printf '%s' "$json" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
except Exception:
    print(0)
    sys.exit(0)
print(len(data) if isinstance(data, list) else 0)
' 2>/dev/null
  fi
}

# json_array_field JSON INDEX FIELD → valor de um campo do elemento INDEX de um
# array JSON top-level ("" se ausente/null/fora do índice).
json_array_field() {
  local json="$1" index="$2" field="$3"
  if $HAS_JQ; then
    printf '%s' "$json" | jq -r --argjson i "$index" --arg field "$field" '.[$i][$field] // empty' 2>/dev/null
  else
    printf '%s' "$json" | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    sys.exit(0)
idx, field = int(sys.argv[1]), sys.argv[2]
try:
    v = data[idx].get(field)
except Exception:
    v = None
print("" if v is None else v)
' "$index" "$field" 2>/dev/null
  fi
}

# history_count JSON STEP STATUS → quantas entradas de .history casam step+status.
history_count() {
  local json="$1" step="$2" status="$3"
  if $HAS_JQ; then
    printf '%s' "$json" | jq --arg step "$step" --arg status "$status" \
      '[ (.history // [])[] | select(.step == $step and .status == $status) ] | length'
  else
    printf '%s' "$json" | python3 -c '
import sys, json
data = json.load(sys.stdin)
step, status = sys.argv[1], sys.argv[2]
print(sum(1 for h in (data.get("history") or []) if h.get("step") == step and h.get("status") == status))
' "$step" "$status"
  fi
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/ }"
  printf '%s' "$s"
}

# http_request METHOD URL [curl-args...] → seta HTTP_STATUS, RESP_HEADERS, RESP_BODY.
# Uma única chamada curl (não repete a requisição), essencial para não duplicar
# efeitos colaterais em cenários como o de idempotência.
http_request() {
  local method="$1" url="$2"
  shift 2
  local marker="___HTTP_STATUS___"
  local raw head_body
  raw="$(curl -sS -i -X "$method" "$url" "$@" -w "\n${marker}:%{http_code}" 2>/dev/null)"
  HTTP_STATUS="${raw##*"${marker}":}"
  head_body="${raw%"${marker}":*}"
  RESP_HEADERS="$(printf '%s' "$head_body" | awk '/^\r?$/{exit} {print}')"
  RESP_BODY="$(printf '%s' "$head_body" | awk 'f{print} /^\r?$/{f=1}')"
}

# get_header HEADERS NAME → valor do header (case-insensitive), string vazia se ausente.
get_header() {
  local headers="$1" name="$2" lname
  lname="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
  printf '%s\n' "$headers" | while IFS= read -r line; do
    key="${line%%:*}"
    lkey="$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')"
    if [ "$lkey" = "$lname" ]; then
      value="${line#*:}"
      value="${value# }"
      value="${value%$'\r'}"
      printf '%s' "$value"
      break
    fi
  done
}

# order_payload SKU QTY UNIT_PRICE DELIVERY_TYPE SIMULATE_JSON [CUSTOMER_ID] → corpo do POST /orders.
# CUSTOMER_ID é opcional; se omitido, gera um customerId aleatório (comportamento anterior).
order_payload() {
  local sku="$1" qty="$2" price="$3" delivery="$4" simulate="$5" customer="${6:-}"
  local address_json="null"
  if [ "$delivery" = "PHYSICAL" ]; then
    address_json='{"street":"Av. Paulista","number":"1000","complement":null,"city":"Sao Paulo","state":"SP","zipCode":"01310-100","country":"BR"}'
  fi
  if [ -z "$customer" ]; then
    customer="qa-e2e-$(gen_uuid)"
  fi
  cat <<EOF
{
  "customerId": "$customer",
  "items": [ { "sku": "$sku", "quantity": $qty, "unitPrice": $price } ],
  "deliveryType": "$delivery",
  "shippingAddress": $address_json,
  "simulate": $simulate
}
EOF
}

jaeger_link() {
  local order_id="$1"
  printf '%s/search?service=saga-orchestrator&tags=%%7B%%22orderId%%22%%3A%%22%s%%22%%7D' "$JAEGER_URL" "$order_id"
}

# wait_for_status ORDER_ID TARGET_STATUS TIMEOUT_SEG → poll a cada 1s. Seta LAST_ORDER_JSON.
wait_for_status() {
  local order_id="$1" target="$2" timeout="${3:-60}"
  local start now st
  start=$(date +%s)
  while true; do
    http_request GET "$ORDER_URL/orders/$order_id"
    if [ "$HTTP_STATUS" = "200" ]; then
      LAST_ORDER_JSON="$RESP_BODY"
      st="$(json_get "$RESP_BODY" "status")"
      if [ "$st" = "$target" ]; then
        return 0
      fi
      if { [ "$st" = "CONFIRMED" ] || [ "$st" = "CANCELED" ]; } && [ "$st" != "$target" ]; then
        return 1
      fi
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$timeout" ]; then
      return 1
    fi
    sleep 1
  done
}

# wait_for_stock_value SKU EXPECTED TIMEOUT_SEG → espera o estoque estabilizar
# (compensações são assíncronas), poll a cada 1s.
wait_for_stock_value() {
  local sku="$1" expected="$2" timeout="${3:-20}"
  local start now avail
  start=$(date +%s)
  while true; do
    http_request GET "$INVENTORY_URL/inventory/stock/$sku"
    avail="$(json_get "$RESP_BODY" "available")"
    if [ "$avail" = "$expected" ]; then
      return 0
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$timeout" ]; then
      LAST_STOCK_VALUE="$avail"
      return 1
    fi
    sleep 1
  done
}

wait_for_health_single() {
  local url="$1" timeout="${2:-60}"
  local start now code
  start=$(date +%s)
  while true; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "$url/actuator/health" 2>/dev/null || echo 000)"
    if [ "$code" = "200" ]; then
      return 0
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$timeout" ]; then
      return 1
    fi
    sleep 1
  done
}

wait_for_health() {
  local timeout=180
  local names=(saga-orchestrator order-service inventory-service payment-service shipping-service)
  local urls=("$SAGA_URL" "$ORDER_URL" "$INVENTORY_URL" "$PAYMENT_URL" "$SHIPPING_URL")
  local start now all_up i code
  start=$(date +%s)
  echo "Aguardando /actuator/health dos 5 serviços (timeout ${timeout}s)..."
  while true; do
    all_up=true
    for i in "${!urls[@]}"; do
      code="$(curl -sS -o /dev/null -w '%{http_code}' "${urls[$i]}/actuator/health" 2>/dev/null || echo 000)"
      if [ "$code" != "200" ]; then
        all_up=false
      fi
    done
    if $all_up; then
      echo "Todos os serviços respondendo."
      return 0
    fi
    now=$(date +%s)
    if [ $((now - start)) -ge "$timeout" ]; then
      echo "${C_RED}Timeout aguardando healthcheck.${C_RESET}" >&2
      for i in "${!urls[@]}"; do
        echo "  - ${names[$i]}: ${urls[$i]}/actuator/health" >&2
      done
      return 1
    fi
    sleep 2
  done
}

# --------------------------------------------------------------------------
# Cenários (nomes de function == chaves aceitas como argumento do script)
# --------------------------------------------------------------------------

# 1. Caminho feliz com envio (PHYSICAL) → CONFIRMED com shipment.created.
scenario_happy_path_physical() {
  local idem order_id ship_status
  idem="$(gen_uuid)"
  local payload
  payload="$(order_payload "SKU-BOOK-001" 1 49.90 "PHYSICAL" 'null')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id"
  if ! wait_for_status "$order_id" "CONFIRMED" 60; then
    SCENARIO_DETAIL="não atingiu CONFIRMED em 60s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  if ! history_has "$LAST_ORDER_JSON" "SHIPPING" "SUCCEEDED"; then
    SCENARIO_DETAIL="history sem SHIPPING/SUCCEEDED"
    return 1
  fi
  http_request GET "$SHIPPING_URL/shipments/$order_id"
  if [ "$HTTP_STATUS" != "200" ]; then
    SCENARIO_DETAIL="GET /shipments/$order_id retornou $HTTP_STATUS (esperado 200)"
    return 1
  fi
  ship_status="$(json_get "$RESP_BODY" "status")"
  if [ "$ship_status" != "CREATED" ]; then
    SCENARIO_DETAIL="shipment status=$ship_status (esperado CREATED)"
    return 1
  fi
  SCENARIO_DETAIL="CONFIRMED, shipment CREATED, tracking presente"
  return 0
}

# 2. Pedido sem envio aplicável (DIGITAL) → CONFIRMED sem shipment.created.
scenario_happy_path_digital() {
  local idem order_id
  idem="$(gen_uuid)"
  local payload
  payload="$(order_payload "SKU-EBOOK-001" 1 39.90 "DIGITAL" 'null')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id"
  if ! wait_for_status "$order_id" "CONFIRMED" 60; then
    SCENARIO_DETAIL="não atingiu CONFIRMED em 60s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  if history_has "$LAST_ORDER_JSON" "SHIPPING" "SUCCEEDED"; then
    SCENARIO_DETAIL="history contém SHIPPING/SUCCEEDED em pedido DIGITAL (não deveria haver envio)"
    return 1
  fi
  http_request GET "$SHIPPING_URL/shipments/$order_id"
  if [ "$HTTP_STATUS" != "404" ]; then
    SCENARIO_DETAIL="GET /shipments/$order_id retornou $HTTP_STATUS (esperado 404: nenhum shipment.created)"
    return 1
  fi
  SCENARIO_DETAIL="CONFIRMED sem shipment.created (DIGITAL)"
  return 0
}

# 3. Falha no pagamento → estoque liberado, pedido cancelado.
scenario_payment_failure() {
  local sku="SKU-BOOK-001" idem order_id before
  http_request GET "$INVENTORY_URL/inventory/stock/$sku"
  before="$(json_get "$RESP_BODY" "available")"
  idem="$(gen_uuid)"
  local payload
  payload="$(order_payload "$sku" 1 49.90 "PHYSICAL" '{"payment":"DECLINE"}')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id"
  if ! wait_for_status "$order_id" "CANCELED" 30; then
    SCENARIO_DETAIL="não atingiu CANCELED em 30s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  if [ "$(json_get "$LAST_ORDER_JSON" "cancellationReason")" != "PAYMENT_DECLINED" ]; then
    SCENARIO_DETAIL="cancellationReason=$(json_get "$LAST_ORDER_JSON" "cancellationReason") (esperado PAYMENT_DECLINED)"
    return 1
  fi
  if ! history_has "$LAST_ORDER_JSON" "INVENTORY" "COMPENSATED" "inventory.released"; then
    SCENARIO_DETAIL="history sem INVENTORY/COMPENSATED (inventory.released)"
    return 1
  fi
  http_request GET "$INVENTORY_URL/inventory/reservations/$order_id"
  if [ "$(json_get "$RESP_BODY" "status")" != "RELEASED" ]; then
    SCENARIO_DETAIL="reservation status=$(json_get "$RESP_BODY" "status") (esperado RELEASED)"
    return 1
  fi
  if ! wait_for_stock_value "$sku" "$before" 20; then
    SCENARIO_DETAIL="estoque não voltou a $before em 20s (valor: $LAST_STOCK_VALUE)"
    return 1
  fi
  SCENARIO_DETAIL="CANCELED (PAYMENT_DECLINED), reserva RELEASED, estoque restaurado ($before)"
  return 0
}

# 4. Falha no envio → estorno + liberação + cancelamento.
scenario_shipping_failure() {
  local sku="SKU-BOOK-001" idem order_id before
  http_request GET "$INVENTORY_URL/inventory/stock/$sku"
  before="$(json_get "$RESP_BODY" "available")"
  idem="$(gen_uuid)"
  local payload
  payload="$(order_payload "$sku" 1 49.90 "PHYSICAL" '{"shipping":"FAIL"}')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id"
  if ! wait_for_status "$order_id" "CANCELED" 30; then
    SCENARIO_DETAIL="não atingiu CANCELED em 30s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  if [ "$(json_get "$LAST_ORDER_JSON" "cancellationReason")" != "SHIPMENT_FAILED" ]; then
    SCENARIO_DETAIL="cancellationReason=$(json_get "$LAST_ORDER_JSON" "cancellationReason") (esperado SHIPMENT_FAILED)"
    return 1
  fi
  http_request GET "$PAYMENT_URL/payments/$order_id"
  if [ "$(json_get "$RESP_BODY" "status")" != "REFUNDED" ]; then
    SCENARIO_DETAIL="payment status=$(json_get "$RESP_BODY" "status") (esperado REFUNDED)"
    return 1
  fi
  http_request GET "$INVENTORY_URL/inventory/reservations/$order_id"
  if [ "$(json_get "$RESP_BODY" "status")" != "RELEASED" ]; then
    SCENARIO_DETAIL="reservation status=$(json_get "$RESP_BODY" "status") (esperado RELEASED)"
    return 1
  fi
  if ! wait_for_stock_value "$sku" "$before" 20; then
    SCENARIO_DETAIL="estoque não voltou a $before em 20s (valor: $LAST_STOCK_VALUE)"
    return 1
  fi
  SCENARIO_DETAIL="CANCELED (SHIPMENT_FAILED), payment REFUNDED, reserva RELEASED, estoque restaurado ($before)"
  return 0
}

# 5. Timeout numa etapa (pagamento) → retries esgotados e depois compensação.
scenario_timeout_step() {
  local sku="SKU-BOOK-001" idem order_id before
  http_request GET "$INVENTORY_URL/inventory/stock/$sku"
  before="$(json_get "$RESP_BODY" "available")"
  idem="$(gen_uuid)"
  local payload
  payload="$(order_payload "$sku" 1 49.90 "PHYSICAL" '{"payment":"TIMEOUT"}')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id"
  # defaults: SAGA_STEP_TIMEOUT_MS=5000, SAGA_STEP_MAX_RETRIES=2, backoff exponencial
  # ~ 3 tentativas x 5s + backoff ~ 20-30s; damos margem generosa (90s).
  if ! wait_for_status "$order_id" "CANCELED" 90; then
    SCENARIO_DETAIL="não atingiu CANCELED em 90s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  if [ "$(json_get "$LAST_ORDER_JSON" "cancellationReason")" != "STEP_TIMEOUT" ]; then
    SCENARIO_DETAIL="cancellationReason=$(json_get "$LAST_ORDER_JSON" "cancellationReason") (esperado STEP_TIMEOUT)"
    return 1
  fi
  if ! history_has "$LAST_ORDER_JSON" "PAYMENT" "TIMED_OUT"; then
    SCENARIO_DETAIL="history sem PAYMENT/TIMED_OUT (retry não registrado)"
    return 1
  fi
  # simulate.payment=TIMEOUT autoriza de fato mas não responde: o refund deve
  # estornar uma autorização real (noop=false).
  http_request GET "$PAYMENT_URL/payments/$order_id"
  if [ "$(json_get "$RESP_BODY" "status")" != "REFUNDED" ]; then
    SCENARIO_DETAIL="payment status=$(json_get "$RESP_BODY" "status") (esperado REFUNDED)"
    return 1
  fi
  http_request GET "$INVENTORY_URL/inventory/reservations/$order_id"
  if [ "$(json_get "$RESP_BODY" "status")" != "RELEASED" ]; then
    SCENARIO_DETAIL="reservation status=$(json_get "$RESP_BODY" "status") (esperado RELEASED)"
    return 1
  fi
  if ! wait_for_stock_value "$sku" "$before" 20; then
    SCENARIO_DETAIL="estoque não voltou a $before em 20s (valor: $LAST_STOCK_VALUE)"
    return 1
  fi
  SCENARIO_DETAIL="retries esgotados (TIMED_OUT) -> CANCELED (STEP_TIMEOUT), refund+release aplicados"
  return 0
}

# 6. Reinício do coordenador no meio da saga → retomada e conclusão (sem duplicar efeito).
scenario_coordinator_restart() {
  SCENARIO_SKIP=0
  if [ "$SKIP_RESTART" = "1" ]; then
    SCENARIO_SKIP=1
    SCENARIO_DETAIL="pulado via SKIP_RESTART=1"
    return 0
  fi
  if ! command -v docker >/dev/null 2>&1; then
    SCENARIO_SKIP=1
    SCENARIO_DETAIL="comando docker indisponível neste shell; pulado"
    return 0
  fi
  local idem order_id auth_count pay_status
  idem="$(gen_uuid)"
  local payload
  # payment=SLOW: responde após SIMULATE_SLOW_MS (< SAGA_STEP_TIMEOUT_MS), tempo
  # suficiente para matar o coordenador enquanto o comando está "em voo".
  payload="$(order_payload "SKU-BOOK-001" 1 49.90 "PHYSICAL" '{"payment":"SLOW"}')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id"
  sleep 1
  echo "   ${C_YELLOW}matando saga-orchestrator (docker compose kill)...${C_RESET}"
  docker compose kill saga-orchestrator >/dev/null 2>&1
  sleep 2
  echo "   ${C_YELLOW}subindo saga-orchestrator novamente (docker compose up -d)...${C_RESET}"
  docker compose up -d saga-orchestrator >/dev/null 2>&1
  if ! wait_for_health_single "$SAGA_URL" 60; then
    SCENARIO_DETAIL="saga-orchestrator não voltou saudável em 60s"
    return 1
  fi
  if ! wait_for_status "$order_id" "CONFIRMED" 90; then
    SCENARIO_DETAIL="não atingiu CONFIRMED após restart em 90s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  auth_count="$(history_count "$LAST_ORDER_JSON" "PAYMENT" "SUCCEEDED")"
  if [ "$auth_count" != "1" ]; then
    SCENARIO_DETAIL="esperado exatamente 1 autorização de pagamento no histórico, encontrado $auth_count (possível efeito duplicado)"
    return 1
  fi
  http_request GET "$PAYMENT_URL/payments/$order_id"
  pay_status="$(json_get "$RESP_BODY" "status")"
  if [ "$pay_status" != "AUTHORIZED" ]; then
    SCENARIO_DETAIL="payment status=$pay_status (esperado AUTHORIZED)"
    return 1
  fi
  SCENARIO_DETAIL="saga retomou após restart do coordenador; 1 única autorização de pagamento"
  return 0
}

# 7. Idempotência: mesmo Idempotency-Key duas vezes → mesmo orderId, estoque reduz uma vez.
scenario_idempotency() {
  local sku="SKU-BOOK-001" idem before order_id1 order_id2 replayed expected
  http_request GET "$INVENTORY_URL/inventory/stock/$sku"
  before="$(json_get "$RESP_BODY" "available")"
  idem="$(gen_uuid)"
  local payload
  payload="$(order_payload "$sku" 1 49.90 "PHYSICAL" 'null')"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="1ª chamada retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order_id1="$(json_get "$RESP_BODY" "orderId")"
  SCENARIO_ORDER_ID="$order_id1"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $idem" -d "$payload"
  if [ "$HTTP_STATUS" != "200" ]; then
    SCENARIO_DETAIL="2ª chamada (mesma Idempotency-Key/mesmo corpo) retornou $HTTP_STATUS (esperado 200): $RESP_BODY"
    return 1
  fi
  replayed="$(get_header "$RESP_HEADERS" "Idempotent-Replayed" | tr '[:upper:]' '[:lower:]')"
  order_id2="$(json_get "$RESP_BODY" "orderId")"
  if [ "$order_id2" != "$order_id1" ]; then
    SCENARIO_DETAIL="orderId divergente entre chamadas ($order_id1 vs $order_id2)"
    return 1
  fi
  if [ "$replayed" != "true" ]; then
    SCENARIO_DETAIL="header Idempotent-Replayed ausente/diferente de true na 2ª chamada"
    return 1
  fi
  if ! wait_for_status "$order_id1" "CONFIRMED" 60; then
    SCENARIO_DETAIL="pedido não confirmou em 60s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  expected=$((before - 1))
  if ! wait_for_stock_value "$sku" "$expected" 20; then
    SCENARIO_DETAIL="estoque final=$LAST_STOCK_VALUE, esperado=$expected (reduzido mais de uma vez ou não reduzido)"
    return 1
  fi
  SCENARIO_DETAIL="mesmo orderId nas duas chamadas ($order_id1); Idempotent-Replayed=true; estoque reduzido uma única vez ($before -> $expected)"
  return 0
}

# 8. D1: listar pedidos de um cliente (GET /orders?customerId=&limit=, ADR-006).
scenario_customer_orders() {
  local cust_id order1 order2 order3 payload count
  cust_id="qa-e2e-cust-$(gen_uuid)"

  # Pedido 1: DIGITAL feliz.
  payload="$(order_payload "SKU-EBOOK-001" 1 39.90 "DIGITAL" 'null' "$cust_id")"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $(gen_uuid)" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="pedido 1 (DIGITAL) POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order1="$(json_get "$RESP_BODY" "orderId")"
  if ! wait_for_status "$order1" "CONFIRMED" 60; then
    SCENARIO_DETAIL="pedido 1 (DIGITAL) não atingiu CONFIRMED em 60s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi

  # Pedido 2: PHYSICAL feliz.
  payload="$(order_payload "SKU-BOOK-001" 1 49.90 "PHYSICAL" 'null' "$cust_id")"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $(gen_uuid)" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="pedido 2 (PHYSICAL) POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order2="$(json_get "$RESP_BODY" "orderId")"
  if ! wait_for_status "$order2" "CONFIRMED" 60; then
    SCENARIO_DETAIL="pedido 2 (PHYSICAL) não atingiu CONFIRMED em 60s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi

  # Pedido 3: PHYSICAL com payment=DECLINE (cancelado).
  payload="$(order_payload "SKU-BOOK-001" 1 49.90 "PHYSICAL" '{"payment":"DECLINE"}' "$cust_id")"
  http_request POST "$ORDER_URL/orders" -H "Content-Type: application/json" -H "Idempotency-Key: $(gen_uuid)" -d "$payload"
  if [ "$HTTP_STATUS" != "202" ]; then
    SCENARIO_DETAIL="pedido 3 (DECLINE) POST /orders retornou $HTTP_STATUS (esperado 202): $RESP_BODY"
    return 1
  fi
  order3="$(json_get "$RESP_BODY" "orderId")"
  if ! wait_for_status "$order3" "CANCELED" 30; then
    SCENARIO_DETAIL="pedido 3 (DECLINE) não atingiu CANCELED em 30s (status atual: $(json_get "$LAST_ORDER_JSON" "status"))"
    return 1
  fi
  SCENARIO_ORDER_ID="$order3"

  # GET /orders?customerId= sem limit → exatamente os 3, mais recente primeiro.
  http_request GET "$ORDER_URL/orders?customerId=$cust_id"
  if [ "$HTTP_STATUS" != "200" ]; then
    SCENARIO_DETAIL="GET /orders?customerId=$cust_id retornou $HTTP_STATUS (esperado 200)"
    return 1
  fi
  count="$(json_array_length "$RESP_BODY")"
  if [ "$count" != "3" ]; then
    SCENARIO_DETAIL="GET /orders?customerId= retornou $count pedidos (esperado 3)"
    return 1
  fi
  if [ "$(json_array_field "$RESP_BODY" 0 orderId)" != "$order3" ] || \
     [ "$(json_array_field "$RESP_BODY" 1 orderId)" != "$order2" ] || \
     [ "$(json_array_field "$RESP_BODY" 2 orderId)" != "$order1" ]; then
    SCENARIO_DETAIL="ordem incorreta (esperado mais recente->mais antigo: $order3,$order2,$order1; obtido: $(json_array_field "$RESP_BODY" 0 orderId),$(json_array_field "$RESP_BODY" 1 orderId),$(json_array_field "$RESP_BODY" 2 orderId))"
    return 1
  fi
  # Campos do contrato no elemento mais recente (pedido 3, CANCELED).
  if [ -z "$(json_array_field "$RESP_BODY" 0 orderId)" ] || \
     [ "$(json_array_field "$RESP_BODY" 0 status)" != "CANCELED" ] || \
     [ -z "$(json_array_field "$RESP_BODY" 0 totalAmount)" ] || \
     [ "$(json_array_field "$RESP_BODY" 0 deliveryType)" != "PHYSICAL" ] || \
     [ -z "$(json_array_field "$RESP_BODY" 0 createdAt)" ] || \
     [ "$(json_array_field "$RESP_BODY" 0 cancellationReason)" != "PAYMENT_DECLINED" ]; then
    SCENARIO_DETAIL="campos do contrato ausentes/incorretos no pedido mais recente"
    return 1
  fi
  # cancellationReason deve ser null (vazio) num pedido CONFIRMED (índice 1, pedido 2).
  if [ -n "$(json_array_field "$RESP_BODY" 1 cancellationReason)" ]; then
    SCENARIO_DETAIL="cancellationReason não é null no pedido CONFIRMED (índice 1)"
    return 1
  fi

  # limit=2 → só os 2 mais recentes, mesma ordem.
  http_request GET "$ORDER_URL/orders?customerId=$cust_id&limit=2"
  if [ "$HTTP_STATUS" != "200" ]; then
    SCENARIO_DETAIL="GET /orders?customerId=&limit=2 retornou $HTTP_STATUS (esperado 200)"
    return 1
  fi
  count="$(json_array_length "$RESP_BODY")"
  if [ "$count" != "2" ]; then
    SCENARIO_DETAIL="limit=2 retornou $count pedidos (esperado 2)"
    return 1
  fi
  if [ "$(json_array_field "$RESP_BODY" 0 orderId)" != "$order3" ] || [ "$(json_array_field "$RESP_BODY" 1 orderId)" != "$order2" ]; then
    SCENARIO_DETAIL="limit=2 não retornou os 2 pedidos mais recentes na ordem esperada"
    return 1
  fi

  # Cliente inexistente → [] (nunca 404).
  http_request GET "$ORDER_URL/orders?customerId=qa-e2e-cust-inexistente-$(gen_uuid)"
  if [ "$HTTP_STATUS" != "200" ]; then
    SCENARIO_DETAIL="GET /orders?customerId=<inexistente> retornou $HTTP_STATUS (esperado 200)"
    return 1
  fi
  count="$(json_array_length "$RESP_BODY")"
  if [ "$count" != "0" ]; then
    SCENARIO_DETAIL="cliente inexistente retornou $count pedidos (esperado [] / 0)"
    return 1
  fi

  # Sem customerId → 400.
  http_request GET "$ORDER_URL/orders"
  if [ "$HTTP_STATUS" != "400" ]; then
    SCENARIO_DETAIL="GET /orders sem customerId retornou $HTTP_STATUS (esperado 400)"
    return 1
  fi

  SCENARIO_DETAIL="3 pedidos do cliente $cust_id listados na ordem correta (mais recente->mais antigo); limit=2 ok; cliente inexistente=[]; sem customerId=400"
  return 0
}

# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

run_scenario() {
  local key="$1" fn="$2"
  local start end duration label color detail_json orderid_json
  echo
  echo "${C_BOLD}=============================================="
  echo "Cenário: $key"
  echo "==============================================${C_RESET}"
  SCENARIO_ORDER_ID=""
  SCENARIO_DETAIL=""
  SCENARIO_SKIP=0
  start=$(date +%s)
  if "$fn"; then
    if [ "$SCENARIO_SKIP" = "1" ]; then
      label="SKIP"; color="$C_YELLOW"
    else
      label="PASS"; color="$C_GREEN"
    fi
  else
    label="FAIL"; color="$C_RED"
  fi
  end=$(date +%s)
  duration=$((end - start))
  case "$label" in
    PASS) COUNT_PASS=$((COUNT_PASS + 1)); printf '%s✔ %s — %ss%s' "$color" "$key" "$duration" "$C_RESET" ;;
    FAIL) COUNT_FAIL=$((COUNT_FAIL + 1)); OVERALL_EXIT=1; printf '%s✘ %s — %ss%s' "$color" "$key" "$duration" "$C_RESET" ;;
    SKIP) COUNT_SKIP=$((COUNT_SKIP + 1)); printf '%s⏭ %s — pulado%s' "$color" "$key" "$C_RESET" ;;
  esac
  if [ -n "$SCENARIO_ORDER_ID" ]; then
    printf ' — orderId=%s' "$SCENARIO_ORDER_ID"
  fi
  echo
  if [ -n "$SCENARIO_DETAIL" ]; then
    echo "   detalhe: $SCENARIO_DETAIL"
  fi
  if [ -n "$SCENARIO_ORDER_ID" ]; then
    echo "   jaeger:  $(jaeger_link "$SCENARIO_ORDER_ID")"
    echo "   GET /orders/$SCENARIO_ORDER_ID  →  $ORDER_URL/orders/$SCENARIO_ORDER_ID"
  fi

  if [ -n "$SCENARIO_ORDER_ID" ]; then
    orderid_json="\"$(json_escape "$SCENARIO_ORDER_ID")\""
  else
    orderid_json="null"
  fi
  if [ -n "$SCENARIO_DETAIL" ]; then
    detail_json="\"$(json_escape "$SCENARIO_DETAIL")\""
  else
    detail_json="null"
  fi
  RESULTS+=("{\"scenario\":\"$(json_escape "$key")\",\"status\":\"$label\",\"durationSeconds\":$duration,\"orderId\":$orderid_json,\"detail\":$detail_json}")
}

write_report() {
  local n=${#RESULTS[@]} i
  {
    echo "["
    for i in "${!RESULTS[@]}"; do
      if [ "$i" -lt $((n - 1)) ]; then
        echo "  ${RESULTS[$i]},"
      else
        echo "  ${RESULTS[$i]}"
      fi
    done
    echo "]"
  } > "$REPORT_FILE"
  echo
  echo "Relatório: $REPORT_FILE"
}

print_summary() {
  echo
  echo "${C_BOLD}================ Resumo ================${C_RESET}"
  echo "  ${C_GREEN}PASS: $COUNT_PASS${C_RESET}  ${C_RED}FAIL: $COUNT_FAIL${C_RESET}  ${C_YELLOW}SKIP: $COUNT_SKIP${C_RESET}"
  if [ "$OVERALL_EXIT" -ne 0 ]; then
    echo "  ${C_RED}Resultado: FALHOU${C_RESET}"
  else
    echo "  ${C_GREEN}Resultado: OK${C_RESET}"
  fi
  echo "${C_BOLD}==========================================${C_RESET}"
}

main() {
  local filter="${1:-}"
  local keys=(happy_path_physical happy_path_digital payment_failure shipping_failure timeout_step coordinator_restart idempotency customer_orders)
  local k found

  if [ -n "$filter" ]; then
    found=0
    for k in "${keys[@]}"; do
      [ "$k" = "$filter" ] && found=1
    done
    if [ "$found" -eq 0 ]; then
      echo "Cenário desconhecido: $filter" >&2
      echo "Disponíveis: ${keys[*]}" >&2
      exit 2
    fi
  fi

  if ! wait_for_health; then
    echo "Abortando: nem todos os serviços ficaram saudáveis a tempo." >&2
    exit 1
  fi

  for k in "${keys[@]}"; do
    if [ -n "$filter" ] && [ "$filter" != "$k" ]; then
      continue
    fi
    run_scenario "$k" "scenario_$k"
  done

  write_report
  print_summary
  exit "$OVERALL_EXIT"
}

main "$@"
