#!/usr/bin/env python3
"""D18 (`b72a6bd8caf3`) — ambiente e versão do próprio Squad Control (ADR-021).

Contrato `docs/contracts/ui-ambiente-e-versao.md` §1–§4, CA1–CA14 e CA20. Portado do teste do Orquestrador
(scratchpad/d18/test_instance.py) e ampliado pelo QA com o teste de contrato por HTTP (CA13/CA14).
Tudo roda em repositórios git TEMPORÁRIOS (cópia principal em `develop` + worktree de feature) e dados temporários
(SQUAD_ROOT_DATA/SQUAD_LOG): nada toca o log real nem o servidor da 7070.

Uso: python3 tests/squad/test_instancia_d18.py   (ou pytest tests/squad/test_instancia_d18.py)
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = pathlib.Path(tempfile.mkdtemp(prefix="squad-d18-data-")).resolve()
(DATA / "docs/squad/memory").mkdir(parents=True)
(DATA / "docs/squad/memory/decisions.jsonl").write_text("")
os.environ.update(SQUAD_ROOT_DATA=str(DATA), SQUAD_LOG=str(DATA / "docs/squad/memory/decisions.jsonl"),
                  SQUAD_TRANSCRIPTS=str(DATA / "transcripts"), SQUAD_TESTENV_PROBE="0", SQUAD_TESTENV_SPAWN="0")
os.environ.pop("SQUAD_MAIN_ROOT", None)
os.environ.pop("SQUAD_ENV", None)
sys.path.insert(0, str(REPO / "tools/squad"))
import instance as I  # noqa: E402

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0"><parent><version>3.4.5</version></parent>
<artifactId>x</artifactId><version>1.1.0-SNAPSHOT</version></project>"""


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


