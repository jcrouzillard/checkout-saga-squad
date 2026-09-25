#!/usr/bin/env python3
"""D24 (ADR-025) — ensaio automatizado do publicador do Squad Control (`docs/contracts/publicacao-do-squad-control.md`).

Tudo em repositórios git TEMPORÁRIOS (seed → origin bare local → cópia principal `main` em develop + clone `dev` que
faz os "PRs"), portas livres ≥ 20000, `SQUAD_CHAT_RUNNER=fake`, PATH sem claude/codex, `SQUAD_GH=/usr/bin/false`,
docker nunca consultado (`SQUAD_TESTENV_PROBE=0`). Nenhum teste abre conexão com a porta do CONFIG; ela só aparece na
asserção de recusa do CA-15. Diretório-base: `$QA_D24_BASE` (padrão: `tempfile.mkdtemp`, que precisa estar sob um
diretório temporário para a guarda estrutural valer).

Classes (independentes; cada uma com seu sandbox):
  Guardas            CA-15 (porta do CONFIG recusada antes de git/kill/bind), CA-4 (não principal / fora de develop),
                     CA-24 (ensure nunca adota; start sem TTY recusa; --yes adota)
  ParadaGraciosa     CA-9 com SQUAD_SUPERVISED=1 (R3 do G2): SIGTERM → interrompida/reinicio_publicacao com o texto
                     parcial, runner morto ≤ 8 s, registro devolvido pelo SSE do servidor novo
  PublicadorFalso    servidor falso (tests/squad/publicador_fake_server.py): CA-3, CA-5, CA-6, CA-7 (livre < 20 s e
                     interrupção em 20 ± 2 s), CA-10, CA-16, CA-17, CA-18, CA-19, CA-22, CA-23 (MERGE_HEAD)
  PublicadorReal     server.py real: CA-1 (merge → publicação ≤ 45/60 s), CA-2 (import quebrado barrado no pré-voo),
                     CA-8 (403/400/409/202), R2 (202 + 409 publicacao_em_andamento; 5 paralelos), CA-7 com resposta
                     longa real + CA-9 pelo fluxo real, R1 (merge que muda a memória com o log sujo e escritor
                     contínuo: ≤ 60 s, 0 perdidos e 0 duplicados por id), CA-20 (/api/live e /api/instance), CA-21
Execução: `python3 tests/squad/test_publicador_d24.py` (~8 min) ou uma classe: `... PublicadorFalso`.
"""
import http.client
import json
import os
import pathlib
import random
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

HERE = pathlib.Path(__file__).resolve().parent
W = HERE.parents[1]
BASE = pathlib.Path(os.environ.get("QA_D24_BASE") or tempfile.mkdtemp(prefix="qa-d24-")).resolve()
GIT = "/usr/bin/git" if os.path.exists("/usr/bin/git") else shutil.which("git")
IDENT = {"GIT_AUTHOR_NAME": "qa", "GIT_AUTHOR_EMAIL": "qa@example.invalid",
         "GIT_COMMITTER_NAME": "qa", "GIT_COMMITTER_EMAIL": "qa@example.invalid"}
SYS_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
FAKE_CMD = json.dumps(["python3", "tests/squad/publicador_fake_server.py", "--port", "{port}"])
SEED_LOG = [{"id": f"{i:012x}", "ts": "2026-09-25T10:00:00+00:00", "agent": "orquestrador", "type": "progress",
             "title": f"evento semente {i}"} for i in range(1, 6)]


# ================================================================ utilidades
def g(cwd, *args, check=True) -> str:
    p = subprocess.run([GIT, *args], cwd=str(cwd), capture_output=True, text=True, env={**os.environ, **IDENT})
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} falhou: {p.stderr}")
    return p.stdout.strip()


