#!/usr/bin/env python3
"""D23 (6450aecde7f9) — F2a: resolvedor de produto e códigos de demanda congelados.

Contrato: docs/contracts/f2a-resolvedor-de-produto.md §8 (CA-1…CA-14) + ressalvas do G2 (docs/squad/gates/G2-D23.json).
Base: verify_f2a.py (Orquestrador) e own_checks.py (Auditor), com as correções pedidas no G2:
  - CA-6 com base DINÂMICA (nº de `task` do humano na cópia do log: o log real já tem D25+);
  - CA-1 por comparação de Path com as constantes de cada módulo;
  - 503 `trava_de_codigos` e `log.py` código 1 com a trava segura por OUTRO processo;
  - CA-8 com SQUAD_ROOT_DATA temporário (as runs do triage não caem no .squad/runs do worktree);
  - CA-11 automatizado (cópia principal e worktree registrado varridos por collect_runs/enrich_log).

Isolamento: o log real (cópia principal) é só LIDO e copiado para um diretório temporário; servidores em porta livre
com SQUAD_ROOT_DATA/SQUAD_LOG temporários; HOME temporário nas execuções que tocam ~/.claude; `gh`/`claude` falsos
no PATH (nenhuma chamada real a modelo ou ao GitHub). CA-9 confere o log/github-sync.json do worktree antes/depois.

Uso: SQUAD_CHAT_RUNNER=fake python3 tests/squad/test_produto_f2a.py -v
"""
import base64
import concurrent.futures as cf
import fcntl
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SQ = REPO / "tools/squad"
PY = sys.executable
RUN = uuid.uuid4().hex[:8]
MARK = f"F2A-QA-{RUN}"   # marca por execução nos títulos sintéticos (CA-9 compara o campo `title` dos eventos)


def synth_id() -> str:
    """id sintético de 12 hex gerado por execução (nunca constante: texto de defeito no log real não casa)."""
    return uuid.uuid4().hex[:12]


ID_B, ID_D, ID_AUS = synth_id(), synth_id(), synth_id()          # CA-7 (gitflow), CA-8 (triagem), QA-D23-1 (ausente)
ID_A1, ID_A2, ID_A3 = synth_id(), synth_id(), synth_id()         # CA-11
SYNTH_IDS = {ID_B, ID_D, ID_AUS, ID_A1, ID_A2, ID_A3}

# ids da tabela do contrato §4.3 (D1…D24, nesta ordem)
FROZEN = ["13e55010e3f5", "48b6ace91207", "62f458c8038b", "1cc732c62a2d", "d91b7a8b31d9", "c6f83b5bb5c7",
          "349e5b1bf818", "e31bdfb73679", "f2324e0f25de", "174084ec85d0", "642a73cb38e5", "1ac2708028fd",
          "efe387a35d71", "1e3d3c894630", "518f89f27ae8", "841f9a27e64a", "e1d6eae16073", "b72a6bd8caf3",
          "402e76f187f9", "41bdb8b49835", "71b7d9bc3313", "b26da7851764", "6450aecde7f9", "cf7a120591b0"]
TABLE = {i: f"D{n}" for n, i in enumerate(FROZEN, 1)}
LIVE_KEYS = {"now", "version", "serverMs", "thresholds", "summary", "alerts", "agents", "testEnv"}   # test_instancia_d18

ENV0 = {k: v for k, v in os.environ.items() if not k.startswith("SQUAD_")}
ENV0["SQUAD_CHAT_RUNNER"] = "fake"
os.environ.clear()
os.environ.update(ENV0)
sys.path.insert(0, str(SQ))
import product  # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp(prefix="qa-f2a-")).resolve()
BIN = TMP / "bin"
SAFE_PATH = f"{BIN}:/usr/bin:/bin"   # BIN tem python3 (→ este intérprete), claude e gh falsos; nunca o claude real


def git(*a, cwd=REPO):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)


def main_root() -> pathlib.Path:
    """Cópia principal = worktree em develop (a mesma regra de product._worktrees); sem ela, o próprio repositório."""
    _, main = product._worktrees(REPO)
    return main or REPO


MAIN = main_root()
REAL_LOG = MAIN / "docs/squad/memory/decisions.jsonl"
WT_LOG = REPO / "docs/squad/memory/decisions.jsonl"
WT_SYNC = REPO / "docs/squad/memory/github-sync.json"


def sha(p: pathlib.Path):
    p = pathlib.Path(p)
    if not p.exists():
        return None
    st = p.stat()
    return hashlib.sha256(p.read_bytes()).hexdigest(), st.st_size, st.st_mtime_ns


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def jget(base, path, timeout=60):
    return json.loads(urllib.request.urlopen(base + path, timeout=timeout).read())


def post(base, path, body, timeout=20):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    for attempt in range(20):   # fila de accept do ThreadingHTTPServer no macOS: reset antes do accept = nada lido
        try:
            r = urllib.request.urlopen(req, timeout=timeout)
            return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
        except urllib.error.URLError as e:
            if "reset" not in str(e).lower() or attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


ERRF: dict = {}


def start_server(env: dict) -> tuple[subprocess.Popen, str]:
    port = free_port()
    p = subprocess.Popen([PY, str(SQ / "server.py"), "--port", str(port)], env=env, cwd=REPO,
                         stdout=subprocess.DEVNULL, stderr=ERRF.setdefault(port, (TMP / f"server-{port}.err").open("w")),
                         start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):
        try:
            urllib.request.urlopen(base + "/api/instance", timeout=1).read()
            return p, base
        except Exception:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("servidor não subiu: " + (TMP / f"server-{port}.err").read_text()[-800:])


