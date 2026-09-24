#!/usr/bin/env python3
"""D15 (`518f89f27ae8`) — ambiente de teste compartilhado e atualização do produtivo (ADR-018).

Tudo com EXECUTOR FALSO (só registra os comandos) e log temporário (SQUAD_ROOT_DATA/SQUAD_LOG): nenhum container,
imagem, volume ou rede é criado, parado ou apagado. Cobre: fila, 409 sem PR, publicação, liberação e próximo da fila,
pedido obsoleto, reset só com APAGAR, guard de portas (R8) e de imagens (R1), desatualizado, divergente/A4/A5/B5,
fingerprint do produtivo, prod.py (só o alterado, nada para docs, R5 compose, rollback R3, B5 com migração R4,
baseline R2, SQUAD_PROD_AUTOUPDATE=0) e CA16 (nenhum comando destrutivo gerado).

Escrito pelo Orquestrador (F2/F5) e ADOTADO pelo QA no G3 da D15, que acrescentou: reset-data/down/publish/release com
o lock tomado (nada executado, pedido fica pendente), cancel pela API (202, duplicate, 404, 400) e
gitflow.after_review (prod.py só com delivered + develop + SQUAD_PROD_AUTOUPDATE != 0). O e2e seguro (R6) está em
test_e2e_compose_seguro_d15.py e a prova CA1/CA4 em prova_produtivo_intacto.sh.

Uso: python3 tests/squad/test_ambiente_teste_d15.py   (ou pytest)
"""
import importlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parents[2]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="squad-d15-")).resolve()
LOG = TMP / "docs/squad/memory/decisions.jsonl"
MAIN = TMP / "main"
WT = TMP / "plankton-teste"
MAIN.mkdir(parents=True)
(MAIN / "docker-compose.yml").write_text("name: checkout-saga\n")
os.environ.update(SQUAD_ROOT_DATA=str(TMP), SQUAD_LOG=str(LOG), SQUAD_TRANSCRIPTS=str(TMP / "transcripts"),
                  SQUAD_MAIN_ROOT=str(MAIN), SQUAD_TEST_WORKTREE=str(WT), SQUAD_TEST_SMOKE_SLEEP="0",
                  SQUAD_TESTENV_SPAWN="0", SQUAD_TESTENV_PROBE="0")
os.environ.pop("SQUAD_PROD_AUTOUPDATE", None)
sys.path.insert(0, str(REPO / "tools/squad"))
te = importlib.import_module("testenv")
prod = importlib.import_module("prod")
al = importlib.import_module("alerts")
server = importlib.import_module("server")

DA, DB, DC = "aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3"
SHA_A, SHA_A2, SHA_B = "a" * 40, "c" * 40, "b" * 40
HEAD, FROM = "f" * 40, "e" * 40
PROD_FORBIDDEN = {"down", "-v", "--volumes", "prune", "rm", "rmi", "--remove-orphans", "--force-recreate", "kill"}


def test_config(**over) -> dict:
    """Config resolvido do teste (mesma forma de `docker compose config --format json`)."""
    env = {**te.read_env(REPO / te.ENV_FILE), **over}
    p = te.test_ports(env)
    ns = env.get("IMAGE_NAMESPACE", "checkout-teste")
    port = lambda target, pub: [{"mode": "ingress", "target": target, "published": str(pub), "protocol": "tcp"}]  # noqa
    svcs = {
        "postgres": {"image": "postgres:17-alpine", "ports": port(5432, p["postgres"]),
                     "volumes": [{"type": "volume", "source": "pgdata", "target": "/var/lib/postgresql/data"}]},
        "kafka": {"image": "apache/kafka:3.8.0", "ports": port(29092, p["kafka"])},
        "checkout-console": {"image": "nginx:1.27-alpine", "ports": port(80, p["console"])},
        "jaeger": {"image": "jaegertracing/all-in-one:1.62.0",
                   "ports": port(16686, p["jaeger"]) + port(4317, int(env.get("OTLP_GRPC_PORT", 14317)))},
        "prometheus": {"image": "prom/prometheus:v2.54.1", "ports": port(9090, p["prometheus"])},
        "grafana": {"image": "grafana/grafana:11.2.0", "ports": port(3000, p["grafana"])},
    }
    for svc, key in zip(te.APP_SERVICES, ("saga", "order", "inventory", "payment", "shipping")):
        svcs[svc] = {"image": f"{ns}/{svc}:local", "build": {"context": "."}, "mem_limit": "536870912",
                     "ports": port(8080 + list(te.APP_SERVICES).index(svc), p[key])}
    name = env.get("COMPOSE_PROJECT_NAME", "checkout-teste")
    return {"name": name, "services": svcs, "volumes": {"pgdata": {"name": f"{name}_pgdata"}},
            "networks": {"default": {"name": f"{name}_default"}}}