def listening(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def free_port() -> int:
    for _ in range(500):
        p = random.randint(20000, 39000)
        if listening(p):
            continue
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("sem porta livre")


def req(port, method, path, body=None, ctype="application/json", host=None, origin=True, timeout=10):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    h = {"Host": host or f"localhost:{port}"}
    if origin:
        h["Origin"] = f"http://{host or f'localhost:{port}'}"
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h["Content-Type"] = ctype
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    raw = r.read()
    c.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw.decode("utf-8", "replace")


def wait_for(fn, timeout, step=0.5, msg="condição"):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = fn()
        if last:
            return last
        time.sleep(step)
    raise AssertionError(f"tempo esgotado ({timeout} s) esperando {msg}; último: {last!r}")


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True


def kill_tree_matching(needle: str):
    out = subprocess.run(["pgrep", "-f", needle], capture_output=True, text=True).stdout.split()
    for pid in out:
        if int(pid) != os.getpid():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass


# ================================================================ sandbox: seed → origin bare → main (develop) + dev
class Sandbox:
    def __init__(self, name: str, fake: bool, extra_env: dict | None = None):
        self.dir = BASE / name
        if self.dir.exists():
            kill_tree_matching(str(self.dir))
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.main, self.dev, self.origin = self.dir / "main", self.dir / "dev", self.dir / "origin.git"
        self.ctl, self.bin = self.dir / "ctl", self.dir / "bin"
        self.gitlog = self.dir / "git-commands.log"
        self.port = free_port()
        self.fake = fake
        self._seed()
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        rec = self.bin / "gitrec"
        rec.write_text(f'#!/bin/sh\necho "$(pwd)|$*" >> "{self.gitlog}"\nexec {GIT} "$@"\n')
        rec.chmod(0o755)
        self.ctl.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("SQUAD_") and k not in ("PATH", "PYTHONPATH")}
        env.update(IDENT)
        env.update({
            "PATH": f"{self.bin}:{SYS_PATH}", "SQUAD_GIT": str(rec), "SQUAD_GH": "/usr/bin/false",
            "SQUAD_CHAT_RUNNER": "fake", "SQUAD_CHAT_FAKE": str(self.main / "tests/squad/conversa_fake_runner.py"),
            "SQUAD_CHAT_TIMEOUT_S": "240", "SQUAD_TRANSCRIPTS": str(self.dir / "trans"),
            "SQUAD_TESTENV_PROBE": "0", "SQUAD_TESTENV_SPAWN": "0", "SQUAD_FAKE_CTL": str(self.ctl),
            "SQUAD_PUBLISH_CANDIDATE_PORT": str(free_port()),
        })
        if fake:
            env["SQUAD_PUBLISH_COMMAND"] = FAKE_CMD
        env.update(extra_env or {})
        self.env = env

    def _seed(self):
        seed = self.dir / "seed"
        seed.mkdir()
        ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".squad")
        for d in ("tools/squad", "squad-control"):
            shutil.copytree(W / d, seed / d, ignore=ign)
        shutil.copytree(W / "docs/squad", seed / "docs/squad", ignore=shutil.ignore_patterns("memory", "__pycache__"))
        mem = seed / "docs/squad/memory"
        (mem / "handoffs").mkdir(parents=True)
        (mem / "handoffs/1-semente.md").write_text("semente\n")
        (mem / "decisions.jsonl").write_text("".join(json.dumps(e) + "\n" for e in SEED_LOG))
        (seed / "tests/squad").mkdir(parents=True)
        for f in ("conversa_fake_runner.py", "publicador_fake_server.py"):
            shutil.copy2(HERE / f, seed / "tests/squad" / f)
        for f in ("pom.xml", "CHANGELOG.md", "Makefile", "AGENTS.md"):
            if (W / f).exists():
                shutil.copy2(W / f, seed / f)
        (seed / ".gitignore").write_text(".squad/\n__pycache__/\n*.pyc\n")
        g(seed, "init", "-q", "-b", "develop")
        g(seed, "add", "-A")
        g(seed, "commit", "-qm", "semente")
        g(self.dir, "clone", "-q", "--bare", str(seed), str(self.origin))
        g(self.dir, "clone", "-q", "-b", "develop", str(self.origin), str(self.main))
        g(self.dir, "clone", "-q", "-b", "develop", str(self.origin), str(self.dev))
        shutil.rmtree(seed)

    # ------------------------------------------------------------ comandos
    def pub(self, *args, root=None, stdin=subprocess.DEVNULL, timeout=180) -> subprocess.CompletedProcess:
        cmd = ["python3", str(self.main / "tools/squad/publisher.py"), *args, "--root", str(root or self.main)]
        return subprocess.run(cmd, cwd=str(root or self.main), env=self.env, stdin=stdin, capture_output=True,
                              text=True, timeout=timeout)

    def start(self, *extra):
        r = self.pub("start", "--port", str(self.port), *extra)
        assert r.returncode == 0, f"start: rc {r.returncode}\n{r.stdout}\n{r.stderr}\n{self.tail_pub()}"
        return r

    def stop(self):
        return self.pub("stop", timeout=60)

    def close(self):
        try:
            self.stop()
        except Exception:
            pass
        kill_tree_matching(str(self.dir))

    # ------------------------------------------------------------ estado
    @property
    def sdir(self):
        return self.main / ".squad/squad-control"

    def status(self) -> dict:
        try:
            return json.loads((self.sdir / "status.json").read_text())
        except (OSError, ValueError):
            return {}

    def server_pid(self):
        return (self.status().get("server") or {}).get("pid")

    def sup_pid(self):
        try:
            return int((self.sdir / "supervisor.pid").read_text().strip())
        except (OSError, ValueError):
            return None

    def tail_pub(self, n=40) -> str:
        p = self.sdir / "publisher.log"
        return "\n".join(p.read_text(errors="replace").splitlines()[-n:]) if p.exists() else ""

    def log_path(self):
        return self.main / "docs/squad/memory/decisions.jsonl"

    def events(self) -> list[dict]:
        out = []
        for ln in self.log_path().read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    def squad_events(self, since=0) -> list[dict]:
        return [e for e in self.events()[since:] if str(e.get("type", "")).startswith("squad-")]

    def wait_result(self, sha: str, timeout: float, types=("squad-updated", "squad-update-failed"), since=0,
                    **match) -> dict:
        def f():
            for e in self.events()[since:]:
                if e.get("type") in types and sha.startswith(e.get("commit") or "-") and \
                        all(e.get(k) == v for k, v in match.items()):
                    return e
            return None
        try:
            return wait_for(f, timeout, msg=f"{types} de {sha[:7]} {match}")
        except AssertionError as ex:
            raise AssertionError(f"{ex}\n--- publisher.log ---\n{self.tail_pub()}") from None

    def head(self):
        return g(self.main, "rev-parse", "HEAD")

    def gitlog_lines(self) -> int:
        return len(self.gitlog.read_text().splitlines()) if self.gitlog.exists() else 0

    def gitlog_since(self, n) -> list[str]:
        return self.gitlog.read_text().splitlines()[n:] if self.gitlog.exists() else []

    # ------------------------------------------------------------ "PR" integrado na develop (clone dev → origin)
    def merge(self, files: dict, msg="PR de teste") -> str:
        d = self.dev
        g(d, "fetch", "-q", "origin")
        g(d, "checkout", "-q", "-B", "develop", "origin/develop")
        br = f"feature/qa-{uuid.uuid4().hex[:6]}"
        g(d, "checkout", "-qb", br)
        for rel, content in files.items():
            p = d / rel
            if content is None:
                p.unlink()
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            if callable(content):
                p.write_text(content(p.read_text() if p.exists() else ""))
            else:
                p.write_text(content)
        g(d, "add", "-A")
        g(d, "commit", "-qm", msg)
        g(d, "checkout", "-q", "develop")
        g(d, "merge", "-q", "--no-ff", br, "-m", f"Merge {br}")
        g(d, "push", "-q", "origin", "develop")
        return g(d, "rev-parse", "HEAD")


def marker(tag):
    return {"squad-control/qa-marker.txt": f"{tag} {uuid.uuid4().hex}\n"}


def mode_file(mode, tag=""):
    return {"tests/squad/publicador_fake_mode.txt": mode + "\n", **marker(tag or mode)}


