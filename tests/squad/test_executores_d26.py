#!/usr/bin/env python3
"""D26 (ADR-027, contrato docs/contracts/executor-e-modelo-por-agente.md §12) — QA: CA-1..CA-20 + ressalvas do G2-D26.

Tudo com dados TEMPORÁRIOS (SQUAD_ROOT_DATA/SQUAD_LOG/SQUAD_TRANSCRIPTS num diretório de teste) e atalhos FALSOS de
`claude`/`codex` (tests/squad/fixtures/d26/bin: custo zero de tokens; `CODEX_HOME` vazio = "sem login"). Nada toca o
log real, a 7070, `~/.claude` ou `~/.codex` (CLAUDE_CONFIG_DIR e CODEX_HOME apontam para o diretório de teste).

  python3 -m unittest tests/squad/test_executores_d26.py -v      (ou: cd tests/squad && python3 -m unittest test_executores_d26)

CA-11 (run real curta no Codex) e CA-H1..H3 são aceites humanos: roteiro em tests/ui/checklist-executores-d26.md.
"""
import fcntl
import hashlib
import http.client
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
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools/squad"
FAKEBIN = pathlib.Path(__file__).resolve().parent / "fixtures/d26/bin"
EXE = [sys.executable, str(TOOLS / "executores.py")]
RUN_AGENT = [sys.executable, str(TOOLS / "run_agent.py")]
GATE = [sys.executable, str(TOOLS / "gate.py")]
HOOK_CMD = json.loads((REPO / ".claude/settings.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="qa-d26-", dir=os.environ.get("QA_D26_TMP") or None))
ROLES = ["orquestrador", "arquiteto", "backend", "devops", "observabilidade", "frontend", "qa", "auditor"]
FRONT = {"arquiteto": "opus", "backend": "opus", "devops": "sonnet", "observabilidade": "sonnet", "frontend": "opus",
         "qa": "sonnet", "auditor": "opus", "orquestrador": None}
# ids de demanda de teste (12 hex): nunca aparecem no log real
D1, D2, D3 = "d26a00000001", "d26a00000002", "d26a00000003"
REAL_LOGS = [REPO / "docs/squad/memory/decisions.jsonl",
             REPO.parent / "plankton/docs/squad/memory/decisions.jsonl"]
sys.path.insert(0, str(TOOLS))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def read(log: pathlib.Path) -> list[dict]:
    try:
        return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    except OSError:
        return []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Data:
    """Um diretório de dados isolado (log, runtime, transcrições, CODEX_HOME, CLAUDE_CONFIG_DIR, registro de chamadas)."""

    n = 0

    def __init__(self, name: str, codex_login=True, claude_login=True, rows=None, **env):
        Data.n += 1
        self.root = TMP / f"{Data.n:02d}-{name}"
        self.log = self.root / "docs/squad/memory/decisions.jsonl"
        self.log.parent.mkdir(parents=True, exist_ok=True)
        (self.root / "tr").mkdir()
        (self.root / "codexhome").mkdir()
        (self.root / "claudecfg").mkdir()
        if codex_login:
            (self.root / "codexhome/auth.json").write_text("{}")
        self.calls = self.root / "calls.jsonl"
        # `python3` do gancho = o intérprete dos testes (o /usr/bin/python3 do macOS é 3.9, sem tomllib); nunca
        # /opt/homebrew/bin no PATH (lá estão o `claude`/`codex` reais)
        (self.root / "pybin").mkdir()
        (self.root / "pybin/python3").symlink_to(sys.executable)
        self.log.write_text("".join(json.dumps(r) + "\n" for r in (rows or [])))
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("SQUAD_", "GIT_", "FAKE_")) and k not in ("CLAUDECODE", "CLAUDE_PROJECT_DIR")}
        self.env = {**base, "PATH": f"{FAKEBIN}:{self.root / 'pybin'}:/usr/bin:/bin",
                    "SQUAD_ROOT_DATA": str(self.root), "SQUAD_LOG": str(self.log),
                    "SQUAD_TRANSCRIPTS": str(self.root / "tr"), "SQUAD_TESTENV_PROBE": "0",
                    "SQUAD_TESTENV_SPAWN": "0", "CODEX_HOME": str(self.root / "codexhome"),
                    "CLAUDE_CONFIG_DIR": str(self.root / "claudecfg"), "FAKE_CALLS": str(self.calls),
                    "FAKE_CLAUDE_LOGIN": "1" if claude_login else "0"}
        self.env.pop("ANTHROPIC_API_KEY", None)
        self.env.update({k: str(v) for k, v in env.items()})

    @property
    def cfg_path(self) -> pathlib.Path:
        return self.root / ".squad/executores.json"

    def rows(self) -> list[dict]:
        return read(self.log)

    def events(self, typ: str) -> list[dict]:
        return [e for e in self.rows() if e.get("type") == typ]

    def call_list(self) -> list[dict]:
        return read(self.calls)

    def run(self, args, stdin=None, env=None, timeout=60) -> subprocess.CompletedProcess:
        return subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout,
                              env={**self.env, **(env or {})}, cwd=str(REPO))

    def exe(self, *args, **kw):
        return self.run([*EXE, *args], **kw)

    def resolve(self, role, *args, **kw) -> tuple[int, dict]:
        p = self.exe("resolve", role, *args, "--json", **kw)
        try:
            return p.returncode, json.loads(p.stdout)
        except json.JSONDecodeError:
            return p.returncode, {"_stdout": p.stdout, "_stderr": p.stderr}

    def write_cfg(self, squad=("claude", None), agents=None, policy="padrao", version=None):
        cur = json.loads(self.cfg_path.read_text()) if self.cfg_path.exists() else {"version": 0}
        ag = {r: None for r in ROLES}
        for r, v in (agents or {}).items():
            ag[r] = {"runner": v[0], "model": v[1]} if v else None
        cfg = {"schema": 1, "version": version or cur["version"] + 1, "updatedAt": "2026-09-25T20:00:00Z",
               "squad": {"runner": squad[0], "model": squad[1]}, "agents": ag,
               "policy": {"onUnavailable": policy}, "codexAck": None}
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg_path.write_text(json.dumps(cfg))

    def append(self, **e):
        e.setdefault("id", hashlib.sha1(json.dumps(e, sort_keys=True).encode()).hexdigest()[:12])
        e.setdefault("ts", iso(datetime.now(timezone.utc)))
        with self.log.open("a") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e

    def task(self, demand, title="Demanda de teste D26"):
        return self.append(id=demand, type="task", agent="humano", title=f"Demanda: {title}", to="orquestrador",
                           ts="2026-09-25T10:00:00+00:00")

    def dry(self, role, *args, **kw) -> tuple[int, dict, str]:
        p = self.run([*RUN_AGENT, role, "tarefa de teste", *args, "--dry-run"], **kw)
        try:
            return p.returncode, json.loads(p.stdout), p.stderr
        except json.JSONDecodeError:
            return p.returncode, {}, p.stderr + p.stdout


def tearDownModule():
    # nenhum evento de teste no log real (ids de demanda e diretório temporário)
    for log in REAL_LOGS:
        if log.exists():
            text = log.read_text(errors="ignore")
            for mark in (D1, D2, D3, str(TMP)):
                assert mark not in text, f"marca de teste {mark} no log real {log}"
    if os.environ.get("QA_D26_KEEP") != "1":
        shutil.rmtree(TMP, ignore_errors=True)


