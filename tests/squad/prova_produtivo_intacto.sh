#!/usr/bin/env bash
# D15 (518f89f27ae8) — CA1/CA4 como evidência repetível. SOMENTE LEITURA: só usa "docker ps", "docker inspect",
# "docker volume inspect", "docker image ls" e "docker compose -p checkout-saga config" (nada sobe, para, recria,
# faz build ou apaga).
#
# O que prova:
#   CA1  o docker-compose.yml DESTA cópia (branch), resolvido com o .env da cópia principal, gera o mesmo
#        "config --hash" que o compose da cópia principal, e ambos batem com o rótulo
#        com.docker.compose.config-hash de cada container do checkout-saga em execução
#        (= o merge não recria nenhum serviço do produtivo por mudança de compose).
#   CA4  grava o prod-fingerprint (ids, imagens, StartedAt, RestartCount, portas, volume pgdata) e, com --compare,
#        compara com um fingerprint anterior (antes × depois de uma suíte/ciclo do teste).
#
# Uso:
#   bash tests/squad/prova_produtivo_intacto.sh <saida.json>                      # "antes"
#   bash tests/squad/prova_produtivo_intacto.sh <saida.json> --compare <antes.json> # "depois"
# Variáveis: SQUAD_MAIN_ROOT (cópia principal; default = worktree do git em develop).
# Saída: 0 = tudo idêntico; 1 = divergência (detalhada no stdout); 2 = uso/ambiente.

set -uo pipefail
PROD=checkout-saga
OUT="${1:-}"
COMPARE=""
if [ "${2:-}" = "--compare" ]; then COMPARE="${3:-}"; fi
if [ -z "$OUT" ] || { [ "${2:-}" = "--compare" ] && [ -z "$COMPARE" ]; }; then
  echo "uso: $0 <saida.json> [--compare <antes.json>]" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAIN="${SQUAD_MAIN_ROOT:-}"
if [ -z "$MAIN" ]; then
  MAIN="$(git -C "$HERE" worktree list --porcelain | awk '/^worktree /{w=substr($0,10)} /^branch refs\/heads\/develop$/{print w; exit}')"
fi
if [ -z "$MAIN" ] || [ ! -f "$MAIN/docker-compose.yml" ]; then
  echo "cópia principal não encontrada (defina SQUAD_MAIN_ROOT)" >&2
  exit 2
fi

TMPD="$(mktemp -d)"
trap 'rm -rf "$TMPD"' EXIT
FAIL=0

# 1) hashes do compose da cópia principal e do compose desta cópia (branch) com o .env da principal
( cd "$MAIN" && docker compose -p "$PROD" config --hash '*' ) | sort > "$TMPD/main.hash" || FAIL=1
docker compose -p "$PROD" -f "$HERE/docker-compose.yml" --project-directory "$MAIN" config --hash '*' \
  | sort > "$TMPD/branch.hash" || FAIL=1
# 2) rótulo config-hash dos containers do produtivo (só leitura)
docker ps -a --filter "label=com.docker.compose.project=$PROD" \
  --format '{{.Label "com.docker.compose.service"}} {{.Label "com.docker.compose.config-hash"}}' \
  | sort > "$TMPD/running.hash" || FAIL=1

echo "cópia principal: $MAIN"
echo "esta cópia:      $HERE"
if [ ! -s "$TMPD/main.hash" ] || [ ! -s "$TMPD/running.hash" ]; then
  echo "FALHA: não foi possível ler os hashes (docker indisponível?)"
  exit 2
fi
if cmp -s "$TMPD/main.hash" "$TMPD/branch.hash"; then
  echo "OK   config --hash: compose da branch == compose da cópia principal ($(wc -l < "$TMPD/main.hash" | tr -d ' ') serviços)"
else
  echo "FALHA config --hash: compose da branch difere do da cópia principal:"
  diff "$TMPD/main.hash" "$TMPD/branch.hash"
  FAIL=1
fi
while read -r svc hash; do
  want="$(awk -v s="$svc" '$1==s{print $2}' "$TMPD/main.hash")"
  if [ "$hash" = "$want" ]; then
    echo "OK   $svc: container em execução com o config-hash do compose ($hash)"
  else
    echo "FALHA $svc: container=$hash compose=${want:-<ausente>} (seria recriado)"
    FAIL=1
  fi
done < "$TMPD/running.hash"

# 3) prod-fingerprint (CA4) e comparação opcional
SQUAD_MAIN_ROOT="$MAIN" python3 "$HERE/tools/squad/testenv.py" prod-fingerprint --out "$OUT" > /dev/null || FAIL=1
if ! python3 - "$OUT" <<'EOF'
import json, sys
fp = json.load(open(sys.argv[1]))
ok = all(c.get("configHashMatchesMain") for c in fp["containers"])
print(f"fingerprint: digest {fp['digest']}, {len(fp['containers'])} containers, "
      f"pgdata CreatedAt {fp.get('volume', {}).get('createdAt')}, configHashMatchesMain em todos: {ok}")
sys.exit(0 if ok else 1)
EOF
then
  FAIL=1
fi
if [ -n "$COMPARE" ]; then
  if SQUAD_MAIN_ROOT="$MAIN" python3 "$HERE/tools/squad/testenv.py" prod-fingerprint --compare "$COMPARE"; then
    echo "OK   prod-fingerprint idêntico ao de $COMPARE"
  else
    echo "FALHA prod-fingerprint mudou em relação a $COMPARE"
    FAIL=1
  fi
fi

if [ "$FAIL" -eq 0 ]; then echo "RESULTADO: produtivo intacto"; else echo "RESULTADO: DIVERGÊNCIA"; fi
exit "$FAIL"