class Fake(te.Exec):
    """Executor falso: registra e responde; nunca chama docker/gh/git de verdade."""

    def __init__(self):
        super().__init__()
        self.prs = {}                     # url -> {state, headRefOid, number}
        self.config = test_config()
        self.docker_ports = "checkout-saga\t0.0.0.0:8081->8081/tcp\n"
        self.lsof = "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nOrbStack 1 u 1u IPv4 0 0t0 TCP *:8081 (LISTEN)\n"
        self.rc = {}                      # palavra-chave -> lista de códigos (consumidos em ordem)
        self.diff = ""
        self.hash_new = {s: "h1" for s in ["postgres", "kafka", *te.APP_SERVICES]}
        self.hash_old = dict(self.hash_new)
        self.health = ""
        self.inspect = "[]"

    def _rc(self, key):
        seq = self.rc.get(key)
        return seq.pop(0) if seq else 0

    def run(self, cmd, cwd=None, timeout=120):
        self.calls.append(list(cmd))
        c = " ".join(cmd)
        R = te.Result
        if cmd[0] == "gh":
            info = self.prs.get(cmd[3])
            return R(0, json.dumps(info)) if info else R(1, "", "no PR")
        if cmd[0] == "lsof":
            return R(0, self.lsof)
        if cmd[0] == "git":
            if "--show-toplevel" in cmd:
                return R(0, str(MAIN) + "\n")
            if "--git-dir" in cmd or "--git-common-dir" in cmd:
                return R(0, str(MAIN / ".git") + "\n")
            if "--abbrev-ref" in cmd:
                return R(0, "develop\n")
            if cmd[-2:] == ["rev-parse", "HEAD"] or cmd[-1] == "origin/develop":
                return R(0, HEAD + "\n")
            if "diff" in cmd:
                return R(0, self.diff)
            if "show" in cmd:
                return R(0, "name: checkout-saga\n")
            if "status" in cmd:
                return R(0, "")
            return R(self._rc("git"), "")
        # docker
        if "config" in cmd and "--format" in cmd and "json" in cmd:
            if "checkout-saga" in cmd:
                return R(0, json.dumps({"name": "checkout-saga"}))
            return R(0, json.dumps(self.config))
        if "config" in cmd and "--hash" in cmd:
            h = self.hash_old if "-f" in cmd else self.hash_new
            return R(0, "".join(f"{k} {v}\n" for k, v in h.items()))
        if cmd[:2] == ["docker", "ps"] and "--format" in cmd and "{{.Ports}}" in c:
            return R(0, self.docker_ports)
        if cmd[:3] == ["docker", "ps", "-a"] and "--format" in cmd:
            return R(0, self.health)
        if cmd[:3] == ["docker", "ps", "-q"] or cmd[:4] == ["docker", "ps", "-a", "-q"]:
            return R(0, "c1 c2\n" if "-a" in cmd else "")
        if cmd[:2] == ["docker", "info"]:
            return R(0, str(16 * 1024 ** 3))
        if cmd[:2] == ["docker", "inspect"]:
            if "{{.Image}}" in cmd:
                return R(0, f"sha256:old-{cmd[-1]}\n")
            return R(0, self.inspect)
        if cmd[:3] == ["docker", "volume", "inspect"]:
            return R(0, json.dumps([{"Name": cmd[-1], "CreatedAt": "2026-09-01T00:00:00Z", "Mountpoint": "/v"}]))
        if cmd[:3] == ["docker", "image", "ls"]:
            return R(0, "checkout-saga/order-service:local\tsha256:img-order\n")
        if cmd[:3] == ["docker", "image", "inspect"]:
            return R(0, "<no value>\n")
        if "ps" in cmd and "-q" in cmd:          # compose ps -q <svc>
            return R(0, f"cid-{cmd[-1]}\n")
        for key in ("build", "up", "stop", "down", "tag", "restart", "logs"):
            if key in cmd:
                return R(self._rc(key), "", f"{key} falhou" if self.rc.get(f"_{key}_err") else "")
        return R(0, "")

    def compose_cmds(self):
        return [c for c in self.calls if c[:2] == ["docker", "compose"]]


def rows():
    return te.read_log()