# ====================================================================== CA-1 · CA-2 · CA-3 · CA-7
class A_Resolvedor(unittest.TestCase):
    def test_ca1_precedencia_demanda_foto_agente_squad(self):
        d = Data("ca1")
        d.task(D1)
        d.write_cfg(squad=("claude", "sonnet"), agents={"arquiteto": ("codex", "gpt-5.6-sol")})
        c, r = d.resolve("backend", "--no-check")
        self.assertEqual((c, r["runner"], r["model"], r["source"]), (0, "claude", "sonnet", "squad"),
                         "null herda executor E modelo do padrão")
        c, r = d.resolve("arquiteto", "--no-check")
        self.assertEqual((r["runner"], r["model"], r["source"], r["via"]), ("codex", "gpt-5.6-sol", "agente", "run_agent"))
        # foto da demanda: tirada no 1º resolve --demand (fora de plantao/conversa/triagem)
        c, r = d.resolve("backend", "--demand", D1, "--no-check")
        self.assertEqual((r["runner"], r["source"]), ("claude", "squad"))
        self.assertEqual(len(d.events("executor-snapshot")), 1)
        # muda a configuração geral: a demanda com foto não muda; a atual sim
        d.write_cfg(squad=("claude", None), agents={"backend": ("codex", None)})
        c, r = d.resolve("backend", "--demand", D1, "--no-check")
        self.assertEqual((r["runner"], r["model"], r["source"]), ("claude", "sonnet", "squad"), "foto > agente")
        c, r = d.resolve("backend", "--no-check")
        self.assertEqual((r["runner"], r["source"]), ("codex", "agente"))
        # plantao/conversa/triagem usam a configuração ATUAL mesmo com demanda
        c, r = d.resolve("backend", "--demand", D1, "--context", "triagem", "--no-check")
        self.assertEqual((r["runner"], r["source"]), ("codex", "agente"))
        # troca só nesta demanda > foto
        d.append(type="executor-config", agent="humano", scope="demand", demand=D1, role="backend",
                 before={"runner": "claude", "model": "sonnet"}, after={"runner": "codex", "model": "gpt-5.6-sol"},
                 by="humano", title="Backend só nesta demanda")
        c, r = d.resolve("backend", "--demand", D1, "--no-check")
        self.assertEqual((r["runner"], r["model"], r["source"]), ("codex", "gpt-5.6-sol", "demanda"))
        # troca desfeita (after null) → volta à foto
        d.append(type="executor-config", agent="humano", scope="demand", demand=D1, role="backend",
                 before={"runner": "codex", "model": "gpt-5.6-sol"}, after=None, by="humano", title="volta")
        c, r = d.resolve("backend", "--demand", D1, "--no-check")
        self.assertEqual((r["runner"], r["source"]), ("claude", "squad"))
        # modelo null = padrão do executor: no claude, alias do frontmatter; Orquestrador sem --model
        d.write_cfg()
        for role in ROLES:
            c, r = d.resolve(role, "--no-check")
            self.assertEqual((r["model"], r["modelArg"]), (None, FRONT[role]), role)

    def test_ca2_migracao_uma_vez_e_variaveis_ignoradas(self):
        d = Data("ca2")
        env = {"SQUAD_RUNNER": "codex", "SQUAD_MODEL": "gpt-5.6-sol", "SQUAD_CHAT_RUNNER": "claude",
               "SQUAD_CHAT_MODEL": "opus"}
        c, r = d.resolve("backend", "--no-check", env=env)
        self.assertEqual(c, 0, r)
        cfg = json.loads(d.cfg_path.read_text())
        self.assertEqual(cfg["squad"], {"runner": "codex", "model": "gpt-5.6-sol"})
        self.assertEqual(cfg["agents"]["orquestrador"], {"runner": "claude", "model": "opus"})
        self.assertEqual((cfg["version"], cfg["policy"]), (1, {"onUnavailable": "padrao"}))
        mig = [e for e in d.events("executor-config") if e.get("via") == "migracao"]
        self.assertEqual(len(mig), 1)
        # 2ª execução com outro ambiente: nada muda, as variáveis viram aviso
        p = d.exe("resolve", "backend", "--no-check", "--json", env={"SQUAD_RUNNER": "claude", "SQUAD_MODEL": "opus"})
        r = json.loads(p.stdout)
        self.assertEqual((r["runner"], r["model"]), ("codex", "gpt-5.6-sol"))
        self.assertIn("variavel_ignorada:SQUAD_RUNNER", r["warnings"])
        self.assertIn("SQUAD_RUNNER ignorada", p.stderr)
        self.assertEqual(len([e for e in d.events("executor-config") if e.get("via") == "migracao"]), 1)
        self.assertEqual(json.loads(d.cfg_path.read_text())["version"], 1)
        # show lista a variável ignorada
        v = json.loads(d.exe("show", "--json", env={"SQUAD_RUNNER": "claude"}).stdout)
        self.assertIn("SQUAD_RUNNER", v["ignoredEnv"])

    def test_ca2_migracao_squad_codex_fixa_orquestrador_em_claude_q2(self):
        d = Data("ca2q2")
        c, r = d.resolve("orquestrador", "--no-check", env={"SQUAD_RUNNER": "codex"})
        self.assertEqual((c, r["runner"]), (0, "claude"))
        mig = d.events("executor-config")[0]
        self.assertIn("orquestrador_codex_pendente_q2", mig["warnings"])

    def test_ca2_squad_model_dentro_de_run_nunca_migra(self):
        d = Data("ca2run")
        c, r = d.resolve("backend", "--no-check", env={"SQUAD_MODEL": "claude-opus-5-5", "SQUAD_RUN": "r1"})
        self.assertEqual(json.loads(d.cfg_path.read_text())["squad"], {"runner": "claude", "model": None})

    def test_ca3_arquivo_ilegivel_resolve_4_e_run_agent_nao_inicia(self):
        for corrupt in ("{nao é json", json.dumps({"schema": 2, "version": 1}),
                        json.dumps({"schema": 1, "version": 1, "squad": {"runner": "gemini"}, "agents": {},
                                    "policy": {"onUnavailable": "padrao"}})):
            d = Data("ca3")
            d.cfg_path.parent.mkdir(parents=True)
            d.cfg_path.write_text(corrupt)
            c, r = d.resolve("backend", "--no-check")
            self.assertEqual((c, r.get("error")), (4, "configuracao_ilegivel"), corrupt)
            p = d.run([*RUN_AGENT, "backend", "x", "--demand", D1])
            self.assertEqual(p.returncode, 4, p.stderr)
            self.assertEqual(d.call_list(), [], "nenhum executor foi chamado")
            self.assertFalse((d.root / ".squad/runs").exists() and list((d.root / ".squad/runs").glob("*.json")))
            self.assertEqual(d.cfg_path.read_text(), corrupt, "nunca cai num padrão silencioso (arquivo intacto)")

    def test_ca7_foto_uma_por_demanda(self):
        d = Data("ca7")
        d.write_cfg(squad=("claude", None))
        p = d.exe("snapshot", "--demand", D1)
        self.assertEqual(p.returncode, 0, p.stderr)
        d.exe("snapshot", "--demand", D1)
        snaps = d.events("executor-snapshot")
        self.assertEqual(len(snaps), 1)
        self.assertEqual(set(snaps[0]["executors"]), set(ROLES))
        self.assertEqual(snaps[0]["configVersion"], 1)
        d.write_cfg(squad=("codex", None), agents={"orquestrador": ("claude", None)})
        _, r = d.resolve("qa", "--demand", D1, "--no-check")
        self.assertEqual(r["runner"], "claude", "demanda com foto mantém a configuração dela")
        _, r = d.resolve("qa", "--demand", D2, "--no-check")
        self.assertEqual(r["runner"], "codex", "demanda nova usa a nova")
        self.assertEqual(len(d.events("executor-snapshot")), 2)
        # --no-snapshot (triagem) não cria foto
        d.resolve("qa", "--demand", D3, "--no-snapshot", "--no-check")
        self.assertEqual(len(d.events("executor-snapshot")), 2)

    def test_validacao_de_valores_e_codigos(self):
        import executores as ex
        self.assertEqual(ex.validate_pair("claude", "opus", ex.RUNNERS)[0], {"runner": "claude", "model": "opus"})
        for runner, model, code in (("codex", "opus", "modelo_incompativel"), ("claude", "gpt-5", "modelo_incompativel"),
                                    ("codex", "claude-opus-5-5", "modelo_incompativel"), ("gemini", None, "formato_invalido"),
                                    ("claude", "a b", "formato_invalido"), ("claude", "x" * 101, "formato_invalido")):
            with self.assertRaises(ex.ExecError) as cm:
                ex.validate_pair(runner, model, ex.RUNNERS)
            self.assertEqual(cm.exception.code, code, (runner, model))
        self.assertEqual(ex.validate_pair("codex", "llama-3", ex.RUNNERS)[1], ["modelo_fornecedor_desconhecido"])
        with self.assertRaises(ex.ExecError) as cm:
            ex.validate_pair("codex", None, ["claude"])
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("executor_nao_permitido", 5))
        self.assertEqual(ex.via_of("claude", "claude-opus-5-5"), "run_agent")
        self.assertEqual(ex.via_of("claude", "haiku"), "nativo")

    def test_set_e_apply_all_recusam_dentro_de_agente(self):
        d = Data("set7")
        d.write_cfg()
        for extra in ({}, {"SQUAD_RUN": "r1"}, {"CLAUDECODE": "1"}):
            p = d.exe("set", "--scope", "squad", "--runner", "codex", "--by", "humano", env=extra)
            self.assertEqual(p.returncode, 7, p.stderr)   # stdin não é TTY (subprocess) → recusado
            p = d.exe("apply-all", "--runner", "codex", "--by", "humano", env=extra)
            self.assertEqual(p.returncode, 7)
        self.assertEqual(json.loads(d.cfg_path.read_text())["version"], 1)

    def test_q2_orquestrador_codex_recusado_em_todo_caminho(self):
        d = Data("q2")
        d.write_cfg(agents={"orquestrador": ("codex", None)})
        c, r = d.resolve("orquestrador", "--no-check")
        self.assertEqual((c, r["error"]), (5, "orquestrador_codex_pendente_q2"))
        p = d.run([*RUN_AGENT, "orquestrador", "x"])
        self.assertEqual(p.returncode, 5)
        self.assertEqual(d.call_list(), [])
        p = d.exe("check-session", "orquestrador", "--runner", "claude")
        self.assertEqual(p.returncode, 3)
        self.assertIn("plantão desta sessão suspenso", p.stdout)
        d.write_cfg()
        c, r, err = d.dry("orquestrador", "--runner", "codex")
        self.assertEqual(c, 5, err)
        self.assertEqual(d.exe("check-session", "orquestrador", "--runner", "claude").returncode, 0)