class Instancia(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="squad-d18-git-")).resolve()
        m = cls.main = cls.tmp / "plankton"
        m.mkdir()
        sh(m, "git", "init", "-q", "-b", "main")
        sh(m, "git", "config", "user.email", "t@t")
        sh(m, "git", "config", "user.name", "t")
        (m / "pom.xml").write_text(POM)
        for d in ("tools/squad", "squad-control", "docs/squad/memory"):
            (m / d).mkdir(parents=True)
            (m / d / "f.txt").write_text("a")
        sh(m, "git", "add", "-A")
        sh(m, "git", "commit", "-qm", "c1")
        sh(m, "git", "tag", "v1.0.0")
        sh(m, "git", "tag", "v1.1.0-rc1")
        sh(m, "git", "tag", "v0.9.0")
        (m / "tools/squad/f.txt").write_text("main-only")
        sh(m, "git", "commit", "-qam", "main")
        sh(m, "git", "checkout", "-qb", "develop", "HEAD~1")
        sh(m, "git", "tag", "v1.2.0", "main")            # v1.2.0 fora da história de develop (CA7)
        cls.wt = cls.tmp / "plankton-d18"
        sh(m, "git", "worktree", "add", "-q", "-b", "feature/x", str(cls.wt))

    def env(self, root, port=7070, data=None, log=None, env=None):
        data = data or root
        return I.environment(root, port, data, log or data / "docs/squad/memory/decisions.jsonl", env or {})

    # ---------------------------------------------------------------- §1 ambiente
    def test_ca1_produtivo(self):
        e = self.env(self.main)
        self.assertEqual((e["name"], e["label"], e["source"]), ("produtivo", "Produtivo", "inferido"))
        self.assertTrue(e["dataIsMain"])

    def test_ca2_worktree_7070_e_outra_porta(self):
        for p in (7070, 7281):
            e = self.env(self.wt, p)
            self.assertEqual((e["name"], e["label"]), ("teste", "Teste"))
            self.assertIn("worktree plankton-d18", e["reason"])
            self.assertIn(f"porta {p}", e["reason"])
            self.assertFalse(e["dataIsMain"])
            self.assertEqual((e["port"], e["worktree"]), (p, "plankton-d18"))

    def test_ca3_principal_outra_porta_ou_dados(self):
        self.assertEqual(self.env(self.main, 7170)["name"], "teste")
        self.assertEqual(self.env(self.main, 7070, data=self.tmp)["name"], "teste")
        self.assertEqual(self.env(self.main, 7070, log=self.tmp / "x.jsonl")["name"], "teste")

    def test_r1_sem_develop_sem_fallback(self):
        sh(self.main, "git", "checkout", "-q", "--detach")
        try:
            e = self.env(self.main)
            self.assertEqual(e["name"], "teste")
            self.assertIn("nenhum worktree em develop", e["reason"])
        finally:
            sh(self.main, "git", "checkout", "-q", "develop")

    def test_ca4_squad_env(self):
        e = self.env(self.wt, 7281, env={"SQUAD_ENV": " produtivo "})
        self.assertEqual((e["name"], e["source"]), ("produtivo", "SQUAD_ENV"))
        e = self.env(self.main, env={"SQUAD_ENV": "teste"})
        self.assertEqual((e["name"], e["source"]), ("teste", "SQUAD_ENV"))
        e = self.env(self.main, env={"SQUAD_ENV": "xyz"})
        self.assertEqual((e["name"], e["label"], e["source"], e["reason"]),
                         ("desconhecido", "Ambiente desconhecido", "SQUAD_ENV", "valor inválido: xyz"))
        e = self.env(self.main, env={"SQUAD_ENV": "Produtivo"})     # só minúsculas
        self.assertEqual(e["name"], "desconhecido")

    def test_ca5_sem_git(self):
        d = pathlib.Path(tempfile.mkdtemp()).resolve()
        e = self.env(d)
        self.assertEqual((e["name"], e["source"]), ("desconhecido", "indeterminado"))
        s = I.Instance(d, 7070, d, d / "l.jsonl", env={}).snapshot()
        self.assertEqual(s["freshness"]["state"], "indeterminado")
        self.assertIsNone(s["build"]["commit"])
        old = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            self.assertEqual(self.env(self.main)["name"], "desconhecido")
            b = I.Instance(self.main, 7070, self.main, self.main / "l", env={}).snapshot()["build"]
            self.assertEqual(b["display"], "sem tag · 1.1.0-SNAPSHOT · commit ?")
        finally:
            os.environ["PATH"] = old

    def test_ca6_r4_dados_do_produtivo(self):
        self.assertTrue(self.env(self.wt, 7281, data=self.main)["dataIsMain"])
        e = self.env(self.wt, 7281, log=self.main / "docs/squad/memory/decisions.jsonl")
        self.assertTrue(e["dataIsMain"])
        self.assertEqual(e["name"], "teste")

    # ---------------------------------------------------------------- §2 versão
    def test_ca7_8_9_versao(self):
        b = I.build(self.main)
        self.assertEqual(b["release"], "v1.2.0")        # maior final, fora da história, sem rc
        self.assertEqual(b["pom"], "1.1.0-SNAPSHOT")    # não o 3.4.5 do <parent>
        self.assertEqual(b["display"], f"v1.2.0 · 1.1.0-SNAPSHOT · {b['commit']}")
        self.assertIn("·", b["display"])
        self.assertEqual(b["branch"], "develop")
        self.assertEqual(len(b["commit"]), 7)
        self.assertTrue(b["commitFull"].startswith(b["commit"]))

    def test_ca7_sem_tags_e_destacado(self):
        d = self.tmp / "semtag"
        d.mkdir()
        sh(d, "git", "init", "-q")
        sh(d, "git", "-c", "user.email=a@a", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x")
        sh(d, "git", "checkout", "-q", "--detach")
        b = I.build(d)
        self.assertIsNone(b["release"])
        self.assertIsNone(b["branch"])                  # HEAD destacado → null
        self.assertTrue(b["display"].startswith("sem tag · pom ? · "))

    def test_ca7_8_repositorio_real(self):
        """Hoje: pom 1.1.0-SNAPSHOT (não 3.4.5) e release = maior tag v* do repositório."""
        b = I.build(REPO)
        self.assertEqual(b["pom"], I.pom_version(REPO))
        self.assertNotEqual(b["pom"], "3.4.5")
        tags = subprocess.run(["git", "tag", "--list", "v[0-9]*"], cwd=REPO, capture_output=True, text=True).stdout.split()
        if tags:
            self.assertIn(b["release"], tags)

    def test_r6_so_prerelease(self):
        d = self.tmp / "rc"
        d.mkdir()
        sh(d, "git", "init", "-q")
        sh(d, "git", "-c", "user.email=a@a", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x")
        self.assertIsNone(I.latest_release(d))
        sh(d, "git", "tag", "v2.0.0-rc1")
        self.assertEqual(I.latest_release(d), "v2.0.0-rc1")

    # ---------------------------------------------------------------- §3 atualidade / dirty
    def test_ca10_11_12_freshness_dirty(self):
        inst = I.Instance(self.wt, 7281, self.wt, self.wt / "l", env={}, cache_s=0)
        s = inst.snapshot()
        self.assertEqual(s["freshness"]["state"], "atual")
        self.assertFalse(s["build"]["dirty"])
        (self.wt / "docs/squad/memory/f.txt").write_text("mem")
        sh(self.wt, "git", "commit", "-qam", "Sincronização da memória")
        s = inst.snapshot()
        self.assertEqual((s["freshness"]["state"], s["freshness"]["changedPaths"]), ("atual", 0))   # CA10
        (self.wt / "docs/squad/memory/f.txt").write_text("mem2")
        self.assertFalse(inst.snapshot()["build"]["dirty"])                                          # CA12 (memória)
        (self.wt / "squad-control/f.txt").write_text("sujo")
        s = inst.snapshot()
        self.assertTrue(s["build"]["dirty"])                                                         # CA12
        self.assertTrue(s["build"]["display"].endswith(" +alterações"))
        sh(self.wt, "git", "commit", "-qam", "ui")
        s = inst.snapshot()
        self.assertEqual(s["freshness"]["state"], "desatualizado")                                   # CA11
        self.assertGreaterEqual(s["freshness"]["changedPaths"], 1)
        self.assertFalse(s["build"]["dirty"])

    def test_ca13_r2_contagem_de_git(self):
        calls = []
        orig = I.subprocess.run

        def spy(a, *k, **kw):
            calls.append(a[1])
            return orig(a, *k, **kw)
        inst = I.Instance(self.wt, 7281, self.wt, self.wt / "l", env={}, cache_s=30)
        I.subprocess.run = spy
        try:
            for _ in range(5):
                inst.snapshot()
            self.assertEqual(calls, ["rev-parse", "status"])   # 1 rev-parse + dirty (R3) por janela; sem diff
            calls.clear()
            inst.cache_s = 0
            (self.wt / "tools/squad/f.txt").write_text("n")
            orig(["git", "commit", "-qam", "tools"], cwd=self.wt, check=True, capture_output=True)
            inst.snapshot()
            inst.snapshot()
            self.assertEqual(calls.count("diff"), 1)             # diff só no HEAD novo
        finally:
            I.subprocess.run = orig

    def test_ca20_git_que_dorme(self):
        d = self.tmp / "bin"
        d.mkdir(exist_ok=True)
        g = d / "git"
        g.write_text("#!/bin/sh\nsleep 10\n")
        g.chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{d}:{old}"
        try:
            t = time.monotonic()
            s = I.Instance(self.main, 7070, self.main, self.main / "l", env={}).snapshot()
            self.assertEqual(s["environment"]["name"], "desconhecido")
            self.assertLess(time.monotonic() - t, 5)
        finally:
            os.environ["PATH"] = old


class ContratoHTTP(unittest.TestCase):
    """CA13/CA14 por HTTP, com o servidor do worktree numa porta efêmera e dados temporários."""
    STATE_KEYS_ANTES = {"now", "log", "gates", "runs", "handoffs", "github", "usage", "version", "thresholds",
                        "summary", "alerts", "alertsHistory", "agents", "serverMs", "testEnv",
                        "delegations"}   # D19 (ADR-022) acrescentou `delegations` antes da D18
    LIVE_KEYS = {"now", "version", "serverMs", "thresholds", "summary", "alerts", "agents", "testEnv",
                 "publication"}   # D24 (ADR-025, contrato publicacao-do-squad-control §4.5): sempre presente, null sem supervisor
    LIVE_HEADERS = {"content-type", "cache-control", "etag", "x-squad-version", "content-length"}

    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        server.INSTANCE = None        # caminho preguiçoso (sem main()): a 1ª consulta cria com a porta real
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.popens = []
        cls._orig = subprocess.Popen
        outer = cls

        class Spy(subprocess.Popen):   # conta TODO subprocesso do processo (git, gh, docker...)
            def __init__(self, args, *a, **kw):
                outer.popens.append(list(args) if isinstance(args, (list, tuple)) else [args])
                super().__init__(args, *a, **kw)
        subprocess.Popen = Spy

    @classmethod
    def tearDownClass(cls):
        subprocess.Popen = cls._orig
        cls.httpd.shutdown()

    def get(self, path):
        r = urllib.request.urlopen(self.base + path)
        return r, json.loads(r.read())

    def test_ca13_live_zero_subprocessos_e_formato(self):
        self.get("/api/live")          # aquece caches do log
        self.popens.clear()
        for _ in range(5):
            r, live = self.get("/api/live")
        self.assertEqual(self.popens, [], "o /api/live não pode executar subprocessos")
        self.assertEqual(set(live), self.LIVE_KEYS)
        self.assertNotIn("instance", live)
        self.assertIsNone(live["publication"], "D24 §4.3: sem supervisor o campo sai null")
        self.assertEqual({k.lower() for k in r.headers.keys()} - {"server", "date"}, self.LIVE_HEADERS)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(r.headers["X-Squad-Version"], live["version"])

    def test_ca13_live_nao_cria_instancia(self):
        saved = self.server.INSTANCE
        self.server.INSTANCE = None
        try:
            self.get("/api/live")
            self.assertIsNone(self.server.INSTANCE, "o /api/live não pode calcular ambiente/versão")
        finally:
            self.server.INSTANCE = saved

    def test_ca14_state_chaves_antigas_mais_instance(self):
        r, st = self.get("/api/state")
        self.assertEqual(set(st), self.STATE_KEYS_ANTES | {"instance"})
        self.assertIsInstance(st["version"], str)                       # `version` segue sendo a dos dados
        inst = st["instance"]
        self.assertEqual(set(inst), {"environment", "build", "freshness"})
        self.assertTrue({"name", "label", "source", "reason", "port", "worktree", "root", "dataRoot", "dataIsMain"}
                        <= set(inst["environment"]))
        self.assertTrue({"release", "pom", "commit", "commitFull", "branch", "dirty", "startedAt", "display"}
                        <= set(inst["build"]))
        # D24 (ADR-025 §4.4): `mode` e `pid` entram DENTRO de `build`; o nível de cima não muda
        self.assertEqual(inst["build"]["mode"], "principal")
        self.assertEqual(inst["build"]["pid"], os.getpid())
        self.assertTrue({"state", "headNow", "changedPaths", "checkedAt"} <= set(inst["freshness"]))
        self.assertEqual(inst["environment"]["port"], self.httpd.server_address[1])
        _, live = self.get("/api/live")
        self.assertEqual(live["version"], st["version"])

    def test_ca13_instance_no_store_e_cache_de_git(self):
        r, a = self.get("/api/instance")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertTrue(r.headers["Content-Type"].startswith("application/json"))
        _, st = self.get("/api/state")
        self.assertEqual(a["environment"], st["instance"]["environment"])
        self.assertEqual(a["build"]["commitFull"], st["instance"]["build"]["commitFull"])
        # worktree de feature numa porta efêmera → teste (CA2); o `reason` cita a porta real
        if a["environment"]["source"] == "inferido":
            self.assertEqual(a["environment"]["name"], "teste")
            self.assertIn(f"porta {self.httpd.server_address[1]}", a["environment"]["reason"])
        self.popens.clear()
        for _ in range(5):
            self.get("/api/instance")
        git = [c for c in self.popens if c and c[0] == "git"]
        self.assertEqual(git, [], "dentro da janela de 30 s o /api/instance não roda git")


if __name__ == "__main__":
    unittest.main(verbosity=2)