def add(type_, agent="orquestrador", **kw):
    return te.append(type_, kw.pop("title", type_), agent=agent, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text("")
        self.fx = Fake()
        te.set_exec(self.fx)
        te.http_ok = lambda url, timeout=3.0: True
        for d, title in ((DA, "um"), (DB, "dois"), (DC, "tres")):
            add("task", "humano", id=d, title=f"Demanda: {title}")

    def review(self, d, pr, sha, state="OPEN"):
        url = f"https://github.com/x/y/pull/{pr}"
        add("review", demand=d, pr=pr, url=url, branch=f"feature/{d}")
        self.fx.prs[url] = {"state": state, "headRefOid": sha, "number": pr, "url": url}
        return url

    def types(self, t):
        return [e for e in rows() if e["type"] == t]


# ====================================================================== fila, pedido do humano, publicação
class TestFila(Base):
    def test_409_sem_pr_aberto(self):
        with self.assertRaises(te.RequestError) as cm:
            te.request(DA, "publish")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.types("test-env-request"), [])

    def test_publicar_fila_liberar_e_proximo(self):
        self.review(DA, 11, SHA_A)
        self.review(DB, 12, SHA_B)
        r = te.request(DA, "publish")
        self.assertEqual(self.types("test-env-request")[0]["agent"], "humano")
        self.assertEqual(r["position"], 1)
        te.reconcile()
        v = te.view(rows())
        self.assertEqual((v["state"], v["demand"], v["commit"], v["pr"]), ("ocupado", DA, SHA_A, 11))
        self.assertEqual(v["urls"]["order"], "http://localhost:18081")
        pub = self.types("test-env-published")[0]
        self.assertEqual(pub["ports"]["saga"], 18080)
        self.assertTrue(all(pub["smoke"].values()))
        cmds = self.fx.compose_cmds()
        self.assertIn(["docker", "compose", "-p", "checkout-teste", "--env-file", "infra/teste/teste.env", "build",
                       "--build-arg", f"REVISION={SHA_A}"], cmds)
        self.assertIn(["docker", "compose", "-p", "checkout-teste", "--env-file", "infra/teste/teste.env", "up", "-d",
                       "--wait", "--wait-timeout", "300"], cmds)
        self.assertIn(["git", "-C", str(MAIN), "worktree", "add", "--detach", str(WT), SHA_A], self.fx.calls)
        # fila: pedido de DB com DA ocupando -> posição 1, nenhum comando do Docker que altere algo
        n = len(self.fx.calls)
        r = te.request(DB, "publish")
        self.assertEqual((r["state"], r["position"]), ("ocupado", 1))
        te.reconcile()
        self.assertFalse([c for c in self.fx.calls[n:] if c[:2] == ["docker", "compose"]])
        self.assertEqual(te.view(rows())["queue"][0]["demand"], DB)
        # pedido repetido = idempotente
        self.assertTrue(te.request(DB, "publish")["duplicate"])
        # merge de DA -> released delivered (stop, sem -v) e publicação automática de DB
        add("delivered", demand=DA, pr=11, url="https://github.com/x/y/pull/11")
        te.reconcile()
        rel = self.types("test-env-released")
        self.assertEqual((rel[0]["demand"], rel[0]["reason"]), (DA, "delivered"))
        self.assertIn(["docker", "compose", "-p", "checkout-teste", "--env-file", "infra/teste/teste.env", "stop"],
                      self.fx.calls)
        v = te.view(rows())
        self.assertEqual((v["state"], v["demand"], v["commit"], v["queue"]), ("ocupado", DB, SHA_B, []))
        self.assertTrue(al.stage_of(al.Rules(rows(), []), rows(), DB) == "Pronto para testar")

    def test_publish_sem_pedido_do_humano_CA5(self):
        self.review(DA, 11, SHA_A)
        self.assertEqual(te.main(["publish", "--demand", DA]), 1)
        f = self.types("test-env-failed")
        self.assertEqual(f[0]["phase"], "guard")
        self.assertEqual(te.view(rows())["state"], "livre")
        self.assertFalse(self.fx.compose_cmds())
        # agente gravando pedido como outro agente também não vale
        add("test-env-request", agent="qa", demand=DA, action="publish")
        te.reconcile()
        self.assertEqual(te.view(rows())["state"], "livre")

    def test_pedido_obsoleto_sai_da_fila_CA8(self):
        self.review(DA, 11, SHA_A)
        url_b = self.review(DB, 12, SHA_B)
        te.request(DA, "publish")
        te.reconcile()
        te.request(DB, "publish")
        add("review-rejected", demand=DB, pr=12, url=url_b)
        te.reconcile()
        rel = [e for e in self.types("test-env-released") if e["demand"] == DB]
        self.assertEqual(rel[0]["reason"], "obsolete")
        self.assertEqual(te.view(rows())["queue"], [])
        self.assertEqual(te.view(rows())["demand"], DA)

    def test_republicar_desatualizado_nao_passa_pela_fila_CA11(self):
        url = self.review(DA, 11, SHA_A)
        self.review(DB, 12, SHA_B)
        te.request(DA, "publish")
        te.reconcile()
        te.request(DB, "publish")
        self.fx.prs[url]["headRefOid"] = SHA_A2          # novo push no PR
        v = te.view(rows(), pr_head=SHA_A2)
        self.assertTrue(v["stale"])
        self.assertFalse(te.view(rows(), pr_head=SHA_A)["stale"])
        te.request(DA, "publish")                          # Republicar
        te.reconcile()
        v = te.view(rows(), pr_head=SHA_A2)
        self.assertEqual((v["demand"], v["commit"], v["stale"]), (DA, SHA_A2, False))
        self.assertEqual(v["queue"][0]["demand"], DB)      # DB continua na fila

    def test_cancelar_libera_e_sair_da_fila(self):
        self.review(DA, 11, SHA_A)
        self.review(DB, 12, SHA_B)
        te.request(DA, "publish")
        te.reconcile()
        te.request(DB, "publish")
        te.request(DB, "cancel")
        self.assertEqual(te.view(rows())["queue"], [])
        add("control", "humano", demand=DA, action="cancel")
        te.reconcile()
        self.assertEqual(self.types("test-env-released")[-1]["reason"], "canceled")
        self.assertEqual(te.view(rows())["state"], "livre")

    def test_liberar_pelo_humano_publica_o_proximo(self):
        self.review(DA, 11, SHA_A)
        self.review(DB, 12, SHA_B)
        te.request(DA, "publish")
        te.reconcile()
        te.request(DB, "publish")
        self.assertEqual(te.main(["release", "--demand", DA, "--reason", "human"]), 0)
        self.assertEqual(self.types("test-env-released")[0]["reason"], "human")
        self.assertEqual(te.view(rows())["demand"], DB)