# ====================================================================== CA-4 · CA-5 · CA-6 · CA-19
class B_RunAgentPerfis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = Data("perfis")
        cls.d.write_cfg()

    def test_ca4_runner_so_com_dry_run(self):
        for extra in (["--runner", "codex"], ["--model", "opus"]):
            p = self.d.run([*RUN_AGENT, "backend", "x", *extra])
            self.assertEqual(p.returncode, 2)
            self.assertIn("só valem com --dry-run", p.stderr)
        self.assertEqual(self.d.call_list(), [])
        c, r, _ = self.d.dry("backend", "--runner", "codex")
        self.assertEqual((c, r["runner"], r["cmd"][:2]), (0, "codex", ["codex", "exec"]))

    def test_ca5_nao_herda_squad_model_do_pai(self):
        c, r, err = self.d.dry("backend", env={"SQUAD_MODEL": "gpt-x"})
        self.assertEqual(c, 0)
        self.assertEqual(r["cmd"][-2:], ["--model", "opus"], "--model do frontmatter, nunca o do pai")
        self.assertNotIn("gpt-x", json.dumps(r["cmd"]))
        self.assertEqual(r["env"], {"SQUAD_RUN": r["env"]["SQUAD_RUN"]}, "filho só com SQUAD_RUN")
        self.assertIn("SQUAD_MODEL ignorada", err)
        # execução real (claude falso): o filho não recebe o SQUAD_MODEL do pai
        d = Data("ca5real")
        d.write_cfg()
        p = d.run([*RUN_AGENT, "qa", "x", "--demand", D1], env={"SQUAD_MODEL": "gpt-x"})
        self.assertEqual(p.returncode, 0, p.stderr)
        call = d.call_list()[-1]
        self.assertIsNone(call["SQUAD_MODEL"])
        self.assertTrue(call["SQUAD_RUN"])
        self.assertEqual(call["argv"][call["argv"].index("--model") + 1], "sonnet")

    def _cmd(self, role, runner, *extra):
        c, r, err = self.d.dry(role, "--runner", runner, *extra)
        self.assertEqual(c, 0, err)
        return r

    def test_ca6_matriz_perfil_x_executor(self):
        runs = str(self.d.root / ".squad/runs")
        logdir = str(self.d.log.parent)
        for role in ROLES:
            for runner in ("claude", "codex"):
                if role == "orquestrador" and runner == "codex":
                    continue   # Q2 (teste próprio)
                r = self._cmd(role, runner)
                cmd = r["cmd"]
                if runner == "claude":
                    exp_profile = "orquestracao" if role == "orquestrador" else "escrita"   # Q3 desligada: Auditor como hoje
                    self.assertEqual(r["profile"], exp_profile, role)
                    self.assertEqual(cmd[:3], ["claude", "-p", "<prompt>"])
                    i = cmd.index("--permission-mode")
                    self.assertEqual(cmd[i:i + 9], ["--permission-mode", "acceptEdits", "--allowedTools", "Bash", "Read",
                                                    "Write", "Edit", "Glob", "Grep"], role)
                    self.assertNotIn("--setting-sources", cmd)
                    self.assertEqual(r["via"], "nativo")
                else:
                    self.assertEqual(r["via"], "run_agent")
                    if role == "auditor":
                        self.assertEqual(r["profile"], "auditoria")
                        self.assertEqual(cmd, ["codex", "exec", "-s", "read-only", "-C", str(REPO),
                                               "--skip-git-repo-check", "-c", 'approval_policy="never"',
                                               "-c", "mcp_servers={}"])
                    else:
                        self.assertEqual(r["profile"], "escrita")
                        self.assertEqual(cmd, ["codex", "exec", "-s", "workspace-write", "-C", str(REPO),
                                               "--add-dir", logdir, "--add-dir", runs,
                                               "-c", "sandbox_workspace_write.network_access=true",
                                               "--skip-git-repo-check", "-c", 'approval_policy="never"'], role)
                    self.assertNotIn("-m", cmd, "model null no codex = sem -m")
        # triagem (Arquiteto, perfil leitura)
        r = self._cmd("arquiteto", "claude", "--read-only")
        cmd = r["cmd"]
        self.assertEqual(r["profile"], "leitura")
        leit = str(TOOLS / "perfis/leitura.json")
        self.assertEqual(cmd[3:7], ["--setting-sources", "project", "--settings", leit])
        self.assertEqual(cmd[7:11], ["--tools", "Read", "Glob", "Grep"])
        dis = cmd[cmd.index("--disallowedTools") + 1:]
        self.assertEqual(dis[:8], ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"])
        self.assertIn("--strict-mcp-config", cmd)
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        r = self._cmd("arquiteto", "codex", "--read-only")
        self.assertEqual(r["cmd"], ["codex", "exec", "-s", "read-only", "-C", str(REPO), "--skip-git-repo-check",
                                    "-c", 'approval_policy="never"', "-c", "mcp_servers={}"])
        self.assertIn("SOMENTE LEITURA", r["prompt"])
        # conversa (Orquestrador, perfil leitura) — conversa.build_cmd
        import conversa as cv
        cc = cv.build_cmd("claude", {"dataRoot": str(self.d.root), "sessionId": "u1"}, {"prompt": "P", "systemPrompt": "S"})
        self.assertEqual(cc[cc.index("--tools") + 1:cc.index("--tools") + 4], ["Read", "Glob", "Grep"])
        self.assertEqual(cc[cc.index("--setting-sources"):cc.index("--setting-sources") + 4],
                         ["--setting-sources", "project", "--settings", str(TOOLS / "perfis/leitura.json")])
        self.assertEqual(cc[cc.index("--permission-mode") + 1], "dontAsk")
        self.assertIn("--strict-mcp-config", cc)
        for t in ("Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"):
            self.assertIn(t, cc[cc.index("--disallowedTools"):])
        cx = cv.build_cmd("codex", {"dataRoot": str(self.d.root), "sessionId": None}, {"prompt": "P", "systemPrompt": "S"})
        for flag in (["-s", "read-only"], ["-c", 'approval_policy="never"'], ["-c", "mcp_servers={}"]):
            self.assertTrue(any(cx[i:i + 2] == flag for i in range(len(cx))), flag)
        self.assertIn("--skip-git-repo-check", cx)

    def test_ca6_perfil_auditoria_no_claude(self):
        import executores as ex
        cmd = ex.profile_cmd("auditoria", "claude", "P", REPO, self.d.root, self.d.log.parent, self.d.root)
        self.assertEqual(cmd[3:5], ["--setting-sources", "project"])
        settings = json.loads(cmd[cmd.index("--settings") + 1])
        self.assertEqual(settings["permissions"]["defaultMode"], "dontAsk")
        self.assertEqual(settings["permissions"]["allow"], ex.AUDIT_ALLOW)
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "Bash")
        self.assertIn("audit-bash", hook["hooks"][0]["command"])
        self.assertEqual(cmd[cmd.index("--tools") + 1:cmd.index("--tools") + 5], ["Read", "Glob", "Grep", "Bash"])
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        for t in ("Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent"):
            self.assertIn(t, settings["permissions"]["deny"])
            self.assertIn(t, cmd[cmd.index("--disallowedTools"):])
        with self.assertRaises(ex.ExecError):
            ex.profile_cmd("orquestracao", "codex", "P", REPO, self.d.root, self.d.log.parent, self.d.root)

    def test_ca19_perfis_leitura_so_fonte_project(self):
        """CLAUDE_CONFIG_DIR de teste com allow Bash e bypassPermissions: o comando leva só `project` + perfil
        dedicado, e o atalho falso recebe exatamente essas fontes (as regras do usuário não entram)."""
        d = Data("ca19")
        d.write_cfg()
        (d.root / "claudecfg/settings.json").write_text(json.dumps(
            {"permissions": {"allow": ["Bash"], "defaultMode": "bypassPermissions"}}))
        c, r, _ = d.dry("arquiteto", "--read-only")
        self.assertEqual(c, 0)
        cmd = r["cmd"]
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "project")
        prof = json.loads(pathlib.Path(cmd[cmd.index("--settings") + 1]).read_text())
        self.assertEqual(prof["permissions"]["defaultMode"], "dontAsk")
        self.assertEqual(prof["permissions"]["allow"], ["Read", "Glob", "Grep"])
        self.assertIn("Bash", prof["permissions"]["deny"])
        # o .claude/settings.json do projeto (fonte `project`) só tem o gancho: nenhuma permissão
        self.assertNotIn("permissions", json.loads((REPO / ".claude/settings.json").read_text()))
        # execução real do perfil (triagem via run_agent --read-only) → o falso recebe só as fontes do perfil
        p = d.run([*RUN_AGENT, "arquiteto", "x", "--demand", D1, "--read-only", "--no-snapshot"])
        self.assertEqual(p.returncode, 0, p.stderr)
        argv = d.call_list()[-1]["argv"]
        self.assertEqual(argv.count("--setting-sources"), 1)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("bypassPermissions", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)
        aud = json.loads((TOOLS / "perfis/auditoria.json").read_text())
        self.assertEqual(aud["permissions"]["defaultMode"], "dontAsk")
        self.assertNotIn("Bash", aud["permissions"]["allow"], "só Bash(prefixo:*) no auditoria")