def stop(p: subprocess.Popen):
    p.terminate()
    try:
        p.wait(10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()


def make_data(name: str, log_src: pathlib.Path | None = None, lines: list[str] | None = None) -> pathlib.Path:
    data = TMP / name
    (data / "docs/squad/memory").mkdir(parents=True)
    log = data / "docs/squad/memory/decisions.jsonl"
    if lines is not None:
        log.write_text("\n".join(lines) + "\n")
    elif log_src:
        shutil.copy(log_src, log)
    else:
        log.write_text("")
    return data


def server_env(data: pathlib.Path, **extra) -> dict:
    env = {**ENV0, "SQUAD_ROOT_DATA": str(data), "SQUAD_LOG": str(data / "docs/squad/memory/decisions.jsonl"),
           "SQUAD_TESTENV_PROBE": "0", "SQUAD_TESTENV_SPAWN": "0", "SQUAD_CHAT_RUNNER": "fake",
           "SQUAD_GH": "/usr/bin/false", "HOME": str(TMP / "home-srv"), "PATH": SAFE_PATH}
    (TMP / "home-srv").mkdir(exist_ok=True)
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}


COPY = TMP / "real-copy.jsonl"
BEFORE = {}


def setUpModule():
    BIN.mkdir()
    # `claude` falso: grava a transcrição em $HOME/.claude/projects/<slug do cwd>/<session-id>.jsonl (regra do §6)
    (BIN / "claude").write_text(
        "#!/bin/sh\nsid=''\nwhile [ $# -gt 0 ]; do [ \"$1\" = --session-id ] && sid=$2; shift; done\n"
        "[ -z \"$sid\" ] && { echo '{\"status\": \"ok\", \"questions\": []}'; exit 0; }\n"
        "d=\"$HOME/.claude/projects/$(pwd -P | sed 's/[^A-Za-z0-9]/-/g')\"; mkdir -p \"$d\"\n"
        "printf '{\"type\":\"assistant\",\"timestamp\":\"2026-09-25T00:00:00Z\",\"message\":{\"model\":\"claude-opus-5-5\","
        "\"content\":[]}}\\n' > \"$d/$sid.jsonl\"\necho ok\n")
    (BIN / "gh").write_text(
        "#!/bin/sh\necho \"$@\" >> '%s/gh_calls'\ncase \"$*\" in\n"
        " *'project list'*) echo '{\"projects\":[{\"number\":1,\"title\":\"x\",\"url\":\"u\",\"id\":\"P\"}]}';;\n"
        " *'issue create'*) echo 'https://github.com/o/r/issues/7';;\n *) echo '{}';;\nesac\n" % TMP)
    for f in BIN.iterdir():
        f.chmod(0o755)
    for n in ("python3", "python"):   # filhos que chamam `python3` usam este intérprete (tomllib), não o do sistema
        (BIN / n).symlink_to(PY)
    BEFORE["real_sha"] = sha(REAL_LOG)
    BEFORE["real_bytes"] = REAL_LOG.read_bytes()
    shutil.copy(REAL_LOG, COPY)
    BEFORE["wt_log"], BEFORE["wt_sync"] = sha(WT_LOG), sha(WT_SYNC)
    BEFORE["wt_runs"] = sorted(p.name for p in (REPO / ".squad/runs").glob("*")) if (REPO / ".squad/runs").exists() else []


def tearDownModule():
    for f in ERRF.values():
        f.close()
    shutil.rmtree(TMP, ignore_errors=True)