# ====================================================================== guard (R1, R8, CA2) e reset
class TestGuard(Base):
    def test_config_real_do_teste_passa(self):
        self.assertEqual(te.check_config(test_config()), [])

    def test_portas_adulteradas_recusadas_sem_up(self):
        errs = te.check_config(test_config(ORDER_PORT="8081", GRAFANA_PORT="3000"))
        self.assertTrue(any("8081" in e for e in errs) and any("3000" in e for e in errs), errs)
        self.assertTrue(te.check_config(test_config(ORDER_PORT="28081")))          # não é produtivo + 10000
        self.review(DA, 11, SHA_A)
        self.fx.config = test_config(ORDER_PORT="8081")
        te.request(DA, "publish")
        te.reconcile()
        self.assertEqual(self.types("test-env-failed")[0]["phase"], "guard")
        self.assertFalse([c for c in self.fx.compose_cmds() if "build" in c or "up" in c])

    def test_imagens_so_das_5_de_aplicacao_R1(self):
        cfg = test_config()
        self.assertEqual(cfg["services"]["postgres"]["image"], "postgres:17-alpine")   # terceiros passam
        errs = te.check_config(test_config(IMAGE_NAMESPACE="checkout-saga"))
        self.assertEqual(len([e for e in errs if "imagem" in e]), 5)
        self.assertTrue(te.check_config(test_config(COMPOSE_PROJECT_NAME="checkout-saga")))

    def test_portas_ocupadas_no_host_e_por_outro_projeto_R8(self):
        self.fx.lsof += "java 9 u 1u IPv4 0 0t0 TCP 127.0.0.1:18081 (LISTEN)\n"
        self.assertEqual(te.port_conflicts([18081]), ["porta 18081 ocupada no host pelo processo 'java'"])
        self.fx.docker_ports = "outro\t0.0.0.0:18082->80/tcp\ncheckout-teste\t0.0.0.0:18080->8080/tcp\n"
        errs = te.port_conflicts([18080, 18082])
        self.assertEqual(errs, ["porta 18082 ocupada pelo projeto 'outro'"])        # o próprio teste não conta

    def test_reset_so_com_APAGAR(self):
        with self.assertRaises(te.RequestError) as cm:
            te.request(None, "reset-data")
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(te.main(["reset-data"]), 1)                 # sem pedido pendente: nada executado
        self.assertFalse(self.fx.compose_cmds())
        self.review(DA, 11, SHA_A)
        te.request(DA, "publish")
        te.reconcile()
        te.request(None, "reset-data", "APAGAR")
        self.assertEqual(te.main(["reset-data"]), 0)
        down = [c for c in self.fx.compose_cmds() if "down" in c]
        self.assertEqual(down, [["docker", "compose", "-p", "checkout-teste", "--env-file", "infra/teste/teste.env",
                                 "down", "-v"]])
        self.assertEqual(len(self.types("test-env-reset")), 1)
        self.assertEqual(te.view(rows())["state"], "ocupado")        # republicou o mesmo commit
        self.assertEqual(self.types("test-env-publishing")[-1]["commit"], SHA_A)

    def test_down_sem_v_e_comandos_sempre_com_projeto_de_teste(self):
        self.review(DA, 11, SHA_A)
        te.request(DA, "publish")
        te.reconcile()
        self.assertEqual(te.main(["down"]), 0)
        self.assertIn(["docker", "compose", "-p", "checkout-teste", "--env-file", "infra/teste/teste.env", "down"],
                      self.fx.calls)
        self.assertTrue(te.view(rows(), health={})["stopped"])
        self.assertEqual(te.view(rows(), health={})["state"], "ocupado")   # derrubado pelo humano: sem A5
        for c in self.fx.compose_cmds():
            self.assertEqual(c[2:6], ["-p", "checkout-teste", "--env-file", "infra/teste/teste.env"], c)
            self.assertNotIn("checkout-saga", " ".join(c))
        with self.assertRaises(RuntimeError):
            te.assert_test_only(["docker", "compose", "up", "-d"])

    def test_flyway_sugere_apagar_dados(self):
        self.review(DA, 11, SHA_A)
        self.fx.rc["up"] = [1]
        orig = self.fx.run

        def run(cmd, cwd=None, timeout=120):
            if "logs" in cmd:
                self.fx.calls.append(list(cmd))
                return te.Result(0, "FlywayValidateException: Validate failed: Detected applied migration not resolved")
            return orig(cmd, cwd, timeout)
        self.fx.run = run
        te.request(DA, "publish")
        te.reconcile()
        f = self.types("test-env-failed")[0]
        self.assertEqual((f["phase"], f["hint"]), ("health", "reset-data"))
        v = te.view(rows())
        self.assertEqual(v["state"], "falhou")
        a4 = [a for a in al.env_alerts(rows(), v) if a["kind"] == "test-env-failed"]
        self.assertEqual(len(a4), 1)
        self.assertIn("apagar dados", a4[0]["title"])