# ====================================================================== perfil auditoria endurecido (G2-D26 Q3)
class C_AuditBash(unittest.TestCase):
    def ok(self, cmd):
        import executores as ex
        return ex.audit_bash_ok(cmd, str(REPO))[0]

    def test_permite_so_leitura_do_repositorio(self):
        for c in ("git diff", "git diff HEAD~1 -- tools/squad", "git log --oneline -5", "git show HEAD:AGENTS.md",
                  "git status --short", "ls tools/squad", "ls -la", "git diff --stat origin/develop...HEAD",
                  "git log --format=%H -3"):
            self.assertTrue(self.ok(c), c)

    def test_nega_output_no_index_ext_diff_git_dir_e_abreviacoes(self):
        for c in ("git diff --output=/tmp/x", "git diff HEAD --output=/tmp/x", "git diff --outp=/tmp/x",
                  "git diff --ou=/tmp/x", "git log --output=x", "git show --output=x",
                  "git diff --no-index /etc/passwd x", "git diff --no-ind ~/.ssh/id_rsa a", "git diff --no-i a b",
                  "git diff --ext-diff", "git diff --ext-d", "git diff --textconv", "git diff --git-dir=/x",
                  "git diff --git-d=/x", "git --git-dir=/x diff", "git -C / diff", "git -c core.pager=sh diff",
                  "git diff --work-tree=/", "git diff -O/etc/passwd", "git diff --orderfile=/etc/passwd",
                  "git log --exec=sh", "git diff --pathspec-from-file=/etc/passwd",
                  "git diff; rm -rf x", "git diff && touch x", "git diff | tee x", "git diff > x", "git diff $(id)",
                  "git diff `id`", "ls /", "ls ~/.ssh", "ls ../..", "cat AGENTS.md", "git push", "git checkout x",
                  "git diff ../outro/arquivo", "GIT_DIR=/x git diff", ""):
            self.assertFalse(self.ok(c), c)

    def test_gancho_audit_bash_falha_fechada(self):
        d = Data("auditbash")
        for stdin, code in (('{"tool_input":{"command":"git diff --stat"},"cwd":"%s"}' % REPO, 0),
                            ('{"tool_input":{"command":"git diff --output=/tmp/x"},"cwd":"%s"}' % REPO, 2),
                            ("isto não é json", 2), ("[]", 2)):
            p = d.exe("audit-bash", stdin=stdin)
            self.assertEqual(p.returncode, code, (stdin, p.stderr))


# ====================================================================== CA-8 · gancho guard-agent
class D_GuardAgent(unittest.TestCase):
    def hook(self, d: Data, tool_input, raw=None, project=REPO, extra_env=None):
        stdin = raw if raw is not None else json.dumps({"tool_name": "Agent", "tool_input": tool_input})
        return subprocess.run(["sh", "-c", HOOK_CMD], input=stdin, capture_output=True, text=True, timeout=60,
                              env={**d.env, "CLAUDE_PROJECT_DIR": str(project), **(extra_env or {})})

    def test_matriz_configuracao_padrao_zero_bloqueios(self):
        d = Data("guardpadrao")   # sem executores.json: 1ª chamada migra (configuração padrão)
        blocked, n, t0 = [], 0, time.monotonic()
        for st in ROLES + ["Explore", "general-purpose", "claude"]:
            for model in (None, "opus", "sonnet", "haiku", "fable", "claude-opus-5-5"):
                for demand in (None, D1):
                    prompt = f"Você atua como o agente **{st.capitalize()}**. Tarefa." + (f" --demand {demand}" if demand else "")
                    ti = {"subagent_type": st, "description": "x", "prompt": prompt, **({"model": model} if model else {})}
                    p = self.hook(d, ti)
                    n += 1
                    if p.returncode != 0:
                        blocked.append((st, model, demand, p.returncode, p.stderr[:200]))
        self.assertEqual(n, 132)
        self.assertEqual(blocked, [], "com a configuração padrão o gancho nunca bloqueia")
        per_call = (time.monotonic() - t0) / n
        self.assertLess(per_call, 2.0, f"{per_call:.2f}s por chamada")
        # executor-dispatch agregado: 1 por (papel, demanda) com o mesmo configurado — não 1 por despacho
        disp = d.events("executor-dispatch")
        keys = [(e["role"], e.get("demand")) for e in disp]
        self.assertEqual(len(keys), len(set(keys)), "um evento por (papel, demanda)")
        self.assertEqual(len(disp), 16, "8 papéis × com/sem demanda")
        self.assertTrue(all(e["via"] == "nativo" and e["configured"]["runner"] == "claude" for e in disp))

    def test_ca8_decisoes(self):
        d = Data("guard")
        d.write_cfg(agents={"arquiteto": ("codex", "gpt-5.6-sol"), "qa": ("claude", "sonnet"),
                            "backend": ("claude", "claude-opus-5-5")})
        p = self.hook(d, {"subagent_type": "arquiteto", "prompt": "x"})
        self.assertEqual(p.returncode, 2)
        self.assertIn("run_agent.py", p.stderr)
        self.assertIn('arquiteto "<tarefa>"', p.stderr)
        p = self.hook(d, {"subagent_type": "general-purpose", "prompt": f"Você atua como o agente **Arquiteto** --demand {D1}"})
        self.assertEqual(p.returncode, 2, "general-purpose com 'agente **Arquiteto**' = Arquiteto")
        self.assertIn(f"--demand {D1}", p.stderr)
        p = self.hook(d, {"subagent_type": "general-purpose", "prompt": "rode run_agent --agent arquiteto"})
        self.assertEqual(p.returncode, 2)
        p = self.hook(d, {"subagent_type": "backend", "prompt": "x"})
        self.assertEqual(p.returncode, 2, "modelo de ID exato no claude → via run_agent")
        p = self.hook(d, {"subagent_type": "qa", "prompt": "x", "model": "opus"})
        self.assertEqual(p.returncode, 2, "tool_input.model divergente")
        self.assertIn("sonnet", p.stderr)
        before = len(d.events("executor-dispatch"))
        p = self.hook(d, {"subagent_type": "qa", "prompt": "x", "model": "sonnet"})
        self.assertEqual(p.returncode, 0, p.stderr)
        p = self.hook(d, {"subagent_type": "devops", "prompt": "x"})
        self.assertEqual(p.returncode, 0)
        disp = d.events("executor-dispatch")[before:]
        self.assertEqual([(e["role"], e["via"], e["configured"]["runner"]) for e in disp],
                         [("qa", "nativo", "claude"), ("devops", "nativo", "claude")])
        for ti in ({"subagent_type": "Explore", "prompt": "procure X"}, {"subagent_type": "general-purpose", "prompt": "y"},
                   {"prompt": "sem tipo"}):
            self.assertEqual(self.hook(d, ti).returncode, 0, ti)
        # mudança do configurado gera um novo dispatch (agregado por par)
        n = len(d.events("executor-dispatch"))
        self.hook(d, {"subagent_type": "devops", "prompt": "x"})
        self.assertEqual(len(d.events("executor-dispatch")), n)
        d.write_cfg(agents={"devops": ("claude", "haiku")})
        self.assertEqual(self.hook(d, {"subagent_type": "devops", "prompt": "x"}).returncode, 0)
        self.assertEqual(len(d.events("executor-dispatch")), n + 1)

    def test_falha_aberta_erros_inesperados(self):
        d = Data("guardfalha")
        ti = {"subagent_type": "backend", "prompt": f"x --demand {D1}"}
        for raw in ("não é json", "[1,2]", "", "null", '{"tool_input": "texto"}'):
            p = self.hook(d, None, raw=raw)
            self.assertEqual(p.returncode, 0, (raw, p.stderr))
        # script ausente (worktree antigo sem executores.py)
        empty = TMP / "sem-script"
        empty.mkdir(exist_ok=True)
        self.assertEqual(self.hook(d, ti, project=empty).returncode, 0)
        # data root inexistente
        self.assertEqual(self.hook(d, ti, extra_env={"SQUAD_ROOT_DATA": str(TMP / "nao-existe"),
                                                     "SQUAD_LOG": str(TMP / "nao-existe/log.jsonl")}).returncode, 0)
        # runtime sem permissão (PermissionError)
        d2 = Data("guardperm")
        (d2.root / ".squad").mkdir()
        os.chmod(d2.root / ".squad", 0)
        try:
            p = self.hook(d2, ti)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("subagente permitido", p.stderr)
        finally:
            os.chmod(d2.root / ".squad", 0o755)
        # log é um diretório (IsADirectoryError ao gravar o dispatch/foto)
        d3 = Data("guardlogdir")
        d3.write_cfg()
        d3.log.unlink()
        d3.log.mkdir()
        self.assertEqual(self.hook(d3, ti).returncode, 0)

    def _hold_lock(self, d: Data, seconds: float):
        lock = d.root / ".squad/locks/executores.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        code = ("import fcntl,os,sys,time;fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT);"
                "fcntl.flock(fd,fcntl.LOCK_EX);print('ok',flush=True);time.sleep(float(sys.argv[2]))")
        holder = subprocess.Popen([sys.executable, "-c", code, str(lock), str(seconds)], stdout=subprocess.PIPE, text=True)
        self.assertEqual(holder.stdout.readline().strip(), "ok")
        return holder

    def test_falha_aberta_trava_ocupada_mais_de_5s(self):
        # (a) sem executores.json (1ª chamada migra sob a trava) e (b) demanda sem foto (foto sob a trava)
        for name, prep in (("travamigra", lambda d: None), ("travafoto", lambda d: d.write_cfg())):
            d = Data(name)
            prep(d)
            holder = self._hold_lock(d, 12)
            try:
                t0 = time.monotonic()
                p = self.hook(d, {"subagent_type": "backend", "prompt": f"x --demand {D1}"})
                dt = time.monotonic() - t0
            finally:
                holder.kill()
                holder.wait()
                holder.stdout.close()
            self.assertEqual(p.returncode, 0, f"{name}: trava ocupada não é 'configuração ilegível': {p.stderr}")
            self.assertNotIn("ilegível", p.stderr)
            self.assertIn("trava de executores ocupada", p.stderr)
            self.assertGreaterEqual(dt, 4.5)
            self.assertLess(dt, 15)

    def test_nega_so_com_configuracao_ilegivel_de_verdade(self):
        d = Data("guardilegivel")
        d.cfg_path.parent.mkdir(parents=True)
        d.cfg_path.write_text("{quebrado")
        p = self.hook(d, {"subagent_type": "backend", "prompt": "x"})
        self.assertEqual(p.returncode, 2)
        self.assertIn("configuração ilegível", p.stderr)
        self.assertEqual(self.hook(d, {"subagent_type": "Explore", "prompt": "x"}).returncode, 0, "sem papel → permite")


