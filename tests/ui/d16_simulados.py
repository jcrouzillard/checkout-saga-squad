#!/usr/bin/env python3
"""D16 (`841f9a27e64a`) — simuladores do fluxo de UI das demandas de bug (QA). Nada real é tocado.

  python3 tests/ui/d16_simulados.py prod <porta>     Jaeger + Grafana + Prometheus do "produtivo" SIMULADOS
                                                      (SQUAD_PROD_JAEGER/GRAFANA/PROMETHEUS=http://127.0.0.1:<porta>)
  python3 tests/ui/d16_simulados.py docker <args…>   executor `docker` falso (SQUAD_DOCKER=tests/ui/d16-docker-simulado):
                                                      `compose -p checkout-saga logs …` devolve o corpus sintético de
                                                      tests/squad/d16_corpus.py; qualquer outro comando falha (rc 1)
  python3 tests/ui/d16_simulados.py files <dir>      grava os arquivos de upload do fluxo (log do corpus, PNG com tEXt,
                                                      log de 500 linhas, log com segredo em chave desconhecida)
"""
import json
import pathlib
import struct
import sys
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "squad"))
import d16_corpus as corpus  # noqa: E402

TID = corpus.TRACE_ID
TRACE = {
    "traceID": TID,
    "processes": {"p1": {"serviceName": "order-service"}, "p2": {"serviceName": "shipping-service"}},
    "spans": [
        {"traceID": TID, "spanID": "aaaaaaaaaaaaaaa1", "operationName": "POST /api/orders", "references": [],
         "startTime": 1790282541550706, "duration": 250000, "processID": "p1",
         "tags": [{"key": "http.request.method", "value": "POST"}, {"key": "http.route", "value": "/api/orders"},
                  {"key": "http.response.status_code", "value": 500}, {"key": "client.address", "value": "203.0.113.9"},
                  {"key": "url.path", "value": "/api/orders?customerId=c-555"}], "logs": []},
        {"traceID": TID, "spanID": "aaaaaaaaaaaaaaa2", "operationName": "shipping.commands process",
         "references": [{"refType": "CHILD_OF", "spanID": "aaaaaaaaaaaaaaa1"}],
         "startTime": 1790282541600706, "duration": 120000, "processID": "p2",
         "tags": [{"key": "otel.status_code", "value": "ERROR"},
                  {"key": "otel.status_description", "value": "endereço inválido"}],
         "logs": [{"timestamp": 1790282541700706, "fields": [
             {"key": "event", "value": "exception"}, {"key": "exception.type", "value": "java.lang.IllegalStateException"},
             {"key": "exception.message", "value": "endereço inválido <img src=x onerror=\"window.__xss=2\">"},
             {"key": "exception.stacktrace", "value": "java.lang.IllegalStateException: endereço inválido: "
                                                      + corpus.ADDRESS_TOSTRING + "\n\tat com.checkout.shipping.X.y(X.java:70)"}]}]},
    ]}
DASHBOARD = {"uid": "checkout-saga", "title": "Checkout Saga", "panels": [
    {"id": 3, "type": "stat", "title": "Taxa de sucesso (%)", "targets": [{"expr": "100 * sum(rate(saga_completed_total{outcome=\"CONFIRMED\"}[5m])) / sum(rate(saga_completed_total[5m]))"}],
     "fieldConfig": {"defaults": {"unit": "percent", "thresholds": {"steps": [{"color": "red", "value": None}, {"color": "green", "value": 95}]}}}}]}


class Prod(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == f"/api/traces/{TID}":
            return self._send({"data": [TRACE]})
        if u.path.startswith("/api/traces/"):
            return self._send({"data": None, "errors": [{"code": 404, "msg": "trace not found"}]}, 404)
        if u.path == "/api/dashboards/uid/checkout-saga":
            return self._send({"dashboard": DASHBOARD})
        if u.path == "/api/v1/query_range":
            start = float(parse_qs(u.query)["start"][0])
            return self._send({"status": "success", "data": {"resultType": "matrix", "result": [
                {"metric": {"outcome": "CONFIRMED"}, "values": [[start, "90"], [start + 60, "97.5"]]}]}})
        return self._send({"message": "not found"}, 404)


def png(text=True) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    w = h = 8
    raw = b"".join(b"\x00" + bytes([200, 40, 40]) * w for _ in range(h))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    if text:
        out += chunk(b"tEXt", b"Author\x00ana.ficticia@exemplo.com.br")
    return out + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def files(d: pathlib.Path):
    d.mkdir(parents=True, exist_ok=True)
    (d / "order-service.log").write_text("\n".join(corpus.lines()) + "\n", encoding="utf-8")
    (d / "tela-erro.png").write_bytes(png())
    (d / "longo.log").write_text("".join(f"linha {i:03d} ok\n" for i in range(500)) + "SEGREDO_NA_LINHA_501 senha=nao-aparece-na-previa\n")
    (d / "squad-control.log").write_text('{"level":"ERROR","message":"POST /api/demand 500","pwd":"abc123","auth":"xyz789"}\n')


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prod":
        ThreadingHTTPServer(("127.0.0.1", int(sys.argv[2])), Prod).serve_forever()
    elif mode == "docker":
        args = sys.argv[2:]
        if args[:3] == ["compose", "-p", "checkout-saga"] and "logs" in args:
            sys.stdout.write(corpus.compose_output(TID))
            sys.exit(0)
        sys.stderr.write("docker simulado: comando não simulado\n")
        sys.exit(1)
    elif mode == "files":
        files(pathlib.Path(sys.argv[2]))
    else:
        sys.exit(__doc__)