# ====================================================================== divergente, alertas, API
class TestApi(Base):
    def test_divergente_A5(self):
        self.review(DA, 11, SHA_A)
        te.request(DA, "publish")
        te.reconcile()
        ok = {s: {"state": "running", "health": "healthy"} for s in te.APP_SERVICES}
        self.assertEqual(te.view(rows(), health=ok)["state"], "ocupado")
        bad = {**ok, "order-service": {"state": "exited", "health": None}}
        v = te.view(rows(), health=bad)
        self.assertEqual(v["state"], "divergente")
        a5 = [a for a in al.env_alerts(rows(), v) if a["kind"] == "test-env-divergent"]
        self.assertEqual(len(a5), 1)
        self.assertIn("order-service", a5[0]["detail"])

    def test_formato_api_e_http(self):
        url = self.review(DA, 11, SHA_A)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(body):
            req = urllib.request.Request(base + "/api/test-env/request", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            self.assertEqual(post({"demand": DB, "action": "publish"})[0], 409)
            self.assertEqual(post({"action": "reset-data"})[0], 400)
            self.assertEqual(post({"action": "reset-data", "confirm": "apagar"})[0], 400)
            st, body = post({"demand": DA, "action": "publish"})
            self.assertEqual((st, body["state"], body["position"]), (202, "livre", 1))
            self.assertEqual(server.TE_SPAWNED[-1], ["reconcile"])
            te.reconcile()
            with urllib.request.urlopen(base + "/api/test-env") as r:
                v = json.loads(r.read())
            for k in ("state", "demand", "pr", "commit", "prHead", "stale", "phase", "publishedAt", "urls", "queue",
                      "lastError"):
                self.assertIn(k, v)
            self.assertEqual((v["state"], v["code"], v["pr"], v["commit"]), ("ocupado", "D1", 11, SHA_A))
            self.assertEqual(set(v["urls"]), {"console", "grafana", "jaeger", "prometheus", "saga", "order",
                                              "inventory", "payment", "shipping"})
            with urllib.request.urlopen(base + "/api/live") as r:
                raw = r.read()
            live = json.loads(raw)
            self.assertEqual(live["testEnv"], {"state": "ocupado", "demand": DA, "code": "D1", "stale": False,
                                               "queueSize": 0})
            self.assertLess(len(raw), server.LIVE_MAX_BYTES)
            with urllib.request.urlopen(base + "/api/state") as r:
                state = json.loads(r.read())
            self.assertEqual(state["testEnv"]["state"], "ocupado")
            self.assertIn("log", state)                                       # /api/state antigo segue válido
            self.assertEqual(post({"demand": DA, "action": "release"})[0], 202)
            self.assertEqual(server.TE_SPAWNED[-1], ["release", "--demand", DA, "--reason", "human"])
            self.assertTrue(url)
        finally:
            httpd.shutdown()

    def test_B5_abre_e_fecha(self):
        add("prod-update-failed", commit=HEAD, services=["order-service"], phase="health", rolledBack=True)
        b5 = [a for a in al.env_alerts(rows(), None) if a["kind"] == "prod-update-failed"]
        self.assertEqual((len(b5), b5[0]["severity"], b5[0]["owner"]), (1, "bloqueio", "humano"))
        add("prod-updated", commit=HEAD, services=["order-service"])
        self.assertEqual(al.env_alerts(rows(), None), [])


# ====================================================================== fingerprint (CA4) — só leitura
class TestFingerprint(Base):
    def test_fingerprint(self):
        cont = [{"Name": "/checkout-saga-order-service-1", "Id": "id1", "Image": "sha256:img-order",
                 "State": {"StartedAt": "2026-09-23T10:00:00Z", "Status": "running"}, "RestartCount": 0,
                 "Config": {"Labels": {"com.docker.compose.service": "order-service",
                                       "com.docker.compose.config-hash": "h1"}},
                 "NetworkSettings": {"Ports": {"8081/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8081"}]}}}]
        self.fx.inspect = json.dumps(cont)
        a = te.prod_fingerprint()
        c = a["containers"][0]
        self.assertEqual((c["id"], c["image"], c["startedAt"], c["restartCount"], c["ports"]),
                         ("id1", "sha256:img-order", "2026-09-23T10:00:00Z", 0, ["8081->8081/tcp"]))
        self.assertEqual(a["volume"]["createdAt"], "2026-09-01T00:00:00Z")
        self.assertEqual(a["images"], {"checkout-saga/order-service:local": "sha256:img-order"})
        self.assertIn("order-service", a["configHash"])
        self.assertEqual(te.fingerprint_diff(a, te.prod_fingerprint()), [])
        cont[0]["State"]["StartedAt"] = "2026-09-24T10:00:00Z"
        self.fx.inspect = json.dumps(cont)
        self.assertEqual(len(te.fingerprint_diff(a, te.prod_fingerprint())), 1)
        mutating = {"up", "down", "build", "stop", "start", "restart", "rm", "tag", "kill", "create", "prune"}
        for cmd in self.fx.calls:
            self.assertFalse(mutating & set(cmd), cmd)