# ====================================================================== CA-9 · CA-10 · CA-15 (runs com atalhos falsos)
class E_Execucao(unittest.TestCase):
    def last_meta(self, d: Data) -> dict:
        metas = sorted((d.root / ".squad/runs").glob("*-*.json"), key=lambda p: p.stat().st_mtime)
        return json.loads(metas[-1].read_text())

    def test_ca9_sem_login_politica_padrao(self):
        d = Data("ca9padrao", codex_login=False)
        d.write_cfg(agents={"qa": ("codex", None)})
        p = d.run([*RUN_AGENT, "qa", "x", "--demand", D1])
        self.assertEqual(p.returncode, 0, p.stderr)
        fb = d.events("executor-fallback")
        self.assertEqual(len(fb), 1)
        self.assertEqual((fb[0]["action"], fb[0]["reason"], fb[0]["role"], fb[0]["demand"]), ("padrao", "sem-login", "qa", D1))
        m = self.last_meta(d)
        self.assertEqual(fb[0]["run"], m["id"], "o fallback aponta a run que explica (B9 por run)")
        self.assertEqual((m["runner"], m["runnerConfigured"], m["configSource"]), ("claude", "codex", "agente"))
        self.assertEqual(m["fallback"]["reason"], "sem-login")
        self.assertEqual([c["bin"] for c in d.call_list()], ["claude"], "rodou no padrão; o codex nunca rodou")
        prog = [e for e in d.events("progress") if e.get("run") == m["id"]]
        self.assertTrue(prog and prog[0].get("runnerConfigured") == "codex", prog[:1])

    def test_ca9_sem_login_politica_parar(self):
        d = Data("ca9parar", codex_login=False)
        d.write_cfg(agents={"qa": ("codex", None)}, policy="parar")
        p = d.run([*RUN_AGENT, "qa", "x", "--demand", D1])
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertEqual(d.call_list(), [], "nenhum processo do executor")
        fb = d.events("executor-fallback")
        self.assertEqual([(e["action"], e["reason"]) for e in fb], [("parou", "sem-login")])
        # CLI resolve também sai 3
        c, r = d.resolve("qa", "--demand", D1)
        self.assertEqual((c, r["error"]), (3, "executor_indisponivel"))
        # padrão da squad também indisponível (papel já é o padrão) → para mesmo com `padrao`
        d2 = Data("ca9same", codex_login=False)
        d2.write_cfg(squad=("codex", None), agents={"orquestrador": ("claude", None)})
        self.assertEqual(d2.run([*RUN_AGENT, "qa", "x", "--demand", D1]).returncode, 3)

    def test_ca10_falha_de_autenticacao_na_saida_uma_nova_run(self):
        d = Data("ca10", FAKE_CODEX_MODE="authfail")
        d.write_cfg(agents={"qa": ("codex", None)})
        p = d.run([*RUN_AGENT, "qa", "x", "--demand", D1], timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-800:] + p.stderr)
        metas = [json.loads(f.read_text()) for f in (d.root / ".squad/runs").glob("*-qa-*.json")]
        self.assertEqual(len(metas), 2, "exatamente 1 nova run, nunca 2")
        first = next(m for m in metas if not m.get("fallbackOf"))
        second = next(m for m in metas if m.get("fallbackOf"))
        self.assertEqual((first["runner"], first.get("authFailure")), ("codex", True))
        self.assertEqual((second["runner"], second["fallbackOf"]), ("claude", first["id"]))
        self.assertEqual([c["bin"] for c in d.call_list()], ["codex", "claude"])
        # o executor padrão também falhando na saída: não entra em laço (fica em 1 retentativa)
        d2 = Data("ca10b", FAKE_CODEX_MODE="authfail", FAKE_CLAUDE_MODE="authfail")
        d2.write_cfg(agents={"qa": ("codex", None)})
        d2.run([*RUN_AGENT, "qa", "x", "--demand", D1], timeout=120)
        self.assertEqual(len(list((d2.root / ".squad/runs").glob("*-qa-*.json"))), 2)

    def test_ca15_campos_da_run_configurado_x_efetivo(self):
        d = Data("ca15")
        d.write_cfg(agents={"qa": ("codex", "gpt-5.6-sol"), "devops": ("claude", "haiku")})
        self.assertEqual(d.run([*RUN_AGENT, "qa", "x", "--demand", D1]).returncode, 0)
        m = self.last_meta(d)
        self.assertEqual({k: m.get(k) for k in ("runner", "runnerConfigured", "modelConfigured", "configSource",
                                                 "profile", "fallback", "model", "modelRequested")},
                         {"runner": "codex", "runnerConfigured": "codex", "modelConfigured": "gpt-5.6-sol",
                          "configSource": "agente", "profile": "escrita", "fallback": None, "model": "gpt-5.6-sol",
                          "modelRequested": "gpt-5.6-sol"})
        self.assertEqual(d.call_list()[-1]["argv"][-3:-1], ["-m", "gpt-5.6-sol"])
        self.assertEqual(d.run([*RUN_AGENT, "devops", "x", "--demand", D1], env={"FAKE_CLAUDE_MODEL": "claude-haiku-5"}).returncode, 0)
        m = self.last_meta(d)
        self.assertEqual((m["runner"], m["modelConfigured"], m["model"], m["modelRequested"]),
                         ("claude", "haiku", "claude-haiku-5", "haiku"))


