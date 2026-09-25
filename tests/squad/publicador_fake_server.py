#!/usr/bin/env python3
"""Servidor falso do Squad Control para os testes do publicador (D24, contrato publicacao-do-squad-control §10).

Uso: `SQUAD_PUBLISH_COMMAND='["python3", "tests/squad/publicador_fake_server.py", "--port", "{port}"]'` — o cwd é a
raiz da cópia (principal ou `plankton-squad-prev`), então cada commit carrega o seu próprio modo.

Modo (arquivo versionado `tests/squad/publicador_fake_mode.txt` no cwd; ausente = `ok`), só com `SQUAD_ENV=produtivo`
(o candidato do pré-voo roda com `SQUAD_ENV=teste` e sempre responde bem, como um erro que só aparece com dados reais):
  ok                  responde 200 em /api/instance, /api/state, /api/live, / e /api/conversas
  quebrado-no-import  sai com código 1 antes de abrir a porta (também no candidato: barrado no pré-voo)
  sai-apos-3s         sai com código 3 três segundos depois de subir
  commit-errado       /api/instance anuncia um commit que não é o do cwd (saúde *depois* falha)
Controles em tempo de execução (`$SQUAD_FAKE_CTL/`, fora do git):
  busy_until          epoch (float): /api/conversas devolve `busy` até esse instante (ocupado-por-30s = agora+30)
  break_produtivo     presente: todo servidor produtivo sai com código 4 ao subir (novo E anterior quebrados, CA-22)
Cada subida anexa uma linha JSON em `$SQUAD_FAKE_CTL/starts.jsonl` (pid, modo, commit, ambiente, SQUAD_SUPERVISED).
"""
import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
a = ap.parse_args()
cwd = pathlib.Path.cwd()
env_name = os.environ.get("SQUAD_ENV") or "produtivo"
prod = env_name == "produtivo"
mf = cwd / "tests/squad/publicador_fake_mode.txt"
mode = mf.read_text().strip() if mf.exists() else "ok"
ctl = pathlib.Path(os.environ.get("SQUAD_FAKE_CTL") or cwd / ".squad/fake-ctl")
ctl.mkdir(parents=True, exist_ok=True)
commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True).stdout.strip()
with (ctl / "starts.jsonl").open("a") as f:
    f.write(json.dumps({"pid": os.getpid(), "mode": mode, "commit": commit, "env": env_name, "cwd": str(cwd),
                        "supervised": os.environ.get("SQUAD_SUPERVISED"),
                        "publishMode": os.environ.get("SQUAD_PUBLISH_MODE"), "t": time.time()}) + "\n")
if mode == "quebrado-no-import":
    print("ModuleNotFoundError: No module named 'conversa_inexistente' (falso)", file=sys.stderr)
    sys.exit(1)
if prod and (ctl / "break_produtivo").exists():
    print("quebrado por break_produtivo (falso)", file=sys.stderr)
    sys.exit(4)
announced = "0" * 40 if (prod and mode == "commit-errado") else commit


def busy():
    try:
        until = float((ctl / "busy_until").read_text().strip())
    except (OSError, ValueError):
        return None
    return {"conversa": "c-fake", "turn": 1} if time.time() < until else None


class H(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = (json.dumps(obj) if not isinstance(obj, str) else obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/instance":
            return self._send(200, {"environment": {"name": env_name, "root": str(cwd), "port": a.port},
                                    "build": {"commitFull": announced, "commit": announced[:7],
                                              "display": f"falso · {announced[:7]}",
                                              "mode": os.environ.get("SQUAD_PUBLISH_MODE") or "principal",
                                              "pid": os.getpid()},
                                    "freshness": {"state": "revertido" if os.environ.get("SQUAD_PUBLISH_REVERTED")
                                                  else "atual",
                                                  "failedCommit": (os.environ.get("SQUAD_PUBLISH_REVERTED") or "")[:7]
                                                  or None}})
        if p == "/api/conversas":
            return self._send(200, {"conversas": [], "busy": busy()})
        if p in ("/api/state", "/api/live"):
            return self._send(200, {"ok": True})
        if p == "/":
            return self._send(200, f"<title>falso {commit[:7]}</title>", "text/html")
        return self._send(404, {"code": "nao_encontrado"})


httpd = ThreadingHTTPServer(("127.0.0.1", a.port), H)
signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=httpd.shutdown, daemon=True).start())
if prod and mode == "sai-apos-3s":
    threading.Timer(3.0, lambda: os._exit(3)).start()
httpd.serve_forever()
sys.exit(0)