# ====================================================================== prod.py (CA13–CA16, R2–R5)
class TestProd(Base):
    ALL: list = []

    def tearDown(self):
        TestProd.ALL.extend(self.fx.calls)

    def deployed(self):
        add("prod-updated", commit=FROM, services=[], baseline=True)

    def ups(self):
        return [c for c in self.fx.calls if c[:4] == ["docker", "compose", "-p", "checkout-saga"] and "up" in c]

    def test_plano_por_caminho(self):
        p = prod.plan_paths([("M", "services/order-service/src/main/java/X.java")])
        self.assertEqual((p["build"], p["restart"], p["compose"], p["migrations"]), (["order-service"], [], False, False))
        self.assertEqual(prod.plan_paths([("M", "services/common/src/A.java")])["build"], sorted(te.APP_SERVICES))
        self.assertEqual(prod.plan_paths([("M", "pom.xml")])["build"], sorted(te.APP_SERVICES))
        self.assertEqual(prod.plan_paths([("M", "Dockerfile")])["build"], sorted(te.APP_SERVICES))
        docs = prod.plan_paths([("M", "docs/a.md"), ("M", "tools/squad/x.py"), ("M", "squad-control/index.html"),
                                ("M", "tests/e2e/run.sh"), ("M", "checkout-console/index.html")])
        self.assertEqual((docs["build"], docs["restart"], docs["compose"]), ([], [], False))
        self.assertEqual(prod.plan_paths([("M", "checkout-console/nginx.conf")])["restart"], ["checkout-console"])
        self.assertEqual(prod.plan_paths([("M", "infra/observability/grafana/d.json")])["restart"], ["grafana"])
        self.assertTrue(prod.plan_paths([("A", "services/order-service/src/main/resources/db/migration/V9__x.sql")])["migrations"])
        self.assertTrue(prod.plan_paths([("A", "services/common/src/main/resources/db/common/V0_2__x.sql")])["migrations"])
        self.assertTrue(prod.plan_paths([("M", "infra/postgres/init/01.sql")])["warnings"])

    def test_so_o_servico_alterado_CA13(self):
        self.deployed()
        self.fx.diff = "M\tservices/order-service/src/main/java/X.java\n"
        self.assertEqual(prod.update(), 0)
        ev = self.types("prod-updated")[-1]
        self.assertEqual((ev["services"], ev["commit"], ev["from"]), (["order-service"], HEAD, FROM))
        self.assertIn(["docker", "tag", "sha256:old-cid-order-service", "checkout-saga/order-service:rollback"],
                      self.fx.calls)                                               # R3: da imagem em execução
        build = [c for c in self.fx.calls if "build" in c]
        self.assertEqual(build, [["docker", "compose", "-p", "checkout-saga", "build", "--build-arg",
                                  f"REVISION={HEAD}", "order-service"]])
        self.assertEqual(self.ups(), [["docker", "compose", "-p", "checkout-saga", "up", "-d", "--no-deps", "--wait",
                                       "--wait-timeout", "300", "order-service"]])
        i_build = self.fx.calls.index(build[0])
        i_up = self.fx.calls.index(self.ups()[0])
        self.assertLess(i_build, i_up)                                             # build antes de tocar containers

    def test_so_docs_nada_CA14(self):
        self.deployed()
        self.fx.diff = "M\tdocs/a.md\nM\ttools/squad/server.py\nM\tsquad-control/index.html\n"
        self.assertEqual(prod.update(), 0)
        self.assertEqual(self.types("prod-updated")[-1]["services"], [])
        self.assertFalse([c for c in self.fx.calls if {"build", "up", "tag", "restart"} & set(c)])

    def test_compose_so_servicos_com_hash_novo_R5(self):
        self.deployed()
        self.fx.diff = "M\tdocker-compose.yml\n"
        self.fx.hash_new["payment-service"] = "h2"
        self.assertEqual(prod.update(), 0)
        self.assertEqual(self.ups(), [["docker", "compose", "-p", "checkout-saga", "up", "-d", "--no-deps", "--wait",
                                       "--wait-timeout", "300", "payment-service"]])
        self.assertFalse([c for c in self.fx.calls if "build" in c])

    def test_rollback_CA15(self):
        self.deployed()
        self.fx.diff = "M\tservices/order-service/src/main/java/X.java\n"
        self.fx.rc["up"] = [1, 0]
        self.assertEqual(prod.update(), 1)
        self.assertIn(["docker", "tag", "checkout-saga/order-service:rollback", "checkout-saga/order-service:local"],
                      self.fx.calls)
        self.assertEqual(len(self.ups()), 2)
        f = self.types("prod-update-failed")[-1]
        self.assertEqual((f["phase"], f["rolledBack"]), ("health", True))
        self.assertEqual(al.env_alerts(rows(), None)[0]["kind"], "prod-update-failed")   # B5 no Painel

    def test_migracao_sem_rollback_B5_R4(self):
        self.deployed()
        self.fx.diff = ("M\tservices/order-service/src/main/java/X.java\n"
                        "A\tservices/common/src/main/resources/db/common/V0_2__x.sql\n")
        self.fx.rc["up"] = [1]
        self.assertEqual(prod.update(), 1)
        self.assertEqual(len(self.ups()), 1)
        self.assertFalse([c for c in self.fx.calls if c[-1].endswith(":local") and "tag" in c])
        f = self.types("prod-update-failed")[-1]
        self.assertFalse(f["rolledBack"])
        self.assertIn("migração Flyway", f["detail"])
        self.assertEqual(al.env_alerts(rows(), None)[0]["rule"][:2], "B5")

    def test_build_com_erro_nao_toca_containers(self):
        self.deployed()
        self.fx.diff = "M\tservices/common/src/A.java\n"
        self.fx.rc["build"] = [1]
        self.assertEqual(prod.update(), 1)
        self.assertEqual(self.ups(), [])
        self.assertEqual(self.types("prod-update-failed")[-1]["phase"], "build")

    def test_baseline_nao_toca_containers_R2(self):
        self.assertEqual(prod.baseline(), 0)
        ev = self.types("prod-updated")[-1]
        self.assertEqual((ev["commit"], ev["services"], ev["baseline"]), (HEAD, [], True))
        self.assertFalse([c for c in self.fx.calls if c[0] == "docker" and "config" not in c])
        self.assertEqual(prod.update(), 0)                         # já no commit atual: nada
        self.assertFalse(self.ups())

    def test_sem_baseline_reconstroi_os_5(self):
        self.fx.diff = ""
        self.assertEqual(prod.update(), 0)
        self.assertEqual(self.types("prod-updated")[-1]["services"], sorted(te.APP_SERVICES))

    def test_autoupdate_desligado(self):
        os.environ["SQUAD_PROD_AUTOUPDATE"] = "0"
        try:
            self.assertEqual(prod.update(auto=True), 0)
        finally:
            os.environ.pop("SQUAD_PROD_AUTOUPDATE")
        self.assertEqual(self.fx.calls, [])

    def test_guard_fora_da_develop(self):
        orig = self.fx.run
        self.fx.run = lambda cmd, cwd=None, timeout=120: te.Result(0, "feature/x\n") if "--abbrev-ref" in cmd \
            else orig(cmd, cwd, timeout)
        self.assertEqual(prod.update(), 1)
        self.assertEqual(self.types("prod-update-failed")[-1]["phase"], "guard")
        self.assertFalse([c for c in self.fx.calls if {"build", "up", "tag"} & set(c)])

    def test_guard_fora_da_copia_principal(self):
        """Sem SQUAD_MAIN_ROOT, a cópia principal é o worktree em develop (plankton/); rodar daqui é recusado."""
        saved = os.environ.pop("SQUAD_MAIN_ROOT")
        try:
            self.assertEqual(prod.update(), 1)
        finally:
            os.environ["SQUAD_MAIN_ROOT"] = saved
        self.assertEqual(self.types("prod-update-failed")[-1]["phase"], "guard")
        self.assertFalse([c for c in self.fx.calls if c[0] == "docker"])

    def test_zz_CA16_nenhum_comando_destrutivo(self):
        """Varre todos os comandos gerados pelo prod.py nos testes acima e recusa explícita dos proibidos."""
        docker = [c for c in TestProd.ALL if c and c[0] == "docker"]
        self.assertTrue(docker)
        for c in docker:
            self.assertFalse(PROD_FORBIDDEN & set(c), c)
            if c[:2] == ["docker", "compose"]:
                self.assertEqual(c[2:4], ["-p", "checkout-saga"], c)
            self.assertNotIn(c[1], ("volume", "system", "network"), c)
        for bad in (["docker", "compose", "-p", "checkout-saga", "down"],
                    ["docker", "compose", "-p", "checkout-saga", "down", "-v"],
                    ["docker", "compose", "-p", "checkout-saga", "up", "-d", "--force-recreate", "postgres"],
                    ["docker", "compose", "-p", "checkout-saga", "up", "-d", "--remove-orphans"],
                    ["docker", "volume", "rm", "checkout-saga_pgdata"], ["docker", "system", "prune", "-f"],
                    ["docker", "compose", "up", "-d"]):
            with self.assertRaises(RuntimeError):
                prod.assert_safe(bad)