# ====================================================================== B9 não retroativo · A8 · B8 (alerts.py)
class F_AlertasB9(unittest.TestCase):
    T0 = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)

    def at(self, minutes):
        return iso(self.T0 + timedelta(minutes=minutes))

    def alerts(self, rows, runs):
        import alerts as al
        return al.executor_alerts(rows, runs, al.Rules(rows, []), (self.T0 + timedelta(hours=1)).timestamp())

    def base(self):
        return [{"id": D1, "type": "task", "agent": "humano", "title": "Demanda: X", "ts": self.at(-60)}]

    def snap(self, runner, minutes):
        return {"id": "snap00000001", "type": "executor-snapshot", "agent": "orquestrador", "demand": D1,
                "ts": self.at(minutes), "executors": {r: {"runner": runner, "model": None, "source": "squad"} for r in ROLES}}

    def mkrun(self, rid, role, runner, minutes, **kw):
        return {"id": rid, "agent": role, "demand": D1, "runner": runner, "started": self.at(minutes), **kw}

    def b9(self, rows, runs):
        return sorted(a["runId"] for a in self.alerts(rows, runs) if a["kind"] == "executor-divergente")

    def test_foto_no_meio_da_demanda_nao_e_retroativa(self):
        import alerts as al
        rows = self.base() + [self.snap("codex", 30)]
        runs = [self.mkrun(f"old{i}", r, "claude", 5 + i) for i, r in enumerate(["arquiteto", "backend", "qa", "devops"])]
        runs.append(self.mkrun("new1", "backend", "claude", 40))
        self.assertEqual(self.b9(rows, runs), ["new1"], "só runs posteriores à foto são comparadas")
        de = {x["role"]: x for x in al.demand_executors(rows, runs, D1)}
        self.assertFalse(de["arquiteto"]["diff"], "runs antigas não viram 'Diferente'")
        self.assertTrue(de["backend"]["diff"])
        self.assertEqual(de["backend"]["reason"], "executor")

    def test_troca_so_nesta_demanda_nao_e_retroativa(self):
        import alerts as al
        rows = self.base() + [self.snap("claude", 0),
                              {"id": "cfg000000001", "type": "executor-config", "agent": "humano", "scope": "demand",
                               "demand": D1, "role": "qa", "ts": self.at(30), "before": {"runner": "claude", "model": None},
                               "after": {"runner": "codex", "model": None}}]
        runs = [self.mkrun("qa-antes", "qa", "claude", 10), self.mkrun("qa-depois", "qa", "claude", 40),
                self.mkrun("be", "backend", "claude", 45)]
        self.assertEqual(self.b9(rows, runs), ["qa-depois"])
        de = {x["role"]: x for x in al.demand_executors(rows, runs, D1)}
        self.assertEqual((de["qa"]["configured"]["source"], de["qa"]["diff"]), ("demanda", True))
        self.assertFalse(de["backend"]["diff"])
        # desfazer a troca (after null) volta à foto, só para runs posteriores ao desfazer
        rows.append({"id": "cfg000000002", "type": "executor-config", "agent": "humano", "scope": "demand", "demand": D1,
                     "role": "qa", "ts": self.at(50), "before": {"runner": "codex"}, "after": None})
        runs.append(self.mkrun("qa-codex-antes-desfazer", "qa", "codex", 48))
        self.assertEqual(self.b9(rows, runs), [], "após desfazer, nada anterior é comparado")

    def test_fallback_silencia_so_a_run(self):
        rows = self.base() + [self.snap("codex", 0),
                              {"id": "fb0000000001", "type": "executor-fallback", "agent": "orquestrador", "demand": D1,
                               "role": "qa", "run": "r1", "action": "padrao", "reason": "sem-login", "ts": self.at(9),
                               "configured": {"runner": "codex"}, "effective": {"runner": "claude"}}]
        runs = [self.mkrun("r1", "qa", "claude", 10), self.mkrun("r2", "qa", "claude", 20)]
        self.assertEqual(self.b9(rows, runs), ["r2"], "o fallback explica só a run dele")
        # evento antigo sem `run`: explica só a PRIMEIRA run do papel depois dele
        rows[-1] = {**rows[-1], "run": None}
        del rows[-1]["run"]
        self.assertEqual(self.b9(rows, runs), ["r2"])
        # run com fallback gravado na meta não gera B9
        runs[1]["fallback"] = {"reason": "sem-login", "from": {"runner": "codex"}}
        self.assertEqual(self.b9(rows, runs), [])
        kinds = sorted(a["kind"] for a in self.alerts(rows, runs))
        self.assertIn("executor-fallback", kinds, "A8 (aviso) do fallback padrao")

    def test_configuracao_padrao_sem_falso_alerta(self):
        rows = self.base() + [self.snap("claude", 0)]
        runs = [self.mkrun(f"r{i}", r, "claude", 5 + i) for i, r in enumerate(ROLES)]
        self.assertEqual(self.alerts(rows, runs), [])

    def test_b8_parou_e_fechamento(self):
        fb = {"id": "fb0000000009", "type": "executor-fallback", "agent": "orquestrador", "demand": D1, "role": "qa",
              "action": "parou", "reason": "sem-login", "ts": self.at(5), "configured": {"runner": "codex"}}
        rows = self.base() + [self.snap("claude", 0), fb]
        b8 = [a for a in self.alerts(rows, []) if a["kind"] == "executor-indisponivel"]
        self.assertEqual(len(b8), 1)
        self.assertEqual((b8[0]["severity"], b8[0]["agent"], b8[0]["demand"]), ("bloqueio", "qa", D1))
        self.assertEqual([x["id"] for x in b8[0]["actions"]], ["tentar-de-novo", "usar-padrao"])
        rows.append({"id": "cfg000000003", "type": "executor-config", "agent": "humano", "scope": "demand", "demand": D1,
                     "role": "qa", "ts": self.at(6), "after": {"runner": "claude", "model": None}})
        self.assertEqual([a for a in self.alerts(rows, []) if a["kind"] == "executor-indisponivel"], [],
                         "'usar o padrão nesta demanda' fecha o B8")


# ====================================================================== CA-12 · CA-20 (gate.py)
PARECER = {"gate": "G2", "from": "backend", "to": "qa", "recommendation": "APPROVE", "confidence": 0.9, "risk": "baixo",
           "rationale": "ok", "evidences": [{"name": "G2 (B,3) mvn package", "status": "pass", "check": "g2-mvn-package"}]}