def develop_alerts():
    """alerts.py da develop, importado de arquivo temporário SEM product.py ao lado (regra posicional de hoje)."""
    for ref in ("origin/develop", "develop"):
        r = git("show", f"{ref}:tools/squad/alerts.py")
        if r.returncode == 0:
            d = TMP / "develop-alerts"
            d.mkdir(exist_ok=True)
            (d / "alerts_develop.py").write_text(r.stdout)
            spec = importlib.util.spec_from_file_location("alerts_develop", d / "alerts_develop.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise unittest.SkipTest("sem develop para comparar")


def swap_d7_d8(lines: list[str]) -> list[str]:
    lines = list(lines)
    idx = {}
    for i, line in enumerate(lines):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "task" and r.get("agent") == "humano" and r.get("id") in ("349e5b1bf818", "e31bdfb73679"):
            idx[r["id"]] = i
    a, b = idx["349e5b1bf818"], idx["e31bdfb73679"]
    lines[a], lines[b] = lines[b], lines[a]
    return lines


# ====================================================================== CA-1 / CA-2
class T01Resolvedor(unittest.TestCase):
    def test_ca1_resolve_sem_variaveis_caminhos_de_hoje(self):
        p = product.resolve()
        self.assertEqual((p.id, p.code_prefix, p.explicit), ("checkout-saga", "D", False))
        exp = {"log": REPO / "docs/squad/memory/decisions.jsonl", "gates_dir": REPO / "docs/squad/gates",
               "handoffs_dir": REPO / "docs/squad/memory/handoffs", "inbox_dir": REPO / "docs/squad/inbox",
               "runs_dir": REPO / ".squad/runs", "memory_dir": REPO / "docs/squad/memory"}
        for k, v in exp.items():
            self.assertEqual(pathlib.Path(getattr(p, k)).resolve(), v.resolve(), k)

    def test_ca1_constantes_dos_modulos_iguais_as_de_hoje(self):
        code = ("import sys, json; sys.path.insert(0, 'tools/squad'); import server, gitflow, github_sync, triage, "
                "run_agent, log as lg; print(json.dumps({'server': str(server.LOG), 'gitflow': str(gitflow.LOG), "
                "'gs': str(github_sync.LOG), 'gss': str(github_sync.STATE), 'gsh': str(github_sync.HANDOFFS), "
                "'triage': str(triage.LOG), 'run': str(run_agent.RUNS), 'runlog': str(run_agent.MAIN_LOG), "
                "'logpy': str(lg.LOG), 'sgates': str(server.GATES_DIR), 'sruns': str(server.RUNS_DIR), "
                "'sdata': str(server.DATA_ROOT)}))")
        r = subprocess.run([PY, "-c", code], cwd=REPO, capture_output=True, text=True, env={**ENV0, "PATH": SAFE_PATH})
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        d = json.loads(r.stdout.strip().splitlines()[-1])
        R = lambda x: pathlib.Path(x).resolve()  # noqa: E731
        for k in ("server", "gitflow", "gs", "triage", "runlog", "logpy"):
            self.assertEqual(R(d[k]), R(REPO / "docs/squad/memory/decisions.jsonl"), k)
        self.assertEqual(R(d["gss"]), R(REPO / "docs/squad/memory/github-sync.json"))
        self.assertEqual(R(d["gsh"]), R(REPO / "docs/squad/memory/handoffs"))
        self.assertEqual(R(d["run"]), R(REPO / ".squad/runs"))
        self.assertEqual(R(d["sruns"]), R(REPO / ".squad/runs"))
        self.assertEqual(R(d["sgates"]), R(REPO / "docs/squad/gates"))
        self.assertEqual(R(d["sdata"]), R(REPO))

    def test_ca2_precedencia_e_cadastro(self):
        with self.assertRaises(product.ProductError):
            product.resolve("nao-existe")
        os.environ["SQUAD_PRODUCT"] = "outro-prod"
        try:
            with self.assertRaises(product.ProductError):
                product.resolve()
            p = product.resolve("checkout-saga")   # argumento vence o env
            self.assertTrue(p.explicit)
            self.assertEqual(p.id, "checkout-saga")
        finally:
            del os.environ["SQUAD_PRODUCT"]
        os.environ["SQUAD_PRODUCT"] = "checkout-saga"
        try:
            self.assertTrue(product.resolve().explicit)
        finally:
            del os.environ["SQUAD_PRODUCT"]
        f = TMP / "product.toml"
        for body, field in [('schema = 1\n[product]\nid = "checkout-saga"\nname = "x"\n', "code_prefix"),
                            ('schema = 1\n[product]\nid = "outro"\nname = "x"\ncode_prefix = "D"\n', "product.id"),
                            ('schema = 1\n[product]\nid = "checkout-saga"\nname = "x"\ncode_prefix = "DD"\n', "code_prefix")]:
            f.write_text(body)
            with self.assertRaises(product.ProductError) as cm:
                product._parse_toml(f, "checkout-saga")
            self.assertIn(field, str(cm.exception))
            self.assertIn(str(f), str(cm.exception))
        f.write_text('schema = 1\n[product]\nid = "checkout-saga"\nname = "x"\ncode_prefix = "D"\n[env.prod]\nport = 1\n')
        self.assertEqual(product._parse_toml(f, "checkout-saga")["code_prefix"], "D")
        saved = product.PLATFORM_ROOT
        product.PLATFORM_ROOT = TMP / "sem-cadastro"
        try:
            ip = product.resolve()
            self.assertEqual((ip.name, ip.code_prefix, ip.explicit), ("Checkout Saga", "D", False))
            with self.assertRaises(product.ProductError):   # explícito exige o arquivo
                product.resolve("checkout-saga")
        finally:
            product.PLATFORM_ROOT = saved

    def test_cadastro_real(self):
        t = REPO / "docs/squad/products/checkout-saga/product.toml"
        self.assertEqual(product._parse_toml(t, "checkout-saga"), {"name": "Checkout Saga", "code_prefix": "D"})


# ====================================================================== CA-3 / CA-4 / CA-5
class T02Codigos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = develop_alerts()
        cls.rows = product.read_rows(COPY)
        cls.table = json.loads((REPO / "docs/squad/products/checkout-saga/codes.json").read_text())

    def test_ca3_paridade_com_develop_sobre_copia_do_log_real(self):
        new = product.demand_codes(self.rows)
        old = self.old.demand_codes(self.rows)
        self.assertEqual(new, old)
        self.assertGreaterEqual(len(new), 24)
        for i, c in TABLE.items():
            self.assertEqual(new.get(i), c, i)
        self.assertTrue(REAL_LOG.read_bytes().startswith(BEFORE["real_bytes"]), "origem só lida (append de terceiros ok)")

    def test_ca3_codes_json_d1_d24(self):
        t = self.table
        self.assertEqual((t["schema"], t["product"], t["prefix"]), (1, "checkout-saga", "D"))
        self.assertEqual({i: c for i, c in t["codes"].items() if i in TABLE}, TABLE)
        self.assertTrue(set(t["codes"]) >= set(TABLE))
        last = t["source"]["lastTaskId"]
        self.assertIn(last, t["codes"])
        self.assertEqual(max(t["codes"].values(), key=lambda c: int(c[1:])), t["codes"][last])
        self.assertEqual({(a["alias"], a["id"], a["code"]) for a in t["aliases"]},
                         {("D7", "e31bdfb73679", "D8"), ("D8", "349e5b1bf818", "D7"),
                          ("D9", "174084ec85d0", "D10"), ("D10", "f2324e0f25de", "D9")})

    def test_ca4_reordenacao_d7_d8(self):
        swapped = [json.loads(line) for line in swap_d7_d8(COPY.read_text().splitlines()) if line.strip()]
        old = self.old.demand_codes(swapped)
        self.assertEqual((old["349e5b1bf818"], old["e31bdfb73679"]), ("D8", "D7"))   # antigo troca
        new = product.demand_codes(swapped)
        self.assertEqual((new["349e5b1bf818"], new["e31bdfb73679"]), ("D7", "D8"))   # congelado não
        self.assertEqual(new, product.demand_codes(self.rows))

    def test_ca5_apelidos(self):
        for al in self.table["aliases"]:
            self.assertTrue(al["sources"])
            for s in al["sources"]:
                self.assertEqual(product.resolve_code(al["alias"], self.rows, source=s), al["id"], (al["alias"], s))
            self.assertEqual(product.resolve_code(al["alias"], self.rows), FROZEN[int(al["alias"][1:]) - 1])
        self.assertEqual(product.resolve_code("D7", self.rows, source="G1-D7.json"), "e31bdfb73679")
        self.assertEqual(product.resolve_code("D9", self.rows, source="origin/feature/D9-modelo-usado-na-demanda"),
                         "174084ec85d0")
        self.assertEqual(product.resolve_code("D7", self.rows, source="docs/contracts/outro.md"), "349e5b1bf818")
        self.assertEqual(product.resolve_code("d24", self.rows), "cf7a120591b0")

    def test_ca5_codes_check_sai_0(self):
        r = subprocess.run([PY, str(SQ / "product.py"), "codes", "--check", "--json", "--log", str(COPY)],
                           capture_output=True, text=True, env={**ENV0, "PATH": SAFE_PATH})
        self.assertEqual(r.returncode, 0, r.stderr[-400:])
        self.assertEqual(json.loads(r.stdout)["problems"], [])

    def test_codes_check_detecta_conflito(self):
        rows = self.rows + [{"id": "aaaa00000001", "agent": "humano", "type": "task", "code": "D900"},
                            {"id": "aaaa00000002", "agent": "humano", "type": "task", "code": "D900"}]
        codes = product.demand_codes(rows)
        self.assertEqual(codes["aaaa00000001"], "D900")
        self.assertNotEqual(codes["aaaa00000002"], "D900")
        self.assertTrue(any("conflito" in x for x in product.check(rows, product.resolve())))

    def test_ca6_log_sintetico_comeca_em_d1(self):
        rows = [{"id": "aaaaaaaaaaaa", "agent": "humano", "type": "task"},
                {"id": ID_B, "agent": "orquestrador", "type": "task"},
                {"id": "cccccccccccc", "agent": "humano", "type": "task"}]
        self.assertEqual(product.demand_codes(rows), {"aaaaaaaaaaaa": "D1", "cccccccccccc": "D2"})

    def test_lacuna_posicional(self):
        """task do humano sem `code` depois do congelado → próximo posicional (= o que o painel de hoje mostraria)."""
        codes = product.demand_codes(self.rows)
        pos = product.positional_codes(self.rows)
        for t in product.human_tasks(self.rows):
            if t["id"] not in TABLE and not t.get("code"):
                self.assertEqual(codes[t["id"]], pos[t["id"]], t["id"])


# ====================================================================== CA-6 / CA-13 (API) / trava
class T03Gravacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = make_data("data-ca6", COPY)
        cls.log = cls.data / "docs/squad/memory/decisions.jsonl"
        cls.env = server_env(cls.data, SQUAD_TRANSCRIPTS=str(TMP / "tr-ca6"))
        cls.srv, cls.base = start_server(cls.env)
        rows = product.read_rows(COPY)
        cls.B = max(int(c[1:]) for c in product.demand_codes(rows).values())   # base dinâmica (log real já tem D25+)

    @classmethod
    def tearDownClass(cls):
        stop(cls.srv)

    def logpy(self, title, agent="humano"):
        return subprocess.run([PY, str(SQ / "log.py"), "--agent", agent, "--type", "task", "--title", title,
                               "--kind", "operacao"], env=self.env, capture_output=True, text=True)

    def test_1_post_e_logpy_gravam_codigos_seguintes(self):
        st, a = post(self.base, "/api/demand", {"title": f"{MARK}-1", "kind": "operacao"})
        self.assertEqual(st, 201, a)
        st, b = post(self.base, "/api/demand", {"title": f"{MARK}-2", "kind": "produto"})
        self.assertEqual(st, 201, b)
        self.assertEqual((a["code"], a["code_prefix"], b["code"]), (f"D{self.B + 1}", "D", f"D{self.B + 2}"))
        disk = product.read_rows(self.log)[-2:]
        self.assertEqual([(r["id"], r["code"], r["code_prefix"]) for r in disk],
                         [(a["id"], a["code"], "D"), (b["id"], b["code"], "D")])
        r = self.logpy(f"{MARK}-3")
        self.assertEqual(r.returncode, 0, r.stderr)
        last = product.read_rows(self.log)[-1]
        self.assertEqual((last["code"], last["code_prefix"]), (f"D{self.B + 3}", "D"))
        type(self).after1 = self.B + 3

    def test_2_task_de_outro_agente_sem_code(self):
        r = self.logpy(f"{MARK}-orq", agent="orquestrador")
        self.assertEqual(r.returncode, 0, r.stderr)
        last = product.read_rows(self.log)[-1]
        self.assertEqual(last["agent"], "orquestrador")
        self.assertNotIn("code", last)
        self.assertNotIn("code_prefix", last)

    def test_3_corrida_10_logpy_mais_10_post(self):
        top = max(int(c[1:]) for c in product.demand_codes(product.read_rows(self.log)).values())
        with cf.ThreadPoolExecutor(20) as ex:
            futs = [ex.submit(self.logpy, f"{MARK}-RACE-L{i}") for i in range(10)] + \
                   [ex.submit(post, self.base, "/api/demand", {"title": f"{MARK}-RACE-P{i}", "kind": "operacao"})
                    for i in range(10)]
            res = [f.result() for f in futs]
        self.assertTrue(all(r.returncode == 0 for r in res[:10]), [r.stderr for r in res[:10]])
        self.assertTrue(all(r[0] == 201 for r in res[10:]), res[10:])
        race = [r for r in product.read_rows(self.log) if f"{MARK}-RACE" in str(r.get("title", ""))]
        self.assertEqual(len(race), 20)
        self.assertEqual(sorted(int(r["code"][1:]) for r in race), list(range(top + 1, top + 21)))
        self.assertEqual(product.check(product.read_rows(self.log), product.resolve().with_log(self.log)), [])

    def test_4_api_state_codes_e_live(self):
        st = jget(self.base, "/api/state")
        rows = product.read_rows(self.log)
        exp = product.demand_codes(rows)
        self.assertEqual(st["codes"], exp)
        for i, c in TABLE.items():
            self.assertEqual(st["codes"][i], c)
        tk = [e for e in st["log"] if e.get("type") == "task" and e.get("agent") == "humano"]
        self.assertTrue(tk)
        self.assertTrue(all(e.get("code") == exp[e["id"]] for e in tk))
        self.assertEqual(rows[-1], json.loads(self.log.read_text().splitlines()[-1]))   # disco sem enriquecimento
        live = jget(self.base, "/api/live")
        self.assertEqual(set(live), LIVE_KEYS)

    def test_5_append_task_com_code_recusado(self):
        p = product.resolve().with_log(self.log)
        before = self.log.read_bytes()
        with self.assertRaises(product.ProductError):
            product.append_task({"agent": "humano", "type": "task", "code": "D99", "id": "x"}, p)
        with self.assertRaises(product.ProductError):
            product.append_task({"agent": "orquestrador", "type": "task", "id": "x"}, p)
        self.assertEqual(self.log.read_bytes(), before)


class T04Trava(unittest.TestCase):
    """503 `trava_de_codigos` e `log.py` código 1 com a trava segura por OUTRO processo (nada gravado)."""

    def test_trava_ocupada(self):
        data = make_data("data-trava", COPY)
        log = data / "docs/squad/memory/decisions.jsonl"
        env = server_env(data, SQUAD_TRANSCRIPTS=str(TMP / "tr-trava"))
        srv, base = start_server(env)
        (data / ".squad/locks").mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen([PY, "-c", "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT); "
                                   "fcntl.flock(fd, fcntl.LOCK_EX); print('ok', flush=True); time.sleep(60)",
                                   str(data / ".squad/locks/codes.lock")], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ok")
            before = log.read_bytes()
            t0 = time.monotonic()
            st, body = post(base, "/api/demand", {"title": f"{MARK}-LOCK", "kind": "operacao"}, timeout=30)
            dt = time.monotonic() - t0
            self.assertEqual((st, body.get("code")), (503, "trava_de_codigos"), body)
            self.assertGreaterEqual(dt, 4.5)
            self.assertEqual(log.read_bytes(), before)
            r = subprocess.run([PY, str(SQ / "log.py"), "--agent", "humano", "--type", "task", "--title", f"{MARK}-LOCK2",
                                "--kind", "operacao"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(log.read_bytes(), before)
            # task de outro agente não passa pela trava
            r = subprocess.run([PY, str(SQ / "log.py"), "--agent", "orquestrador", "--type", "progress", "--title",
                                f"{MARK}-semtrava"], env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            holder.kill()
            holder.wait()
        st, body = post(base, "/api/demand", {"title": f"{MARK}-LOCK3", "kind": "operacao"})
        stop(srv)
        self.assertEqual(st, 201, body)
        self.assertRegex(body["code"], r"^D[1-9][0-9]*$")


    def test_qa_d23_2_bug_com_503_nao_deixa_pasta_nem_indice(self):
        """QA-D23-2 (ac4df23): bug cujo `task` cai em 503 trava_de_codigos → pasta e linha do index.jsonl desfeitas;
        o rascunho continua e o reenvio (trava livre) grava 201."""
        data = make_data("data-trava-bug", COPY)
        log = data / "docs/squad/memory/decisions.jsonl"
        srv, base = start_server(server_env(data, SQUAD_TRANSCRIPTS=str(TMP / "tr-trava-bug")))
        consent = {"production": True, "public": True}

        def draft(txt):
            st, d = post(base, "/api/bug/draft", {"kind": "produto", "files": [
                {"name": "erro.log", "contentBase64": base64.b64encode(txt).decode()}]})
            self.assertEqual(st, 201, d)
            return d["draft"]

        def bug(dr, title):
            return post(base, "/api/demand", {"title": title, "kind": "produto", "detail": "sintoma", "nature": "bug",
                                              "bug": {"draft": dr, "consent": consent}}, timeout=30)

        bugs_dir = data / "docs/squad/produto/bugs"
        idx = bugs_dir / "index.jsonl"
        holder = None
        try:
            st, b1 = bug(draft(b"falha 1\n"), f"{MARK}-BUG1")   # índice já existe: exercita o truncate (não o unlink)
            self.assertEqual(st, 201, b1)
            dirs0, idx0, log0 = sorted(p.name for p in bugs_dir.iterdir()), idx.read_bytes(), log.read_bytes()
            dr2 = draft(b"falha 2\n")
            (data / ".squad/locks").mkdir(parents=True, exist_ok=True)
            holder = subprocess.Popen([PY, "-c", "import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT); "
                                       "fcntl.flock(fd, fcntl.LOCK_EX); print('ok', flush=True); time.sleep(60)",
                                       str(data / ".squad/locks/codes.lock")], stdout=subprocess.PIPE, text=True)
            self.assertEqual(holder.stdout.readline().strip(), "ok")
            st, e = bug(dr2, f"{MARK}-BUG2")
            self.assertEqual((st, e.get("code")), (503, "trava_de_codigos"), e)
            self.assertEqual(sorted(p.name for p in bugs_dir.iterdir()), dirs0, "nenhuma pasta órfã")
            self.assertEqual(idx.read_bytes(), idx0, "nenhuma linha órfã no index.jsonl")
            self.assertEqual(log.read_bytes(), log0, "nenhum task gravado")
            self.assertTrue((data / ".squad/bug-drafts" / dr2).exists(), "rascunho preservado para o reenvio")
            holder.kill()
            holder.wait()
            holder = None
            st, b2 = bug(dr2, f"{MARK}-BUG2")
            self.assertEqual(st, 201, b2)
            self.assertEqual(len(idx.read_text().splitlines()), len(idx0.decode().splitlines()) + 1)
            self.assertTrue((bugs_dir / b2["id"] / "bug.json").is_file())
        finally:
            if holder:
                holder.kill()
                holder.wait()
            stop(srv)


# ====================================================================== CA-7 / CA-8
class T05Ferramentas(unittest.TestCase):
    def test_ca7_gitflow_honra_squad_log(self):
        g = TMP / "g.jsonl"
        g.write_text(json.dumps({"id": ID_B, "ts": "2026-09-25T00:00:00+00:00", "agent": "humano",
                                 "type": "task", "title": f"Demanda: {MARK} gitflow"}) + "\n")
        envg = {**ENV0, "SQUAD_LOG": str(g), "PATH": SAFE_PATH}
        GR = TMP / "gr"   # repositório TEMPORÁRIO (nada de git no worktree real)
        shutil.copytree(SQ, GR / "tools/squad", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "docs/squad/products", GR / "docs/squad/products")
        (GR / "docs/squad/memory").mkdir(parents=True)
        (GR / "docs/squad/memory/decisions.jsonl").write_text("")
        for c in (["init", "-q", "-b", "develop"], ["add", "-A"],
                  ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base"]):
            self.assertEqual(git(*c, cwd=GR).returncode, 0)
        (GR / "docs/squad/memory/decisions.jsonl").write_text("{}\n")   # memória suja: snapshot NÃO pode commitar
        code = ("import sys; sys.path.insert(0, 'tools/squad'); import gitflow; print(gitflow.LOG); "
                f"print(gitflow.demand_code('{ID_B}')); gitflow.log('{MARK} gitflow'); "
                "gitflow.import_memory('develop'); gitflow.snapshot_state()")
        r = subprocess.run([PY, "-c", code], cwd=GR, env=envg, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        self.assertIn(str(g), r.stdout)
        self.assertIn("\nD1\n", r.stdout)
        self.assertIn(f"{MARK} gitflow", g.read_text().split("\n", 1)[1])
        self.assertEqual(r.stdout.count("ignorada"), 2, r.stdout)
        self.assertIn(f"SQUAD_LOG={g}", r.stdout)
        self.assertEqual((GR / "docs/squad/memory/decisions.jsonl").read_text(), "{}\n")
        br = git("branch", "--list", cwd=GR).stdout
        r = subprocess.run([PY, "tools/squad/gitflow.py", "feature-start", "D99", "x", "--demand", ID_B],
                           cwd=GR, env=envg, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("D99", r.stdout + r.stderr)
        self.assertEqual(git("branch", "--list", cwd=GR).stdout, br)
        self.assertEqual(git("rev-list", "--count", "HEAD", cwd=GR).stdout.strip(), "1")
        # QA-D23-1 (ac4df23): demanda AUSENTE do log também sai 2 (contrato §5.1), sem criar branch
        r = subprocess.run([PY, "tools/squad/gitflow.py", "feature-start", "D1", "x", "--demand", ID_AUS],
                           cwd=GR, env=envg, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(ID_AUS, r.stderr)
        self.assertIn("não encontrada", r.stderr)
        self.assertEqual(git("branch", "--list", cwd=GR).stdout, br)
        self.assertEqual(git("rev-list", "--count", "HEAD", cwd=GR).stdout.strip(), "1")

    def test_ca8_github_sync_estado_ao_lado_do_log(self):
        gs = TMP / "gs"
        gs.mkdir()
        glog = gs / "decisions.jsonl"
        glog.write_text(json.dumps({"id": "cccccccccccc", "ts": "2026-09-25T00:00:00+00:00", "agent": "orquestrador",
                                    "type": "decision", "title": f"{MARK} sync"}) + "\n")
        (gs / "github-sync.json").write_text(json.dumps({"processed": [], "issues": {"_diario": {
            "number": 1, "url": "u", "closed": False}}, "project": {"url": "u", "id": "P", "fields": {}}}))
        env = {**ENV0, "SQUAD_LOG": str(glog), "PATH": SAFE_PATH, "HOME": str(TMP / "home-gs")}
        r = subprocess.run([PY, str(SQ / "github_sync.py")], env=env, capture_output=True, text=True)
        st = json.loads((gs / "github-sync.json").read_text())
        self.assertIn("cccccccccccc", st["processed"], (r.stdout + r.stderr)[-500:])
        self.assertEqual(sha(WT_SYNC), BEFORE["wt_sync"])

    def test_ca8_triage_grava_validation_no_temporario(self):
        data = make_data("data-triage")
        tl = TMP / "t.jsonl"
        tl.write_text(json.dumps({"id": ID_D, "ts": "2026-09-25T00:00:00+00:00", "agent": "humano",
                                  "type": "task", "title": f"Demanda: {MARK} triagem", "kind": "operacao"}) + "\n")
        env = {**ENV0, "SQUAD_LOG": str(tl), "SQUAD_ROOT_DATA": str(data), "PATH": SAFE_PATH,
               "SQUAD_TRANSCRIPTS": str(TMP / "tr-tri"), "HOME": str(TMP / "home-tri")}
        r = subprocess.run([PY, str(SQ / "triage.py"), ID_D, "--runner", "claude"], env=env,
                           capture_output=True, text=True, cwd=REPO)
        rows = product.read_rows(tl)
        self.assertTrue(any(e.get("type") == "validation" for e in rows), (r.stdout + r.stderr)[-500:])
        runs = (REPO / ".squad/runs")
        now = sorted(p.name for p in runs.glob("*")) if runs.exists() else []
        self.assertEqual(now, BEFORE["wt_runs"], "runs do triage não podem cair no .squad/runs do worktree")


# ====================================================================== CA-10 / CA-11 / CA-12
class T06Transcricoes(unittest.TestCase):
    def test_ca10_run_agent_worktree_transcript_exato(self):
        home = TMP / "home-ca10"
        home.mkdir()
        wt2 = TMP / "wt-x"
        wt2.mkdir()
        data = make_data("data-ca10")
        env = {**ENV0, "HOME": str(home), "PATH": SAFE_PATH, "SQUAD_ROOT_DATA": str(data)}
        r = subprocess.run([PY, str(SQ / "run_agent.py"), "qa", f"{MARK} run", "--worktree", str(wt2)], env=env,
                           capture_output=True, text=True)
        metas = list((data / ".squad/runs").glob("*.json"))
        self.assertEqual(len(metas), 1, r.stdout + r.stderr)
        meta = json.loads(metas[0].read_text())
        exp = home / ".claude/projects" / product._slug(wt2) / f"{meta.get('sessionId')}.jsonl"
        self.assertEqual(meta.get("transcript"), str(exp))
        self.assertTrue(exp.exists())
        self.assertEqual(meta.get("model"), "claude-opus-5-5")
        # /api/state mostra o modelo da run (modelSource ≠ none) com HOME temporário e sem SQUAD_TRANSCRIPTS
        srv, base = start_server(server_env(data, HOME=str(home), SQUAD_TRANSCRIPTS=None))
        try:
            st = jget(base, "/api/state")
        finally:
            stop(srv)
        run = next((x for x in st["runs"] if x["id"] == meta["id"]), None)
        self.assertIsNotNone(run, [x["id"] for x in st["runs"]])
        self.assertEqual(run["model"], "claude-opus-5-5")

    def test_ca11_dados_em_outro_lugar_varre_principal_e_worktree(self):
        """SQUAD_ROOT_DATA ≠ raiz do código, HOME temporário: runs do run_agent aparecem e as transcrições da cópia
        principal e de um worktree REGISTRADO (git worktree list, só leitura) são varridas por collect_runs/enrich_log."""
        wts, main = product._worktrees(REPO)
        if not main:
            self.skipTest("sem cópia principal (develop) registrada")
        others = [w for w in wts if not product.same_path(w, REPO) and not product.same_path(w, main)]
        if not others:
            self.skipTest("sem outro worktree registrado")
        other = others[0]
        home = TMP / "home-ca11"
        data = make_data("data-ca11")
        log = data / "docs/squad/memory/decisions.jsonl"
        ts_m, ts_w = "2026-09-25T10:00:00+00:00", "2026-09-25T10:05:00+00:00"
        log.write_text("".join(json.dumps(e) + "\n" for e in [
            {"id": ID_A1, "ts": ts_m, "agent": "backend", "type": "progress", "title": f"{MARK}-CA11-MAIN"},
            {"id": ID_A2, "ts": ts_w, "agent": "qa", "type": "progress", "title": f"{MARK}-CA11-WT"},
            {"id": ID_A3, "ts": ts_w, "agent": "qa", "type": "progress", "title": f"{MARK}-CA11-NADA"}]))

        def tr(where, name, ts, agent, title, model):
            d = home / ".claude/projects" / product._slug(where)
            d.mkdir(parents=True, exist_ok=True)
            cmd = f'python3 tools/squad/log.py --agent {agent} --type progress --title "{title}"'
            (d / f"{name}.jsonl").write_text(json.dumps({
                "type": "assistant", "timestamp": ts.replace("+00:00", "Z"),
                "message": {"model": model, "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                          "input": {"command": cmd}}]}}) + "\n")
        tr(main, "s-main", ts_m, "backend", f"{MARK}-CA11-MAIN", "claude-opus-5-5")
        tr(other, "s-wt", ts_w, "qa", f"{MARK}-CA11-WT", "claude-sonnet-4-6")
        # run gravada pelo run_agent com os dados no data_root temporário
        env = {**ENV0, "HOME": str(home), "PATH": SAFE_PATH, "SQUAD_ROOT_DATA": str(data)}
        (TMP / "wt-ca11").mkdir()
        r = subprocess.run([PY, str(SQ / "run_agent.py"), "qa", f"{MARK} run ca11", "--worktree", str(TMP / "wt-ca11")],
                           env=env, capture_output=True, text=True)
        metas = list((data / ".squad/runs").glob("*.json"))
        self.assertEqual(len(metas), 1, r.stdout + r.stderr)
        meta = json.loads(metas[0].read_text())
        # a pasta da própria cópia de dados/código NÃO existe no HOME temporário: só main e worktree foram criados
        env_s = server_env(data, HOME=str(home), SQUAD_TRANSCRIPTS=None)
        code = ("import sys, json; sys.path.insert(0, 'tools/squad'); import product; "
                "print(json.dumps([str(x) for x in product.transcript_dirs()]))")
        dirs = json.loads(subprocess.run([PY, "-c", code], cwd=REPO, env=env_s, capture_output=True,
                                         text=True).stdout.strip().splitlines()[-1])
        self.assertIn(str(home / ".claude/projects" / product._slug(main)), dirs)
        self.assertIn(str(home / ".claude/projects" / product._slug(other)), dirs)
        srv, base = start_server(env_s)
        try:
            st = jget(base, "/api/state")
        finally:
            stop(srv)
        by = {e["id"]: e for e in st["log"]}
        self.assertEqual((by[ID_A1]["modelSource"], by[ID_A1]["model"]),
                         ("transcript", "claude-opus-5-5"), "transcrição da cópia principal varrida (enrich_log)")
        self.assertEqual((by[ID_A2]["modelSource"], by[ID_A2]["model"]),
                         ("transcript", "claude-sonnet-4-6"), "transcrição do worktree registrado varrida")
        self.assertEqual(by[ID_A3]["modelSource"], "none")
        run = next((x for x in st["runs"] if x["id"] == meta["id"]), None)
        self.assertIsNotNone(run, "run do run_agent em data_root/.squad/runs aparece em /api/state")
        self.assertEqual(run["model"], "claude-opus-5-5")

    def test_ca12_squad_transcripts_exclusivo(self):
        os.environ["SQUAD_TRANSCRIPTS"] = str(TMP / "so-esta")
        try:
            self.assertEqual(product.transcript_dirs(), [TMP / "so-esta"])
            self.assertEqual(product.transcript_dir_for(TMP / "qualquer"), TMP / "so-esta")
        finally:
            del os.environ["SQUAD_TRANSCRIPTS"]
        self.assertEqual(product.transcript_dir_for(pathlib.Path("/a b/c.d")),
                         pathlib.Path.home() / ".claude/projects" / product._slug("/a b/c.d"))


# ====================================================================== CA-13 (API com log reordenado)
class T07PainelReordenado(unittest.TestCase):
    def test_ca13_api_com_log_reordenado(self):
        data = make_data("data-swap", lines=swap_d7_d8(COPY.read_text().splitlines()))
        srv, base = start_server(server_env(data, SQUAD_TRANSCRIPTS=str(TMP / "tr-swap")))
        try:
            st = jget(base, "/api/state")
            live = jget(base, "/api/live")
        finally:
            stop(srv)
        for i, c in TABLE.items():
            self.assertEqual(st["codes"][i], c)
        self.assertEqual(set(live), LIVE_KEYS)
        # a página usa o mapa do servidor (código congelado) — nenhuma posição (§4.6)
        html = (REPO / "squad-control/index.html").read_text()
        self.assertIn("state.codes", html)


# ====================================================================== CA-9 (por último)
class T99NadaNoReal(unittest.TestCase):
    def test_ca9_nada_no_real(self):
        self.assertEqual(sha(WT_LOG), BEFORE["wt_log"], "log do worktree intacto (sha/tamanho/mtime)")
        self.assertEqual(sha(WT_SYNC), BEFORE["wt_sync"], "github-sync.json do worktree intacto")
        now = REAL_LOG.read_bytes()
        self.assertTrue(now.startswith(BEFORE["real_bytes"]), "log real: só append de terceiros")
        # Só EVENTOS contam (nada de substring em texto livre: um defeito pode citar ids/marcas no título/detalhe):
        # id sintético desta execução, `demand`/`code` de task apontando para ele, ou título criado por este teste.
        for log in (REAL_LOG, WT_LOG):
            for r in product.read_rows(log):
                self.assertNotIn(r.get("id"), SYNTH_IDS, (log, r.get("id")))
                if r.get("type") == "task":
                    for k in ("demand", "code"):
                        self.assertNotIn(r.get(k), SYNTH_IDS, (log, k, r.get("id")))
                title = str(r.get("title") or "")
                self.assertFalse(title.startswith((MARK, f"Demanda: {MARK}")), (log, r.get("id"), title))
        runs = REPO / ".squad/runs"
        self.assertEqual(sorted(p.name for p in runs.glob("*")) if runs.exists() else [], BEFORE["wt_runs"])


if __name__ == "__main__":
    unittest.main()