# ====================================================================== QA (G2 prioridade 2): lock, cancel pela API, after_review
class TestQaLock(Base):
    """reset-data e down com o lock tomado: nada é executado; o pedido fica pendente até o próximo reconcile."""

    def publicado(self):
        self.review(DA, 11, SHA_A)
        te.request(DA, "publish")
        te.reconcile()
        self.assertEqual(te.view(rows())["state"], "ocupado")
        return len(self.fx.calls)

    def test_reset_data_com_lock_tomado(self):
        self.publicado()
        te.request(None, "reset-data", "APAGAR")
        n, n_reset = len(self.fx.calls), len(self.types("test-env-reset"))
        with te.lock() as got:
            self.assertTrue(got)
            self.assertEqual(te.main(["reset-data"]), 3)
            self.assertEqual(te.reconcile(), {"skipped": "lock", "actions": []})
        self.assertFalse([c for c in self.fx.calls[n:] if c[:2] == ["docker", "compose"]])
        self.assertEqual(len(self.types("test-env-reset")), n_reset)
        self.assertTrue(te.derive(rows())["reset"])                      # continua pendente
        te.reconcile()                                                   # lock livre: agora executa
        self.assertEqual(len(self.types("test-env-reset")), n_reset + 1)
        self.assertIn(te.compose_teste("down", "-v"), self.fx.calls[n:])

    def test_down_com_lock_tomado(self):
        n = self.publicado()
        n_req = len(self.types("test-env-request"))
        with te.lock() as got:
            self.assertTrue(got)
            self.assertEqual(te.main(["down"]), 3)
        self.assertFalse([c for c in self.fx.calls[n:] if c[:2] == ["docker", "compose"]])
        self.assertEqual(len(self.types("test-env-request")), n_req)     # nem grava pedido
        self.assertFalse(te.view(rows(), health={}).get("stopped"))
        self.assertEqual(te.main(["down"]), 0)                            # sem lock: down sem -v
        self.assertEqual([c for c in self.fx.calls[n:] if "down" in c], [te.compose_teste("down")])

    def test_publish_e_release_com_lock_tomado(self):
        self.review(DA, 11, SHA_A)
        te.request(DA, "publish")
        with te.lock():
            self.assertEqual(te.main(["publish", "--demand", DA]), 3)
            self.assertEqual(te.main(["release", "--demand", DA, "--reason", "human"]), 3)
        self.assertFalse(self.fx.compose_cmds())