class G_Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = Data("gate")
        cls.d.task(D1)
        cls.d.write_cfg()
        repo = cls.repo = cls.d.root / "repo"
        repo.mkdir()
        g = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True)
        g("init", "-q", "-b", "develop")
        g("config", "user.email", "qa@x")
        g("config", "user.name", "qa")
        (repo / "README.md").write_text("x\n")
        g("add", ".")
        g("commit", "-qm", "base")
        g("checkout", "-qb", "feature/D26-x")
        (repo / "services/saga-orchestrator").mkdir(parents=True)
        (repo / "services/saga-orchestrator/A.java").write_text("class A {}\n")
        g("add", ".")
        g("commit", "-qm", "feature")
        cls.head = g("rev-parse", "HEAD").stdout.strip()
        # mvn falso: registra a chamada e sai com FAKE_MVN_EXIT; docker/gh que não deveriam rodar gravam também
        b = cls.d.root / "bin"
        b.mkdir()
        for tool in ("mvn", "docker", "sh", "bash", "curl"):
            (b / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{cls.d.root}/gate-calls.txt"\n'
                                  f'echo "saida do {tool}"\nexit ${{FAKE_MVN_EXIT:-0}}\n')
            (b / tool).chmod(0o755)
        cls.env = {"PATH": f"{b}:{cls.d.env['PATH']}"}

    def gate_calls(self):
        f = self.d.root / "gate-calls.txt"
        return f.read_text().splitlines() if f.exists() else []

    def verify(self, **env):
        p = self.d.run([*GATE, "verify", "--gate", "G2", "--demand", D1, "--worktree", str(self.repo), "--json"],
                       env={**self.env, **env}, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def record(self, parecer, raw=None):
        out = self.d.root / f"saida-{time.monotonic_ns()}.txt"
        out.write_text(raw if raw is not None else f"texto do auditor\n```parecer\n{json.dumps(parecer)}\n```\n")
        return self.d.run([*GATE, "record", "--demand", D1, "--from-output", str(out), "--worktree", str(self.repo),
                           "--run", "r-aud"], env=self.env)

    def test_ca20_verify_lista_fixa_e_record_coerente(self):
        v = self.verify(FAKE_MVN_EXIT="1")
        st = {c["id"]: c["status"] for c in v["checks"]}
        self.assertEqual(st, {"g2-mvn-package": "fail", "g2-saga-unit": "fail", "g2-compose-config": "n/a",
                              "g2-compose-healthcheck": "n/a"})
        self.assertEqual(v["commit"], self.head)
        calls = self.gate_calls()
        self.assertEqual(calls, ["mvn -q package -DskipTests", "mvn -q -pl services/saga-orchestrator -am test"],
                         "só os comandos de gate_checks.json (lista, sem shell)")
        ev = [e for e in self.d.events("evidence") if e.get("demand") == D1][-1]
        self.assertIn("verify:g2-mvn-package=fail", json.dumps(ev, ensure_ascii=False).replace('", "status": "', "="))
        self.assertTrue((self.d.root / ".squad/runs" / f"verify-G2-{D1}-1.json").exists())
        # parecer `pass` num critério cuja verificação deu fail → recusado, nada gravado
        n_gates = len(self.d.events("gate"))
        p = self.record(PARECER)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("incoerente", p.stderr)
        self.assertEqual(len(self.d.events("gate")), n_gates)
        self.assertTrue(any(e.get("title") == "parecer incoerente com a verificação" for e in self.d.events("progress")))
        # casando pelo nome do critério (sem `check`)
        par = json.loads(json.dumps(PARECER))
        del par["evidences"][0]["check"]
        self.assertEqual(self.record(par).returncode, 2)
        # `pass` com nome livre + APPROVE com verificação em fail → recusado (regra b)
        par["evidences"] = [{"name": "tudo certo", "status": "pass"}]
        self.assertEqual(self.record(par).returncode, 2)
        # RETURN coerente (fail registrado) → grava gate e evento
        par = {**PARECER, "recommendation": "RETURN", "evidences": [
            {"name": "G2 (B,3) mvn package", "status": "fail", "check": "g2-mvn-package"},
            {"name": "G2 (B,3) testes unitários da Saga", "status": "fail", "check": "g2-saga-unit"}]}
        p = self.record(par)
        self.assertEqual(p.returncode, 0, p.stderr)
        gates = self.d.events("gate")
        self.assertEqual(len(gates), n_gates + 1)
        self.assertEqual((gates[-1]["agent"], gates[-1]["gate"], gates[-1]["recommendation"], gates[-1].get("run")),
                         ("auditor", "G2", "RETURN", "r-aud"))
        files = list((self.repo / "docs/squad/gates").glob("G2-*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text())["recordedBy"], "gate.py")
        # verify de novo com mvn passando → APPROVE coerente grava (ciclo 2)
        v = self.verify(FAKE_MVN_EXIT="0")
        self.assertEqual(v["cycle"], 2)
        self.assertEqual(self.record(PARECER).returncode, 0)

    def test_ca12_bloco_parecer_invalido_nao_grava(self):
        n = len(self.d.events("gate"))
        for raw in ("sem bloco nenhum", "```parecer\n{json quebrado\n```\n",
                    "```parecer\n" + json.dumps({**PARECER, "confidence": 1.5}) + "\n```\n",
                    "```parecer\n" + json.dumps({**PARECER, "recommendation": "TALVEZ"}) + "\n```\n",
                    "```parecer\n" + json.dumps({**PARECER, "evidences": []}) + "\n```\n"):
            p = self.record(None, raw=raw)
            self.assertEqual(p.returncode, 2, raw)
            self.assertIn("parecer inválido", p.stderr)
        self.assertEqual(len(self.d.events("gate")), n)

    def test_ca20_bug_worktree_temporario_e_testcmd_fora_do_regex(self):
        d = Data("gatebug")
        d.append(id=D2, type="task", agent="humano", title="Demanda: bug", nature="bug", ts="2026-09-25T10:00:00+00:00")
        # evento do QA com alvo fora do regex → `erro` "alvo do teste não reconhecido" (vira validate), nada roda
        d.append(type="evidence", agent="qa", demand=D2, sha=self.head, title="repro: bash -c 'rm -rf /'",
                 evidences=[{"name": "reproducao", "status": "FAIL"}])
        p = d.run([*GATE, "verify", "--gate", "G3", "--demand", D2, "--worktree", str(self.repo), "--json"],
                  env=self.env, timeout=120)
        v = json.loads(p.stdout)
        st = {c["id"]: (c["status"], c["tail"]) for c in v["checks"]}
        self.assertEqual(st["bug-repro-falha"][0], "erro")
        self.assertIn("não reconhecido", st["bug-repro-falha"][1])
        self.assertFalse(any("rm -rf" in c for c in self.gate_calls()))
        # alvo válido → worktree temporário criado no commit do teste e removido ao fim
        d.append(type="evidence", agent="qa", demand=D2, sha=self.head,
                 title="repro: python3 -m pytest -q tests/test_x.py::test_y", evidences=[{"name": "reproducao", "status": "FAIL"}])
        wt_before = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True).stdout
        p = d.run([*GATE, "verify", "--gate", "G3", "--demand", D2, "--worktree", str(self.repo), "--json"],
                  env={**self.env, "PATH": f"{self.d.root / 'bin'}:/usr/bin:/bin"}, timeout=120)
        v = json.loads(p.stdout)
        st = {c["id"]: c for c in v["checks"]}
        self.assertIn(st["bug-repro-falha"]["status"], ("pass", "fail", "erro"))
        self.assertNotIn("não reconhecido", st["bug-repro-falha"]["tail"])
        wt_after = subprocess.run(["git", "worktree", "list"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertEqual(wt_before, wt_after, "worktree temporário removido")
        self.assertFalse((d.root / ".squad/verify" / f"G3-{D2}").exists())

    def test_ca20_so_comandos_da_lista(self):
        import gate
        ids = [c["id"] for c in gate.load_checks()]
        self.assertEqual(ids, ["g2-mvn-package", "g2-saga-unit", "g2-compose-config", "g2-compose-healthcheck",
                               "bug-repro-falha", "bug-repro-passa"])
        for c in gate.load_checks():
            self.assertTrue(isinstance(c["cmd"], list) or c["cmd"] == "{testCmd}")
        self.assertIsNone(gate.test_cmd_from({"title": "mvn -q -pl services/x test -Dtest=A; rm -rf /"}) and None)
        self.assertEqual(gate.test_cmd_from({"title": "python3 -m pytest -q tests/../../etc/x.py"}), None)
        self.assertEqual(gate.test_cmd_from({"title": "mvn -q -pl services/order-service test -Dtest=A#b"}),
                         ["mvn", "-q", "-pl", "services/order-service", "test", "-Dtest=A#b"])
        src = (TOOLS / "gate.py").read_text()
        self.assertNotIn("shell=True", src)


# ====================================================================== CA-13 · CA-14 · CA-15 · CA-16 · CA-17 (servidor)
class H_Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = Data("servidor", codex_login=False)
        cls.d.task(D1)
        cls.d.task(D2, "Demanda entregue")
        cls.d.append(type="delivered", agent="humano", demand=D2, title="entregue")
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(TOOLS / "server.py"), "--port", str(cls.port)],
                                    env={**cls.d.env, "SQUAD_CHAT_RUNNER": "fake",
                                         "SQUAD_CHAT_FAKE": str(pathlib.Path(__file__).parent / "conversa_fake_runner.py")},
                                    cwd=str(REPO), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        for _ in range(200):
            try:
                cls.req("GET", "/api/executores")
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("servidor não subiu")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)

    @classmethod
    def req(cls, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=30)
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                  headers={"Host": f"localhost:{cls.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        return r.status, (json.loads(data) if data else None)

    def test_1_ca13_post_executores(self):
        s, v = self.req("GET", "/api/executores")
        self.assertEqual(s, 200)
        for k in ("config", "version", "resolved", "status", "allowed", "policy", "ignoredEnv", "lastEffective",
                  "history", "plantao"):
            self.assertIn(k, v)
        self.assertEqual(v["status"]["codex"]["detail"], "sem-login")
        self.assertEqual(len(v["resolved"]), 8)
        ver = v["version"]
        agents = {r: None for r in ROLES}
        s, r = self.req("POST", "/api/executores", {"baseVersion": ver, "squad": {"runner": "claude", "model": None},
                                                    "agents": {**agents, "qa": {"runner": "codex", "model": "gpt-5.6-sol"}},
                                                    "policy": {"onUnavailable": "padrao"}})
        self.assertEqual((s, r["code"]), (409, "executor_indisponivel"))
        self.assertEqual(r["warnings"], [{"runner": "codex", "detail": "sem-login"}])
        s, r = self.req("POST", "/api/executores", {"baseVersion": ver, "squad": {"runner": "claude", "model": None},
                                                    "agents": {**agents, "qa": {"runner": "codex", "model": "gpt-5.6-sol"}},
                                                    "policy": {"onUnavailable": "padrao"}, "acknowledge": True})
        self.assertEqual(s, 200, r)
        self.assertEqual(r["version"], ver + 1)
        ev = [e for e in self.d.events("executor-config") if e.get("scope") == "agent"][-1]
        self.assertEqual((ev["role"], ev["before"], ev["after"], ev["by"], ev["via"], ev["acknowledged"]),
                         ("qa", None, {"runner": "codex", "model": "gpt-5.6-sol"}, "humano", "painel", True))
        self.assertTrue(ev["user"] and ev["machine"] and ev["ts"])
        self.assertEqual(ev["configVersion"], ver + 1)
        s, r = self.req("POST", "/api/executores", {"baseVersion": ver, "agents": agents})
        self.assertEqual((s, r["code"]), (409, "versao_desatualizada"))
        for body, code in (({"agents": {**agents, "orquestrador": {"runner": "codex"}}}, "orquestrador_codex_pendente_q2"),
                           ({"agents": {**agents, "backend": {"runner": "claude", "model": "gpt-5"}}}, "modelo_incompativel"),
                           ({"agents": {**agents, "backend": {"runner": "gemini"}}}, "formato_invalido"),
                           ({"policy": {"onUnavailable": "talvez"}}, "formato_invalido")):
            s, r = self.req("POST", "/api/executores", {"baseVersion": ver + 1, **body})
            self.assertEqual((s, r["code"]), (400, code), body)
        s, v = self.req("GET", "/api/executores")
        self.assertEqual(v["version"], ver + 1, "recusas não mudam a versão")
        self.assertEqual(v["history"][0]["role"], "qa")

    def test_2_ca14_aplicar_a_todos(self):
        _, v = self.req("GET", "/api/executores")
        n = len([e for e in self.d.events("executor-config") if e.get("scope") == "apply-all"])
        s, r = self.req("POST", "/api/executores/aplicar-a-todos", {"baseVersion": v["version"], "runner": "codex",
                                                                    "model": None, "acknowledge": True})
        self.assertEqual(s, 200, r)
        self.assertIn("orquestrador_codex_pendente_q2", r["warnings"])
        _, v2 = self.req("GET", "/api/executores")
        self.assertEqual(v2["config"]["squad"], {"runner": "codex", "model": None})
        self.assertEqual({k: x for k, x in v2["config"]["agents"].items() if x}, {"orquestrador": {"runner": "claude", "model": None}})
        ev = [e for e in self.d.events("executor-config") if e.get("scope") == "apply-all"]
        self.assertEqual(len(ev), n + 1)
        self.assertEqual(ev[-1]["before"]["agents"]["qa"], {"runner": "codex", "model": "gpt-5.6-sol"})
        s, r = self.req("POST", "/api/executores/aplicar-a-todos", {"baseVersion": v2["version"], "runner": "claude",
                                                                    "model": None})
        self.assertEqual(s, 200, r)
        _, v3 = self.req("GET", "/api/executores")
        self.assertEqual(set(v3["config"]["agents"].values()), {None}, "8 agents = null (inclusive o Orquestrador)")

    def test_3_ca15_ca16_state_demands_e_b9(self):
        # foto de D1 com o padrão atual (claude); troca só nesta demanda: arquiteto → codex
        p = self.d.exe("snapshot", "--demand", D1)
        self.assertEqual(p.returncode, 0, p.stderr)
        s, r = self.req("POST", "/api/demand/executores", {"demand": D1, "role": "arquiteto", "runner": "codex",
                                                           "model": "gpt-5.6-sol"})
        self.assertEqual((s, r["code"]), (409, "executor_indisponivel"))
        s, r = self.req("POST", "/api/demand/executores", {"demand": D1, "role": "arquiteto", "runner": "codex",
                                                           "model": "gpt-5.6-sol", "acknowledge": True})
        self.assertEqual(s, 200, r)
        self.assertEqual(self.req("POST", "/api/demand/executores", {"demand": D2, "role": "qa", "runner": "claude"})[0], 409)
        self.assertEqual(self.req("POST", "/api/demand/executores", {"demand": D3, "role": "qa", "runner": "claude"})[0], 404)
        self.assertEqual(self.req("POST", "/api/demand/executores", {"demand": D1, "role": "orquestrador",
                                                                     "runner": "codex", "acknowledge": True})[0], 400)
        time.sleep(1.1)
        # run NATIVA do Arquiteto (transcrição de subagente) no claude, com o papel configurado em codex → B9 (CA-16)
        ts = iso(datetime.now(timezone.utc))
        sub = self.d.root / "tr/sessao1/subagents"
        sub.mkdir(parents=True)
        (sub / "agent-nativo01.jsonl").write_text("\n".join(json.dumps(x) for x in (
            {"type": "user", "timestamp": ts, "message": {"role": "user", "content":
                f"Você atua como o agente **Arquiteto**. Tarefa --demand {D1}"}},
            {"type": "assistant", "timestamp": ts, "message": {"model": "claude-opus-5-5",
                                                               "content": [{"type": "text", "text": "ok"}]}})) + "\n")
        (sub / "agent-nativo01.meta.json").write_text(json.dumps({"description": "Arquiteto: tarefa", "demand": D1}))
        # run via run_agent do QA (padrão claude, modelo sonnet)
        p = self.d.run([*RUN_AGENT, "qa", "x", "--demand", D1], env={"FAKE_CLAUDE_MODEL": "claude-sonnet-5"})
        self.assertEqual(p.returncode, 0, p.stderr)
        _, st = self.req("GET", "/api/state")
        dem = next(x for x in st["demands"] if x["id"] == D1)
        by = {x["role"]: x for x in dem["executors"]}
        self.assertEqual((by["arquiteto"]["configured"]["source"], by["arquiteto"]["diff"], by["arquiteto"]["reason"]),
                         ("demanda", True, "executor"))
        self.assertEqual((by["qa"]["diff"], by["qa"]["effective"][-1]["runner"]), (False, "claude"))
        b9 = [a for a in st["alerts"] if a.get("kind") == "executor-divergente"]
        self.assertEqual([(a["agent"], a["demand"], a["runId"]) for a in b9], [("arquiteto", D1, "nativo01")])
        _, live = self.req("GET", "/api/live")
        self.assertNotIn("demands", live, "/api/live não muda")
        self.assertTrue(any(a.get("kind") == "executor-divergente" for a in live["alerts"]))

    def test_4_b8_real_e_usar_padrao(self):
        _, v = self.req("GET", "/api/executores")
        s, r = self.req("POST", "/api/executores", {"baseVersion": v["version"], "policy": {"onUnavailable": "parar"},
                                                    "agents": {**{x: None for x in ROLES}, "devops": {"runner": "codex"}},
                                                    "acknowledge": True})
        self.assertEqual(s, 200, r)
        p = self.d.run([*RUN_AGENT, "devops", "x", "--demand", D3])
        self.assertEqual(p.returncode, 3)
        self.d.task(D3, "B8")
        _, live = self.req("GET", "/api/live")
        b8 = [a for a in live["alerts"] if a.get("kind") == "executor-indisponivel" and a.get("demand") == D3]
        self.assertEqual(len(b8), 1)
        self.assertEqual(b8[0]["severity"], "bloqueio")
        s, r = self.req("POST", "/api/demand/executores", {"demand": D3, "role": "devops", "runner": "claude"})
        self.assertEqual(s, 200, r)
        _, live = self.req("GET", "/api/live")
        self.assertFalse([a for a in live["alerts"] if a.get("kind") == "executor-indisponivel" and a.get("demand") == D3])
        self.assertEqual(self.d.run([*RUN_AGENT, "devops", "x", "--demand", D3]).returncode, 0, "retoma após a troca")

    def test_5_ca17_conversa_usa_executor_do_orquestrador(self):
        import conversa as cv
        old = {k: os.environ.get(k) for k in ("SQUAD_ROOT_DATA", "SQUAD_LOG", "SQUAD_CHAT_RUNNER", "SQUAD_CHAT_FAKE", "PATH")}
        try:
            os.environ.update(SQUAD_ROOT_DATA=str(self.d.root), SQUAD_LOG=str(self.d.log), PATH=self.d.env["PATH"])
            os.environ.pop("SQUAD_CHAT_RUNNER", None)
            os.environ.pop("SQUAD_CHAT_FAKE", None)
            _, v = self.req("GET", "/api/executores")
            self.req("POST", "/api/executores", {"baseVersion": v["version"], "policy": {"onUnavailable": "padrao"},
                                                 "agents": {**{x: None for x in ROLES},
                                                            "orquestrador": {"runner": "claude", "model": "haiku"}}})
            self.assertEqual((cv.default_runner(), cv.requested_model()), ("claude", "haiku"))
            os.environ["SQUAD_CHAT_RUNNER"] = "codex"   # variável antiga: ignorada como configuração
            self.assertEqual(cv.default_runner(), "claude")
        finally:
            for k, val in old.items():
                if val is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = val

    def test_6_ca17_troca_de_executor_abre_sessao_nova(self):
        src = (TOOLS / "conversa.py").read_text()
        # a sessão guarda o runner; turno com runner diferente do da sessão abre sessão nova (meta-update executorChanged)
        self.assertIn('if cur_runner and cur_runner != runner:', src)
        self.assertIn('"reason": "executorChanged"', src)
        import conversa as cv
        c1 = cv.build_cmd("codex", {"dataRoot": str(self.d.root), "sessionId": "th-1"}, {"prompt": "P", "resume": False})
        self.assertNotIn("resume", c1)
        c2 = cv.build_cmd("claude", {"dataRoot": str(self.d.root), "sessionId": "u-2"}, {"prompt": "P", "resume": False})
        self.assertIn("--session-id", c2)
        self.assertNotIn("--resume", c2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