# ================================================================ CA-15, CA-4, CA-24
class Guardas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox("guardas", fake=True)

    @classmethod
    def tearDownClass(cls):
        cls.sb.close()

    def test_ca15_porta_do_config_recusada_antes_de_qualquer_git(self):
        sb = self.sb
        n0 = sb.gitlog_lines()
        for args, rc_esperado in ((("start", "--port", "7070", "--yes"), 2), (("ensure", "--port", "7070"), 0),
                                  (("run", "--port", "7070"), 2)):
            r = sb.pub(*args, timeout=30)
            self.assertEqual(r.returncode, rc_esperado, (args, r.stdout, r.stderr))
            self.assertIn("recusado", r.stderr, args)
            self.assertIn("7070", r.stderr, args)                       # CA-15: única menção à porta do CONFIG
        self.assertEqual(sb.gitlog_since(n0), [], "CA-15: nenhum comando git antes da recusa")
        self.assertFalse(sb.sdir.exists(), "CA-15: nada criado (nem lock, nem status, nem log)")

    def test_ca04_fora_da_copia_principal_ou_de_develop(self):
        sb = self.sb
        g(sb.dev, "checkout", "-q", "-B", "release/9.9.9")
        try:
            r = sb.pub("start", "--port", str(free_port()), root=sb.dev, timeout=30)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("cópia principal em develop", r.stderr)
            self.assertFalse((sb.dev / ".squad/squad-control/status.json").exists())
        finally:
            g(sb.dev, "checkout", "-q", "develop")

    def test_ca24_primeira_adocao(self):
        sb = self.sb
        port = free_port()
        env = {**sb.env, "SQUAD_ENV": "produtivo"}
        env.pop("SQUAD_SUPERVISED", None)
        old = subprocess.Popen(["python3", "tests/squad/publicador_fake_server.py", "--port", str(port)],
                               cwd=str(sb.main), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
        try:
            wait_for(lambda: listening(port), 10, 0.1, "servidor não supervisionado")
            r = sb.pub("ensure", "--port", str(port), timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            time.sleep(1)
            self.assertIsNone(old.poll(), "CA-24: ensure não encerra o servidor atual")
            self.assertFalse((sb.sdir / "supervisor.pid").exists(), "ensure não sobe supervisor com a porta ocupada")
            r = sb.pub("start", "--port", str(port), timeout=30)          # stdin /dev/null: sem TTY
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("confirmação no terminal", r.stderr)
            self.assertIsNone(old.poll(), "CA-24: start sem TTY não encerra o servidor atual")
            # adoção de fato (só --yes, que é só para testes): encerra o antigo e sobe o supervisionado na mesma porta
            sb.port = port
            r = sb.start("--yes")
            wait_for(lambda: old.poll() is not None, 15, 0.2, "servidor antigo encerrado")
            st = sb.status()
            self.assertEqual(st.get("state"), "no-ar", st)
            self.assertNotEqual(st["server"]["pid"], old.pid)
            code, inst = req(port, "GET", "/api/instance")
            self.assertEqual((code, inst["build"]["pid"]), (200, st["server"]["pid"]))
        finally:
            sb.stop()
            if old.poll() is None:
                old.kill()


# ================================================================ CA-9 (R3 do G2): SIGTERM gracioso supervisionado
class ParadaGraciosa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = BASE / "ca9"
        shutil.rmtree(cls.dir, ignore_errors=True)
        cls.dir.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls):
        kill_tree_matching(str(cls.dir))

    def start(self, data, port, supervised=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SQUAD_")}
        env.update({"PATH": SYS_PATH, "SQUAD_ROOT_DATA": str(data), "SQUAD_LOG": str(data / "docs/squad/memory/decisions.jsonl"),
                    "SQUAD_TRANSCRIPTS": str(self.dir / "trans"), "SQUAD_TESTENV_PROBE": "0",
                    "SQUAD_TESTENV_SPAWN": "0", "SQUAD_CHAT_RUNNER": "fake",
                    "SQUAD_CHAT_FAKE": str(HERE / "conversa_fake_runner.py"), "SQUAD_CHAT_TIMEOUT_S": "240",
                    "SQUAD_GH": "/usr/bin/false", "SQUAD_ENV": "teste"})
        if supervised:
            env["SQUAD_SUPERVISED"] = "1"
        with open(self.dir / f"srv-{port}.err", "w") as err:
            p = subprocess.Popen([sys.executable, str(W / "tools/squad/server.py"), "--port", str(port)], env=env,
                                 stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
        wait_for(lambda: listening(port), 20, 0.1, "server.py no ar")
        return p

    def test_ca09_sigterm_interrompe_com_texto_parcial_e_sse_do_novo(self):
        for i, via in enumerate(("kill", "killpg", "kill")):
            with self.subTest(via=via):
                data = self.dir / f"data-{i}"
                (data / "docs/squad/memory").mkdir(parents=True)
                (data / "docs/squad/memory/decisions.jsonl").write_text(json.dumps(SEED_LOG[0]) + "\n")
                port = free_port()
                p = self.start(data, port)
                _, c = req(port, "POST", "/api/conversas", {})
                cid = c["id"]
                code, r = req(port, "POST", f"/api/conversas/{cid}/mensagens", {"text": "DORMIR"})
                self.assertEqual(code, 202, r)
                turn = r["turn"]
                wait_for(lambda: req(port, "GET", "/api/conversas")[1].get("busy"), 10, 0.2, "turno ativo")
                wait_for(lambda: "parcial" in json.dumps(req(port, "GET", f"/api/conversas/{cid}")[1]), 10, 0.2,
                         "texto parcial transmitido")
                mine = subprocess.run(["pgrep", "-P", str(p.pid)], capture_output=True, text=True).stdout.split()
                self.assertTrue(mine, "runner falso é filho do servidor")
                t0 = time.monotonic()
                (os.killpg if via == "killpg" else os.kill)(p.pid, signal.SIGTERM)
                rc = p.wait(15)
                dt = time.monotonic() - t0
                self.assertEqual(rc, 0, f"saída graciosa ({via})")
                self.assertLessEqual(dt, 8.0, f"CA-9: ≤ 8 s ({dt:.1f})")
                time.sleep(0.5)
                vivos = [x for x in mine if pid_alive(x) and "conversa_fake_runner" in subprocess.run(
                    ["ps", "-o", "command=", "-p", x], capture_output=True, text=True).stdout]
                self.assertEqual(vivos, [], "CA-9: o runner deixa de existir")
                # servidor novo nos mesmos dados: registro final e SSE de reconexão
                port2 = free_port()
                p2 = self.start(data, port2)
                try:
                    _, v = req(port2, "GET", f"/api/conversas/{cid}")
                    msgs = [m for m in v.get("messages", []) if m.get("role") == "orquestrador" and m.get("turn") == turn]
                    self.assertTrue(msgs, v)
                    m = msgs[-1]
                    self.assertEqual((m.get("status"), m.get("code")), ("interrompida", "reinicio_publicacao"), m)
                    self.assertIn("parcial", m.get("text") or "", "texto já transmitido preservado")
                    cc = http.client.HTTPConnection("127.0.0.1", port2, timeout=10)
                    cc.request("GET", f"/api/conversas/{cid}/turnos/{turn}/stream",
                               headers={"Host": f"localhost:{port2}"})
                    body = cc.getresponse().read(20000).decode("utf-8", "replace")
                    cc.close()
                    self.assertIn("reinicio_publicacao", body, "CA-9: SSE do servidor novo devolve o registro final")
                finally:
                    p2.terminate()
                    p2.wait(15)


# ================================================================ servidor falso: supervisor, travas, rollback, quedas
class PublicadorFalso(unittest.TestCase):
    """Ordem importa (test_NN): um único supervisor percorre os estados do §5."""
    FAST = {"SQUAD_PUBLISH_POLL_S": "2,1", "SQUAD_PUBLISH_STABLE_S": "2", "SQUAD_PUBLISH_HEALTH_TIMEOUT_S": "8",
            "SQUAD_PUBLISH_STOP_GRACE_S": "3"}

    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox("falso", fake=True, extra_env=cls.FAST)
        cls.sb.start()

    @classmethod
    def tearDownClass(cls):
        cls.sb.close()

    def one_result(self, sha, since):
        """CA-10: exatamente um squad-updated OU um squad-update-failed por publicação."""
        rs = [e for e in self.sb.squad_events(since) if e["type"] in ("squad-updated", "squad-update-failed")
              and sha.startswith(e.get("commit") or "-")]
        self.assertEqual(len(rs), 1, rs)
        return rs[0]

    def test_01_start_lock_unico(self):
        sb = self.sb
        st = sb.status()
        self.assertEqual(st.get("state"), "no-ar", st)
        self.assertTrue(st.get("supervised"))
        pid = st["server"]["pid"]
        e = [x for x in sb.squad_events() if x["type"] == "squad-updated"]
        self.assertEqual((len(e), e[0]["trigger"]), (1, "inicio"))
        for k in ("commit", "display", "trigger", "sameCommit", "durationSec", "waitedSec"):
            self.assertIn(k, e[0])
        r = sb.pub("start", "--port", str(sb.port), timeout=30)          # CA-16: 2º start só mostra o estado
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("publicador no ar", r.stdout)
        self.assertEqual(sb.server_pid(), pid)
        starts = [json.loads(x) for x in (sb.ctl / "starts.jsonl").read_text().splitlines()]
        self.assertEqual(sum(1 for s in starts if s["env"] == "produtivo"), 1, "um único servidor produtivo")
        self.assertEqual(starts[-1]["supervised"], "1")

    def test_02_ca03_merge_so_de_docs_nao_reinicia(self):
        sb = self.sb
        pid, n = sb.server_pid(), len(sb.events())
        sha = sb.merge({"docs/qa-nota.md": "só docs\n", "services/qa/README.md": "fora de watch_paths\n"})
        wait_for(lambda: sb.head() == sha, 20, msg="fast-forward da cópia principal")
        time.sleep(6)
        self.assertEqual(sb.server_pid(), pid, "CA-3: servidor não reiniciado")
        self.assertEqual(sb.squad_events(n), [], "CA-3: nenhum evento squad-*")

    def test_03_ca07_livre_antes_de_20s(self):
        sb = self.sb
        n = len(sb.events())
        (sb.ctl / "busy_until").write_text(str(time.time() + 12))
        sha = sb.merge(marker("ca7-livre"))
        seen = []

        def watch():
            st = sb.status()
            if st.get("state") == "aguardando-ponto-seguro":
                seen.append(st)
            return any(e.get("type") == "squad-updated" and sha.startswith(e.get("commit") or "-")
                       for e in sb.events()[n:])
        wait_for(watch, 60, 0.3, "squad-updated")
        e = self.one_result(sha, n)
        self.assertEqual(e["type"], "squad-updated")
        self.assertTrue(0 < e["waitedSec"] < 20, e)
        self.assertNotIn("interrupted", e)
        self.assertTrue(seen and seen[0].get("deadline") and seen[0].get("busy"), "estado com deadline e busy")

    def test_04_ca07_ocupado_30s_interrompe_em_20s(self):
        sb = self.sb
        n = len(sb.events())
        (sb.ctl / "busy_until").write_text(str(time.time() + 300))
        try:
            sha = sb.merge(marker("ca7-ocupado"))
            e = sb.wait_result(sha, 90, since=n)
        finally:
            (sb.ctl / "busy_until").unlink()
        self.assertEqual(e["type"], "squad-updated", e)
        self.assertTrue(18 <= e["waitedSec"] <= 22, f"CA-7: 20 ± 2 s, veio {e['waitedSec']}")
        self.assertEqual(e.get("interrupted"), {"conversa": "c-fake", "turn": 1})
        self.one_result(sha, n)

    def test_05_ca23_merge_head_trava_antes_do_fetch(self):
        sb = self.sb
        mh = pathlib.Path(g(sb.main, "rev-parse", "--git-path", "MERGE_HEAD"))
        mh = mh if mh.is_absolute() else sb.main / mh
        mh.write_text(sb.head() + "\n")
        time.sleep(2.5)            # um ciclo (2 s) que já passou das travas antes do MERGE_HEAD termina antes da marca
        head0, n, k = sb.head(), len(sb.events()), sb.gitlog_lines()
        try:
            sha = sb.merge(marker("ca23"))
            time.sleep(10)
            cmds = sb.gitlog_since(k)
            escrita = [c for c in cmds if any(f"|{w}" in c or f" {w} " in f" {c.split('|', 1)[1]} "
                                              for w in ("fetch", "merge", "worktree", "ls-remote", "checkout", "reset"))]
            self.assertEqual(escrita, [], "CA-23: nenhum ls-remote/fetch/merge/worktree com MERGE_HEAD")
            self.assertTrue(cmds, "o supervisor continuou checando (rev-parse)")
            self.assertEqual(sb.head(), head0)
            self.assertEqual(sb.squad_events(n), [], "CA-23: nenhum evento")
        finally:
            mh.unlink()
        e = sb.wait_result(sha, 40, since=n)
        self.assertEqual(e["type"], "squad-updated")

    def test_06_ca06_codigo_sujo_bloqueia_publicacao_pela_cli(self):
        sb = self.sb
        n = len(sb.events())
        f = sb.main / "squad-control/qa-marker.txt"
        orig = f.read_text()
        f.write_text(orig + "sujo\n")
        try:
            r = sb.pub("publish", "--when", "now", timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            e = sb.wait_result(sb.head(), 30, types=("squad-update-failed",), since=n)
            self.assertEqual((e["phase"], e["trigger"], e["rolledBack"]), ("guard", "cli", False), e)
            self.assertIn("mudança rastreada", e.get("detail", ""))
            rq = [x for x in sb.events()[n:] if x["type"] == "squad-publish-requested"]
            self.assertEqual(len(rq), 1)
            self.assertEqual((rq[0]["agent"], rq[0]["trigger"], rq[0]["requestId"]),
                             ("humano", "cli", e["requestId"]))
        finally:
            f.write_text(orig)
        self.assertEqual(sb.status().get("state"), "no-ar")

    def test_07_ca05_a_frente_com_codigo_nao_e_tocado(self):
        sb = self.sb
        (sb.main / "tools/squad/qa-local.txt").write_text("commit local de código\n")
        g(sb.main, "add", "tools/squad/qa-local.txt")
        g(sb.main, "commit", "-qm", "local")
        local, n, k = sb.head(), len(sb.events()), sb.gitlog_lines()
        sha = sb.merge(marker("ca5"))
        time.sleep(8)
        cmds = [c.split("|", 1)[1] for c in sb.gitlog_since(k)]
        self.assertFalse([c for c in cmds if c.split()[0] in ("fetch", "merge", "rebase", "reset", "checkout",
                                                                "ls-remote")], cmds)
        self.assertEqual(sb.head(), local, "CA-5: HEAD inalterado")
        self.assertEqual(sb.squad_events(n), [])
        g(sb.main, "reset", "-q", "--keep", "HEAD~1")                # limpeza do teste (preserva o log sujo)
        e = sb.wait_result(sha, 40, since=n)
        self.assertEqual(e["type"], "squad-updated")

    def test_08_ca02_ca18_quebra_pos_troca_rollback_e_revertido_persistente(self):
        sb = self.sb
        n = len(sb.events())
        before = sb.head()
        sha = sb.merge(mode_file("commit-errado"))
        e = sb.wait_result(sha, 60, since=n)
        self.assertEqual((e["type"], e["phase"], e["rolledBack"]), ("squad-update-failed", "health", True), e)
        self.assertTrue(before.startswith(e["runningCommit"]), e)
        self.assertIn("commit errado", e.get("detail", ""))
        st = sb.status()
        self.assertEqual((st["state"], st["server"]["mode"], st["failedCommit"]), ("revertido", "anterior", sha))
        code, inst = req(sb.port, "GET", "/api/instance")
        self.assertEqual((inst["build"]["mode"], inst["freshness"]["state"], inst["build"]["commitFull"]),
                         ("anterior", "revertido", before))
        prev = sb.dir / "plankton-squad-prev"
        self.assertEqual(g(prev, "rev-parse", "HEAD"), before)
        self.assertEqual(g(prev, "symbolic-ref", "-q", "HEAD", check=False), "", "worktree destacado")
        time.sleep(8)                                                    # ≥ 3 ciclos de 2 s
        again = [x for x in sb.squad_events(n) if sha.startswith(x.get("commit") or "-")]
        self.assertEqual(len(again), 1, "CA-18: 0 tentativas novas do mesmo SHA")

    def test_09_ca18_start_com_failed_commit_sobe_o_anterior_e_ca16_stop(self):
        sb = self.sb
        r = sb.stop()
        self.assertIn("publicador parado", r.stdout)
        wait_for(lambda: not listening(sb.port), 10, 0.2, "porta livre após stop")
        self.assertEqual(sb.status().get("state"), "parado")
        sb.start()
        st = sb.status()
        self.assertEqual((st["state"], st["server"]["mode"]), ("revertido", "anterior"), st)

    def test_10_sha_novo_publica(self):
        sb = self.sb
        n = len(sb.events())
        sha = sb.merge(mode_file("ok", "conserto"))
        e = sb.wait_result(sha, 60, since=n)
        self.assertEqual(e["type"], "squad-updated", e)
        self.assertEqual((sb.status()["state"], sb.status()["server"]["mode"]), ("no-ar", "principal"))

    def test_11_ca17_sigkill_sobe_de_novo_em_5s(self):
        sb = self.sb
        n = len(sb.events())
        pid = sb.server_pid()
        os.kill(pid, signal.SIGKILL)
        t0 = time.monotonic()
        wait_for(lambda: sb.server_pid() not in (None, pid) and listening(sb.port), 10, 0.2, "servidor de volta")
        self.assertLessEqual(time.monotonic() - t0, 5.0, "CA-17: ≤ 5 s")
        c = [x for x in sb.squad_events(n) if x["type"] == "squad-server-crashed"]
        self.assertEqual(len(c), 1, c)
        self.assertEqual((c[0]["restarts"], c[0]["mode"]), (1, "principal"))

    def test_12_ca17_cinco_quedas_em_5min_rollback(self):
        sb = self.sb
        n = len(sb.events())
        sha = sb.merge(mode_file("sai-apos-3s"))
        up = sb.wait_result(sha, 60, since=n)
        self.assertEqual(up["type"], "squad-updated")                   # passou na estabilidade (2 s) e caiu depois
        e = sb.wait_result(sha, 120, types=("squad-update-failed",), since=n)
        self.assertEqual((e["phase"], e["rolledBack"]), ("health", True), e)
        self.assertIn("quedas em 5 min", e.get("detail", ""))
        crashed = [x for x in sb.squad_events(n) if x["type"] == "squad-server-crashed"]
        self.assertEqual([x["restarts"] for x in crashed], [1, 5], "evento na 1ª e a cada 5 quedas")
        self.assertEqual((sb.status()["state"], sb.status()["server"]["mode"]), ("revertido", "anterior"))

    def test_13_conserto(self):
        sb = self.sb
        n = len(sb.events())
        sha = sb.merge(mode_file("ok", "conserto2"))
        self.assertEqual(sb.wait_result(sha, 60, since=n)["type"], "squad-updated")

    def test_14_ca22_pagina_de_manutencao_e_tentar_de_novo(self):
        sb = self.sb
        n = len(sb.events())
        (sb.ctl / "break_produtivo").write_text("1")
        try:
            sha = sb.merge(marker("ca22"))
            e = sb.wait_result(sha, 60, since=n)
            self.assertEqual((e["type"], e["phase"], e["rolledBack"]), ("squad-update-failed", "rollback", False), e)
            self.assertEqual(sb.status()["state"], "fora-do-ar")
            code, html = req(sb.port, "GET", "/")
            self.assertEqual(code, 200)
            self.assertIn("Squad Control fora do ar", html)
            self.assertIn(sha[:7], html)
            self.assertIn("Tentar de novo", html)
            self.assertEqual(req(sb.port, "GET", "/api/state"), (503, {"code": "fora_do_ar",
                                                                        "error": "Squad Control fora do ar"}))
            self.assertEqual(req(sb.port, "GET", "/api/live")[0], 503)
            self.assertEqual(req(sb.port, "POST", "/api/squad-control/publish", {"when": "now"},
                                 host="evil.example")[0], 403)
        finally:
            (sb.ctl / "break_produtivo").unlink()
        m = len(sb.events())
        code, r = req(sb.port, "POST", "/api/squad-control/publish", {"when": "now", "confirm": True})
        self.assertEqual(code, 202, r)
        e = sb.wait_result(sha, 60, since=m, requestId=r["requestId"])
        self.assertEqual((e["type"], e["trigger"]), ("squad-updated", "botao"), e)
        self.assertEqual(sb.status()["state"], "no-ar")

    def test_15_ca19_execv_mantem_o_pid_do_servidor(self):
        sb = self.sb
        n = len(sb.events())
        sup = sb.sup_pid()
        sha = sb.merge({"tools/squad/publisher.py": lambda s: s + "\n# QA D24: mudança inócua (CA-19)\n"})
        e = sb.wait_result(sha, 60, since=n)
        self.assertEqual(e["type"], "squad-updated", e)
        srv = sb.server_pid()
        wait_for(lambda: "supervisor reiniciado por execv" in sb.tail_pub(80), 30, msg="execv no publisher.log")
        time.sleep(3)
        self.assertEqual(sb.sup_pid(), sup, "execv mantém o pid do supervisor")
        self.assertTrue(pid_alive(sup))
        self.assertEqual(sb.server_pid(), srv, "CA-19: mesmo pid do servidor (não reinicia de novo)")
        self.assertTrue(pid_alive(srv))
        self.assertEqual(sb.status()["state"], "no-ar")
        self.assertEqual(sb.status()["supervisor"]["commit"], sha[:7], "o processo novo carregou o código novo")
        self.one_result(sha, n)

    def test_16_ca19_selftest_falha_mantem_o_supervisor_antigo(self):
        sb = self.sb
        n = len(sb.events())
        sup = sb.sup_pid()
        sha = sb.merge({"tools/squad/publisher.py": lambda s: s + "# QA D24: 2ª mudança\n",
                        "tools/squad/alerts.py": lambda s: "raise RuntimeError('QA D24: selftest deve falhar')\n" + s})
        e = sb.wait_result(sha, 60, since=n)
        self.assertEqual(e["type"], "squad-updated", e)
        f = sb.wait_result(sha, 60, types=("squad-update-failed",), since=n)
        self.assertEqual((f["phase"], f["rolledBack"]), ("supervisor", False), f)
        self.assertEqual(sb.sup_pid(), sup)
        self.assertEqual(sb.status()["state"], "no-ar")
        self.assertTrue(listening(sb.port))

    def test_17_ca16_stop_libera_a_porta(self):
        sb = self.sb
        srv = sb.server_pid()
        r = sb.stop()
        self.assertEqual(r.returncode, 0)
        wait_for(lambda: not listening(sb.port), 10, 0.2, "porta livre")
        self.assertFalse(pid_alive(srv))
        self.assertEqual(sb.status()["state"], "parado")
        self.assertEqual(sb.pub("status").returncode, 1)


# ================================================================ server.py real: CA-1, CA-2, botão, R1, R2
class PublicadorReal(unittest.TestCase):
    """Padrões do CONFIG (poll 15 s, estabilidade 10 s): os tempos medidos são os do aceite."""

    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox("real", fake=False)
        cls.sb.start()

    @classmethod
    def tearDownClass(cls):
        cls.sb.close()

    def chat(self, text):
        port = self.sb.port
        _, c = req(port, "POST", "/api/conversas", {})
        code, r = req(port, "POST", f"/api/conversas/{c['id']}/mensagens", {"text": text})
        self.assertEqual(code, 202, r)
        busy = wait_for(lambda: req(port, "GET", "/api/conversas")[1].get("busy"), 15, 0.2, "turno ativo")
        return c["id"], r["turn"], busy

    def final_msg(self, cid, turn):
        _, v = req(self.sb.port, "GET", f"/api/conversas/{cid}")
        ms = [m for m in v.get("messages", []) if m.get("role") == "orquestrador" and m.get("turn") == turn]
        return ms[-1] if ms else None

    def runner_alive(self):
        out = subprocess.run(["pgrep", "-f", "conversa_fake_runner"], capture_output=True, text=True).stdout.split()
        return [p for p in out if str(self.sb.dir) in subprocess.run(["ps", "-o", "command=", "-p", p],
                                                                     capture_output=True, text=True).stdout]

    def test_01_no_ar_e_ca20(self):
        sb = self.sb
        st = sb.status()
        self.assertEqual(st.get("state"), "no-ar")
        code, inst = req(sb.port, "GET", "/api/instance")
        self.assertEqual(set(inst), {"environment", "build", "freshness"})
        self.assertEqual((inst["build"]["mode"], inst["build"]["pid"], inst["environment"]["name"]),
                         ("principal", st["server"]["pid"], "produtivo"))
        times, size = [], 0
        for _ in range(20):
            t0 = time.monotonic()
            c = http.client.HTTPConnection("127.0.0.1", sb.port, timeout=5)
            c.request("GET", "/api/live", headers={"Host": f"localhost:{sb.port}"})
            body = c.getresponse().read()
            times.append(time.monotonic() - t0)
            size = len(body)
        live = json.loads(body)
        self.assertEqual(set(live["publication"]), {"state", "target", "deadline", "trigger", "lastResult", "mode"})
        self.assertLessEqual(len(json.dumps(live["publication"]).encode()), 1024)
        self.assertLessEqual(sorted(times)[18], 0.3, "CA-20: p95 ≤ 300 ms")
        self.assertLessEqual(size, 64 * 1024)
        code, v = req(sb.port, "GET", "/api/squad-control/publication")
        self.assertEqual((code, v["supervised"], v["canPublish"], v["reason"]), (200, True, True, None))
        self.assertEqual(req(sb.port, "GET", "/api/squad-control/publication", host="evil.example")[0], 403)

    def test_02_ca01_merge_publica_em_ate_45s_e_pagina_nova_em_60s(self):
        sb = self.sb
        n = len(sb.events())
        title = f"QA-D24-{uuid.uuid4().hex[:6]}"
        sha = sb.merge({"squad-control/index.html": lambda s: s.replace("<title>", f"<title>{title} ", 1)})
        t0 = time.monotonic()
        e = sb.wait_result(sha, 60, since=n)
        dt = time.monotonic() - t0
        self.assertEqual(e["type"], "squad-updated", e)
        self.assertLessEqual(dt, 45, f"CA-1: evento em {dt:.1f} s")
        wait_for(lambda: title in str(req(sb.port, "GET", "/")[1]), 60 - dt, msg="título novo servido")
        code, inst = req(sb.port, "GET", "/api/instance")
        self.assertEqual((inst["build"]["commitFull"], inst["build"]["pid"]), (sha, sb.server_pid()))
        live = req(sb.port, "GET", "/api/live")[1]
        self.assertEqual((live["publication"]["state"], live["publication"]["lastResult"]["type"]),
                         ("no-ar", "squad-updated"))
        type(self).ca1_seconds = round(dt, 1)

    def test_03_ca02_import_quebrado_barrado_no_preflight(self):
        sb = self.sb
        n = len(sb.events())
        pid, srv_commit = sb.server_pid(), sb.status()["server"]["commit"]
        sha = sb.merge({"tools/squad/server.py": lambda s: s.replace("\nimport ", "\nimport conversa_inexistente  # QA\nimport ", 1)})
        e = sb.wait_result(sha, 75, since=n)
        self.assertEqual((e["type"], e["phase"], e["rolledBack"]), ("squad-update-failed", "preflight", False), e)
        self.assertIn("conversa_inexistente", e.get("detail", ""))
        self.assertEqual(sb.server_pid(), pid, "CA-2: o servidor nunca cai")
        self.assertEqual(req(sb.port, "GET", "/api/instance")[1]["build"]["commitFull"], srv_commit)
        lr = req(sb.port, "GET", "/api/live")[1]["publication"]["lastResult"]
        self.assertEqual((lr["type"], lr["commit"]), ("squad-update-failed", sha[:7]))
        time.sleep(16)                                                   # 1 ciclo: não tenta de novo
        self.assertEqual(len([x for x in sb.squad_events(n) if sha.startswith(x.get("commit") or "-")]), 1)
        m = len(sb.events())
        # conserto = reverter o import E mudar outra coisa: um revert puro volta ao código no ar e (corretamente, §5.1.4)
        # não publica nada — o diff contra o commit no ar fica vazio
        fix = sb.merge({"tools/squad/server.py": lambda s: s.replace("import conversa_inexistente  # QA\n", "", 1),
                        **marker("conserto-import")})
        self.assertEqual(sb.wait_result(fix, 75, since=m)["type"], "squad-updated")

    def test_04_ca08_r2_botao_e_ca09_pelo_fluxo_real(self):
        sb = self.sb
        self.settle()
        P = "/api/squad-control/publish"
        code, r = req(sb.port, "POST", P, {"when": "now"}, host="evil.example")
        self.assertEqual((code, r.get("code")), (403, "origem_invalida"))
        code, r = req(sb.port, "POST", P, b'{"when":"now"}', ctype="text/plain")
        self.assertEqual((code, r.get("code")), (400, "pedido_invalido"))
        code, r = req(sb.port, "POST", P, {"when": "agora"})
        self.assertEqual((code, r.get("code")), (400, "pedido_invalido"))
        cid, turn, busy = self.chat("DORMIR")
        n = len(sb.events())
        code, r = req(sb.port, "POST", P, {"when": "now"})
        self.assertEqual((code, r.get("code"), r.get("busy")), (409, "resposta_em_andamento", busy))
        code, r1 = req(sb.port, "POST", P, {"when": "now", "confirm": True})
        self.assertEqual(code, 202, r1)
        code, r2 = req(sb.port, "POST", P, {"when": "now", "confirm": True})          # R2: logo em seguida
        self.assertEqual((code, r2.get("code")), (409, "publicacao_em_andamento"), r2)
        self.assertIn(r2.get("pendingRequestId"), (None, r1["requestId"]))   # só no caminho sob o flock
        v = req(sb.port, "GET", "/api/squad-control/publication")[1]
        self.assertEqual((v["canPublish"], v["reason"]), (False, "publicacao_em_andamento"))
        e = sb.wait_result(sb.head(), 60, since=n, requestId=r1["requestId"])
        self.assertEqual((e["type"], e["trigger"], e["sameCommit"], e.get("interrupted")),
                         ("squad-updated", "botao", True, busy), e)
        rq = [x for x in sb.events()[n:] if x["type"] == "squad-publish-requested"]
        self.assertEqual(len(rq), 1, "R2: um único pedido gravado")
        self.assertEqual((rq[0]["agent"], rq[0]["requestId"], rq[0]["confirm"]), ("humano", r1["requestId"], True))
        self.assertEqual(len([x for x in sb.events()[n:] if x.get("requestId") == r1["requestId"]
                              and x["type"] in ("squad-updated", "squad-update-failed")]), 1, "CA-10")
        m = self.final_msg(cid, turn)                                    # CA-9 pelo fluxo real (SQUAD_SUPERVISED=1)
        self.assertEqual((m.get("status"), m.get("code")), ("interrompida", "reinicio_publicacao"), m)
        self.assertIn("parcial", m.get("text") or "")
        self.assertEqual(self.runner_alive(), [], "CA-9: runner encerrado")

    def settle(self):
        sb = self.sb
        wait_for(lambda: sb.status().get("state") == "no-ar" and not list((sb.sdir / "requests").glob("*.json"))
                 and listening(sb.port), 90, 0.5, "supervisor ocioso")

    def test_05_r2_cinco_pedidos_paralelos(self):
        sb = self.sb
        self.settle()
        n = len(sb.events())
        res = []
        ths = [threading.Thread(target=lambda: res.append(req(sb.port, "POST", "/api/squad-control/publish",
                                                              {"when": "safe"}))) for _ in range(5)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        codes = sorted(c for c, _ in res)
        self.assertEqual(codes, [202, 409, 409, 409, 409], res)
        self.assertTrue(all(b.get("code") == "publicacao_em_andamento" for c, b in res if c == 409))
        rid = next(b["requestId"] for c, b in res if c == 202)
        e = sb.wait_result(sb.head(), 60, since=n, requestId=rid)
        self.assertEqual(e["type"], "squad-updated")
        self.assertEqual(len([x for x in sb.events()[n:] if x["type"] == "squad-publish-requested"]), 1)

    def test_06_ca07_resposta_longa_interrompida_em_20s(self):
        sb = self.sb
        self.settle()
        cid, turn, busy = self.chat("DORMIR")
        n = len(sb.events())
        sha = sb.merge({"squad-control/qa-marker.txt": f"ca7 real {uuid.uuid4().hex}\n"})
        e = sb.wait_result(sha, 90, since=n)
        self.assertEqual(e["type"], "squad-updated", e)
        self.assertTrue(18 <= e["waitedSec"] <= 22, e)
        self.assertEqual(e.get("interrupted"), busy)
        m = self.final_msg(cid, turn)
        self.assertEqual((m.get("status"), m.get("code")), ("interrompida", "reinicio_publicacao"), m)
        self.assertIn("parcial", m.get("text") or "")
        self.assertEqual(self.runner_alive(), [])

    def test_07_r1_merge_que_muda_a_memoria_com_log_sujo(self):
        sb = self.sb
        self.settle()
        log = sb.log_path()
        written, stop = [], threading.Event()

        def writer():   # como o log.py/servidor: open(a) + 1 write por evento, a cada 0,1 s
            i = 0
            while not stop.is_set():
                e = {"id": uuid.uuid4().hex[:12], "ts": "2026-09-25T19:00:00+00:00", "agent": "qa",
                     "type": "progress", "title": f"r1 local {i}"}
                with open(log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(e) + "\n")
                written.append(e["id"])
                i += 1
                time.sleep(0.1)
        th = threading.Thread(target=writer)
        th.start()
        try:
            time.sleep(1.5)
            self.assertTrue(g(sb.main, "status", "--porcelain", "--", "docs/squad/memory/decisions.jsonl"))
            remote_ids = [uuid.uuid4().hex[:12] for _ in range(3)]
            n = len(sb.events())
            sha = sb.merge({
                "docs/squad/memory/decisions.jsonl": lambda s: s + "".join(json.dumps(
                    {"id": rid, "ts": "2026-09-25T18:59:00+00:00", "agent": "auditor", "type": "gate",
                     "title": "r1 remoto"}) + "\n" for rid in remote_ids),
                "docs/squad/memory/handoffs/99-r1.md": "brief\n",
                "squad-control/index.html": lambda s: s.replace("<title>", "<title>R1 ", 1)})
            t0 = time.monotonic()
            e = sb.wait_result(sha, 90, since=n)
            dt = time.monotonic() - t0
            time.sleep(1.0)
        finally:
            stop.set()
            th.join()
        time.sleep(0.6)
        ids = [x.get("id") for x in sb.events()]
        from collections import Counter
        c = Counter(ids)
        self.assertEqual(e["type"], "squad-updated", e)
        self.assertLessEqual(dt, 60, f"R1: publicação em {dt:.1f} s")
        self.assertEqual(sb.head(), sha)
        self.assertEqual([i for i in written if i not in c], [], "R1: 0 eventos locais perdidos")
        self.assertEqual([i for i in remote_ids if i not in c], [], "R1: 0 eventos remotos perdidos")
        self.assertEqual([k for k, v in c.items() if v > 1], [], "R1: 0 duplicados por id")
        self.assertTrue((sb.main / "docs/squad/memory/handoffs/99-r1.md").exists())
        mdir = sb.sdir / "merge"
        self.assertEqual(sorted(os.listdir(mdir)) if mdir.exists() else [], [], "cópias apagadas")
        type(self).r1 = {"segundos": round(dt, 1), "locais": len(written), "remotos": 3, "linhas": len(ids)}

    def test_08_ca08_ca21_sem_supervisor(self):
        sb = self.sb
        data = sb.dir / "sem-sup"
        (data / "docs/squad/memory").mkdir(parents=True)
        (data / "docs/squad/memory/decisions.jsonl").write_text(json.dumps(SEED_LOG[0]) + "\n")
        port = free_port()
        env = {**sb.env, "SQUAD_ROOT_DATA": str(data), "SQUAD_ENV": "produtivo"}
        env.pop("SQUAD_SUPERVISED", None)
        p = subprocess.Popen(["python3", "tools/squad/server.py", "--port", str(port)], cwd=str(sb.main), env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            wait_for(lambda: listening(port), 20, 0.1, "server.py sem supervisor")
            self.assertIsNone(req(port, "GET", "/api/live")[1]["publication"])
            v = req(port, "GET", "/api/squad-control/publication")[1]
            self.assertEqual((v["supervised"], v["canPublish"], v["reason"]), (False, False, "sem_supervisor"))
            code, r = req(port, "POST", "/api/squad-control/publish", {"when": "now"})
            self.assertEqual((code, r.get("code")), (409, "sem_supervisor"))
            self.assertIn("make squad", r.get("error", ""))
        finally:
            p.terminate()
            p.wait(15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