class TestQaCancelApi(Base):
    """POST /api/test-env/request action=cancel (servidor com SQUAD_ROOT_DATA/SQUAD_LOG temporários, docker falso)."""

    def test_cancel_pela_api(self):
        self.review(DA, 11, SHA_A)
        self.review(DB, 12, SHA_B)
        te.request(DA, "publish")
        te.reconcile()
        te.request(DB, "publish")
        self.assertEqual(te.view(rows())["queue"][0]["demand"], DB)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def post(body):
            req = urllib.request.Request(base + "/api/test-env/request", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            n_calls, n_spawn = len(self.fx.calls), len(server.TE_SPAWNED)
            st, body = post({"demand": DB, "action": "cancel"})
            self.assertEqual(st, 202, body)
            self.assertIn("request", body)
            self.assertEqual(server.TE_SPAWNED[n_spawn:], [["reconcile"]])
            req = self.types("test-env-request")[-1]
            self.assertEqual((req["agent"], req["action"], req["demand"]), ("humano", "cancel", DB))
            self.assertEqual(te.view(rows())["queue"], [])
            self.assertEqual(te.view(rows())["demand"], DA)                # ocupante não é afetado
            st, body = post({"demand": DB, "action": "cancel"})            # repetido: idempotente, sem novo spawn
            self.assertEqual((st, body.get("duplicate")), (202, True))
            self.assertEqual(len(server.TE_SPAWNED), n_spawn + 1)
            self.assertEqual(post({"demand": "naoexiste000", "action": "cancel"})[0], 404)
            self.assertEqual(post({"action": "cancel"})[0], 400)
            self.assertEqual(post({"demand": DB, "action": "explodir"})[0], 400)
            self.assertFalse(self.fx.calls[n_calls:])                      # a API não executa docker
        finally:
            httpd.shutdown()


class TestQaAfterReview(unittest.TestCase):
    """gitflow.after_review: prod.py update --auto só com delivered, na develop e SQUAD_PROD_AUTOUPDATE != 0."""

    @classmethod
    def setUpClass(cls):
        cls.gf = importlib.import_module("gitflow")

    def setUp(self):
        gf = self.gf
        self.saved = (gf.ROOT, gf.current, gf.subprocess.Popen, os.environ.get("SQUAD_PROD_AUTOUPDATE"))
        root = pathlib.Path(tempfile.mkdtemp(prefix="squad-d15-gf-"))
        for f in ("docker-compose.yml", "tools/squad/prod.py", "tools/squad/testenv.py", "infra/teste/teste.env"):
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text("")
        self.root, self.popen, self.branch = root, [], "develop"
        gf.ROOT = root
        gf.current = lambda: self.branch

        def fake_popen(cmd, **kw):
            self.popen.append(cmd)

            class P:
                pid = 0
            return P()
        gf.subprocess.Popen = fake_popen
        os.environ.pop("SQUAD_PROD_AUTOUPDATE", None)

    def tearDown(self):
        gf = self.gf
        gf.ROOT, gf.current, gf.subprocess.Popen, auto = self.saved
        if auto is None:
            os.environ.pop("SQUAD_PROD_AUTOUPDATE", None)
        else:
            os.environ["SQUAD_PROD_AUTOUPDATE"] = auto

    def call(self, delivered):
        self.gf.after_review(delivered=delivered)

    def script(self):
        self.assertEqual(len(self.popen), 1, self.popen)
        return self.popen[0][-1]

    def test_defeito_print_nao_quebra(self):
        """Regressão do defeito f6ed87f48c62 (corrigido pelo Orquestrador): o print final do after_review fazia c[3]
        em ['python3', 'tools/squad/testenv.py', 'reconcile'] (3 itens) -> IndexError em todo merge/fechamento."""
        for delivered in (True, False):
            self.gf.after_review(delivered=delivered)

    def test_develop_delivered_chama_prod_e_reconcile(self):
        self.call(True)
        s = self.script()
        self.assertIn("tools/squad/prod.py update --auto", s)
        self.assertLess(s.index("prod.py"), s.index("testenv.py reconcile"))   # produtivo primeiro

    def test_fora_da_develop_nao_chama_prod(self):
        self.branch = "feature/D15-ambiente-de-teste"
        self.call(True)
        self.assertNotIn("prod.py", self.script())

    def test_autoupdate_desligado_nao_chama_prod(self):
        os.environ["SQUAD_PROD_AUTOUPDATE"] = "0"
        self.call(True)
        self.assertNotIn("prod.py", self.script())

    def test_devolvida_nao_chama_prod(self):
        self.call(False)
        self.assertNotIn("prod.py", self.script())

    def test_copia_sem_ambiente_nada_executado(self):
        for f in ("infra/teste/teste.env", "docker-compose.yml"):
            (self.root / f).unlink()
        self.branch = "feature/x"
        self.gf.after_review(delivered=True)
        self.gf.after_review(delivered=False)
        self.assertEqual(self.popen, [])
        os.environ["SQUAD_PROD_AUTOUPDATE"] = "0"
        self.branch = "develop"
        self.gf.after_review(delivered=True)
        self.assertEqual(self.popen, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
