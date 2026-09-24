#!/usr/bin/env python3
"""D15 (`518f89f27ae8`) — R6/F4: `tests/e2e/run.sh` nunca roda `docker compose` sem `-p` e, fora do CI, não reinicia
o saga-orchestrator do produtivo (`checkout-saga`) sem `E2E_ALLOW_PROD=1` (contrato ambiente-de-teste §7, CA17).

Nada real é tocado: o `docker` do PATH é um script FALSO que só registra os argumentos, e os serviços são um servidor
HTTP falso em 127.0.0.1 (porta aleatória). O `run.sh` roda de verdade (`bash tests/e2e/run.sh coordinator_restart`),
com o relatório redirecionado para um arquivo temporário (E2E_REPORT_FILE).

Uso: python3 tests/squad/test_e2e_compose_seguro_d15.py   (ou python3 -m unittest tests.squad.test_e2e_compose_seguro_d15)
"""
import json
import os
import pathlib
import re
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parents[2]
RUN_SH = REPO / "tests/e2e/run.sh"
ORDER_ID = "00000000-0000-0000-0000-00000000e2e6"


class FakeServices(BaseHTTPRequestHandler):
    """Responde como os 5 serviços: health 200, POST /orders 202, pedido CONFIRMED com 1 autorização."""
    requests: list = []

    def log_message(self, *a):
        pass

    def _send(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        FakeServices.requests.append(("GET", self.path))
        if self.path.endswith("/actuator/health"):
            return self._send(200, {"status": "UP"})
        if self.path == f"/orders/{ORDER_ID}":
            return self._send(200, {"orderId": ORDER_ID, "status": "CONFIRMED",
                                    "history": [{"step": "PAYMENT", "status": "SUCCEEDED"}]})
        if self.path == f"/payments/{ORDER_ID}":
            return self._send(200, {"orderId": ORDER_ID, "status": "AUTHORIZED"})
        return self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        FakeServices.requests.append(("POST", self.path))
        return self._send(202, {"orderId": ORDER_ID})


class E2EComposeSeguro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeServices)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        FakeServices.requests = []
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="e2e-compose-d15-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.docker_log = self.tmp / "docker.log"
        fake = self.bin / "docker"
        # docker FALSO: grava os argumentos (separados por TAB) e sai 0; nunca chama o docker real.
        fake.write_text('#!/usr/bin/env bash\n'
                        f'( IFS=$\'\\t\'; printf \'%s\\n\' "$*" ) >> "{self.docker_log}"\n'
                        'exit 0\n')
        fake.chmod(0o755)
        self.report = self.tmp / "report.json"

    def env(self, **over):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("E2E_") and k not in ("CI", "SKIP_RESTART", "COMPOSE_PROJECT_NAME")}
        env.update(PATH=f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                   ORDER_URL=self.base, SAGA_URL=self.base, INVENTORY_URL=self.base, PAYMENT_URL=self.base,
                   SHIPPING_URL=self.base, JAEGER_URL=self.base, E2E_REPORT_FILE=str(self.report))
        env.update(over)
        return env

    def docker_calls(self):
        if not self.docker_log.exists():
            return []
        return [line.split("\t") for line in self.docker_log.read_text().splitlines() if line]

    def run_restart(self, **over):
        r = subprocess.run(["bash", str(RUN_SH), "coordinator_restart"], cwd=REPO, env=self.env(**over),
                           capture_output=True, text=True, timeout=120)
        report = json.loads(self.report.read_text())
        self.assertEqual(len(report["scenarios"]), 1, r.stdout + r.stderr)
        return r, report["scenarios"][0]

    def assert_all_with_p(self, calls, project):
        self.assertTrue(calls)
        for c in calls:
            self.assertEqual(c[:3], ["compose", "-p", project], c)
            self.assertFalse({"up", "down", "rm", "-v", "--volumes", "--force-recreate", "--remove-orphans",
                              "restart", "create", "build"} & set(c), c)

    # ------------------------------------------------------------------ estático
    def test_unico_ponto_que_chama_docker(self):
        """Nenhuma linha executável chama 'docker' fora de e2e_compose (comentários e echo não contam)."""
        calls = []
        for n, line in enumerate(RUN_SH.read_text().splitlines(), 1):
            code = line.strip()
            if not code or code.startswith("#") or code.startswith("echo ") or "SCENARIO_DETAIL=" in code:
                continue
            if re.search(r'(^|[;&|(]\s*)docker(\s|$)', code):
                calls.append((n, code))
        self.assertEqual([c for _, c in calls], ['docker "${args[@]}" "$@"'], calls)
        body = RUN_SH.read_text()
        fn = re.search(r"e2e_compose\(\) \{(.*?)\n\}", body, re.S).group(1)
        self.assertIn('args=(compose -p "$E2E_COMPOSE_PROJECT")', fn)
        self.assertNotIn("up -d saga-orchestrator", body)

    # ------------------------------------------------------------------ run.sh de verdade, docker falso
    def test_teste_usa_p_checkout_teste_e_env_file_kill_start(self):
        r, sc = self.run_restart(E2E_COMPOSE_PROJECT="checkout-teste", E2E_COMPOSE_ENV_FILE="infra/teste/teste.env",
                                 COMPOSE_PROJECT_NAME="checkout-saga")
        self.assertEqual(sc["status"], "PASS", r.stdout + r.stderr)
        calls = self.docker_calls()
        prefix = ["compose", "-p", "checkout-teste", "--env-file", "infra/teste/teste.env"]
        self.assertEqual(calls, [prefix + ["kill", "saga-orchestrator"], prefix + ["start", "saga-orchestrator"]])
        self.assertNotIn("checkout-saga", self.docker_log.read_text())
        self.assert_all_with_p(calls, "checkout-teste")

    def test_produtivo_fora_do_ci_e_pulado_sem_docker_nem_pedido(self):
        r, sc = self.run_restart()
        self.assertEqual(sc["status"], "SKIP", r.stdout + r.stderr)
        self.assertIn("E2E_ALLOW_PROD", sc["detail"])
        self.assertEqual(self.docker_calls(), [])
        self.assertFalse([q for q in FakeServices.requests if q[0] == "POST"])      # nem cria pedido

    def test_produtivo_explicito_sem_allow_tambem_pulado(self):
        _, sc = self.run_restart(E2E_COMPOSE_PROJECT="checkout-saga", E2E_ALLOW_PROD="0")
        self.assertEqual(sc["status"], "SKIP")
        self.assertEqual(self.docker_calls(), [])

    def test_ci_reinicia_com_p_checkout_saga(self):
        r, sc = self.run_restart(CI="true")
        self.assertEqual(sc["status"], "PASS", r.stdout + r.stderr)
        self.assertEqual(self.docker_calls(), [["compose", "-p", "checkout-saga", "kill", "saga-orchestrator"],
                                               ["compose", "-p", "checkout-saga", "start", "saga-orchestrator"]])

    def test_allow_prod_local_reinicia_com_p_checkout_saga(self):
        _, sc = self.run_restart(E2E_ALLOW_PROD="1")
        self.assertEqual(sc["status"], "PASS")
        self.assert_all_with_p(self.docker_calls(), "checkout-saga")

    def test_skip_restart_nao_chama_docker(self):
        _, sc = self.run_restart(SKIP_RESTART="1", E2E_COMPOSE_PROJECT="checkout-teste")
        self.assertEqual(sc["status"], "SKIP")
        self.assertEqual(self.docker_calls(), [])

    def test_last_report_do_repo_nao_e_sobrescrito(self):
        real = REPO / "tests/e2e/last-report.json"
        before = real.read_bytes() if real.exists() else None
        self.run_restart(E2E_COMPOSE_PROJECT="checkout-teste")
        self.assertEqual(real.read_bytes() if real.exists() else None, before)

    # ------------------------------------------------------------------ funções isoladas (source)
    def bash_fn(self, script, **over):
        return subprocess.run(["bash", "-c", f'source "{RUN_SH}"; {script}'], cwd=REPO, env=self.env(**over),
                              capture_output=True, text=True, timeout=30)

    def test_source_nao_executa_a_suite(self):
        r = self.bash_fn("echo carregado")
        self.assertEqual(r.stdout.strip().splitlines()[-1], "carregado")
        self.assertFalse(FakeServices.requests)
        self.assertEqual(self.docker_calls(), [])

    def test_restart_coordinator_isolado(self):
        self.bash_fn("restart_coordinator", E2E_COMPOSE_PROJECT="checkout-teste")
        self.assertEqual([c[:5] for c in self.docker_calls()],
                         [["compose", "-p", "checkout-teste", "kill", "saga-orchestrator"],
                          ["compose", "-p", "checkout-teste", "start", "saga-orchestrator"]])

    def test_restart_allowed(self):
        cases = [({}, "1"), ({"CI": "true"}, "0"), ({"E2E_ALLOW_PROD": "1"}, "0"),
                 ({"E2E_COMPOSE_PROJECT": "checkout-teste"}, "0")]
        for over, rc in cases:
            r = self.bash_fn('restart_allowed; echo "rc=$?"', **over)
            self.assertIn(f"rc={rc}", r.stdout, over)
        r = self.bash_fn('E2E_COMPOSE_PROJECT=""; restart_allowed; echo "rc=$? $SCENARIO_DETAIL"')
        self.assertIn("rc=1", r.stdout)
        self.assertIn("-p", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
