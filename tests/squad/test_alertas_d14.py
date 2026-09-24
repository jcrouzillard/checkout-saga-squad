#!/usr/bin/env python3
"""D14 (`1e3d3c894630`) — bloqueios/avisos e estado dos agentes calculados no servidor (ADR-017).

Cobre o contrato `docs/contracts/ui-governanca-squad-control.md` §13.1 com dados SINTÉTICOS num diretório
temporário (SQUAD_ROOT_DATA, SQUAD_LOG, SQUAD_TRANSCRIPTS): nada toca o log real.
  CA-S1 abrir/fechar B1–B4, A1–A3 · CA-S2 3º RETURN e reinício de `returns` · CA-S3 B2→A1→fecha
  CA-S4 A2 com 601 s × 599 s e ferramenta longa · CA-S5 esperas do Orquestrador · CA-S6 compatibilidade
  (/api/state e log.py sem --step) · CA-S7 segredos mascarados · CA-S8 sem bloqueios herdados.

Uso: python3 tests/squad/test_alertas_d14.py   (ou pytest tests/squad/test_alertas_d14.py)
"""
import importlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[2]
TMP = pathlib.Path(tempfile.mkdtemp(prefix="squad-d14-"))
LOG = TMP / "docs/squad/memory/decisions.jsonl"
GATES = TMP / "docs/squad/gates"
RUNS = TMP / ".squad/runs"
TRANS = TMP / "transcripts"
os.environ.update(SQUAD_ROOT_DATA=str(TMP), SQUAD_LOG=str(LOG), SQUAD_TRANSCRIPTS=str(TRANS))
os.environ.pop("SQUAD_STALLED_S", None)
sys.path.insert(0, str(REPO / "tools/squad"))
server = importlib.import_module("server")
al = importlib.import_module("alerts")

D = "aaaaaaaaaaa1"   # D1
D2 = "aaaaaaaaaaa2"  # D2
T0 = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
_n = [0]


def ts(minutes=0.0):
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def ev(type_, agent="auditor", minutes=0.0, **kw):
    _n[0] += 1
    return {"id": f"e{_n[0]:011d}", "ts": ts(minutes), "agent": agent, "type": type_, "title": kw.pop("title", type_), **kw}


def base_rows():
    return [ev("task", "humano", 0, id="aaaaaaaaaaa1", title="Demanda: um"),
            ev("task", "humano", 0.1, id="aaaaaaaaaaa2", title="Demanda: dois")]


def gate(g, rec, conf, minutes, demand=D, risk="baixo", to=None, **kw):
    return ev("gate", "auditor", minutes, demand=demand, gate=g, recommendation=rec, confidence=conf, risk=risk,
              to=to, **kw)


def human(g, rec, minutes, demand=D):
    return ev("human", "humano", minutes, demand=demand, gate=g, recommendation=rec)


def reset_data():
    for p in (TMP / "docs", RUNS, TRANS):
        shutil.rmtree(p, ignore_errors=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    GATES.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    TRANS.mkdir(parents=True, exist_ok=True)
    server._log_cache.update(sig=None, rows=[])
    server._gates_cache.update(sig=None, gates=[])
    server._rules_cache.update(sig=None, rules=None)
    server._STORE = None


def write_log(rows):
    LOG.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    server._log_cache.update(sig=None)


def state():
    return server.compute(full=True)


def open_by_kind(data, kind):
    return [a for a in data["alerts"] if kind in a["kinds"]]


def jl(path, rows, age_s):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    t = time.time() - age_s
    os.utime(path, (t, t))


def iso_ago(s):
    return datetime.fromtimestamp(time.time() - s, timezone.utc).isoformat()


def asst(content, s_ago, model="claude-opus-5-5"):
    return {"type": "assistant", "timestamp": iso_ago(s_ago), "message": {"model": model, "content": content}}


def user(content, s_ago):
    return {"type": "user", "timestamp": iso_ago(s_ago), "message": {"content": content}}


def subagent(session, agent_id, description, rows, age_s):
    d = TRANS / session / "subagents"
    jl(d / f"agent-{agent_id}.jsonl", rows, age_s)
    (d / f"agent-{agent_id}.meta.json").write_text(json.dumps({"description": description, "toolUseId": f"tu-{agent_id}"}))


class Regras(unittest.TestCase):
    def setUp(self):
        reset_data()

    # ---------------- B1
    def test_b1_abre_e_fecha_com_novo_gate(self):
        rows = base_rows() + [gate("G2", "RETURN", 0.8, 5, to="backend")]
        write_log(rows)
        a = open_by_kind(state(), "gate-return")
        self.assertEqual(len(a), 1)
        a = a[0]
        self.assertEqual((a["severity"], a["kind"], a["owner"], a["code"]), ("bloqueio", "gate-return", "backend", "D1"))
        self.assertEqual(a["action"]["href"], "#/demandas/D1/gates")
        self.assertEqual(a["source"]["event"], rows[-1]["id"])
        self.assertEqual(a["openedAt"], rows[-1]["ts"])
        rows.append(gate("G2", "APPROVE", 0.9, 9, to="qa"))
        write_log(rows)
        data = state()
        self.assertFalse(open_by_kind(data, "gate-return"))
        h = [x for x in data["alertsHistory"] if x["id"] == a["id"]][0]
        self.assertEqual((h["closedAt"], h["closedBy"], h["closedByEvent"]), (rows[-1]["ts"], "auditor", rows[-1]["id"]))

    def test_b1_fecha_com_override_humano(self):
        rows = base_rows() + [gate("G2", "RETURN", 0.8, 5, to="backend"), human("G2", "OVERRIDE", 6)]
        write_log(rows)
        self.assertFalse(state()["alerts"])

    def test_b1_fecha_com_demanda_cancelada(self):
        rows = base_rows() + [gate("G2", "RETURN", 0.8, 5, to="backend"),
                              ev("control", "humano", 7, demand=D, action="cancel")]
        write_log(rows)
        data = state()
        self.assertFalse(data["alerts"])
        self.assertEqual(data["alertsHistory"][0]["closedBy"], "humano")

    # ---------------- B2 / A1 (CA-S3)
    def test_b2_confianca_baixa_vira_a1_apos_decisao_e_fecha_com_80(self):
        rows = base_rows() + [gate("G2", "APPROVE", 0.62, 5, to="qa")]
        write_log(rows)
        data = state()
        self.assertEqual([a["kind"] for a in data["alerts"]], ["human-required"])
        b2 = data["alerts"][0]
        self.assertEqual((b2["severity"], b2["owner"], b2["action"]["label"]), ("bloqueio", "humano", "Decidir G2"))
        self.assertIn("62%", b2["rule"])
        self.assertFalse(open_by_kind(data, "low-confidence"))
        rows.append(human("G2", "APPROVE", 6))
        write_log(rows)
        data = state()
        self.assertEqual([a["kind"] for a in data["alerts"]], ["low-confidence"])
        a1 = data["alerts"][0]
        self.assertEqual((a1["severity"], a1["owner"]), ("aviso", "squad"))
        rows.append(gate("G2", "APPROVE", 0.8, 9, to="qa"))
        write_log(rows)
        data = state()
        self.assertFalse(data["alerts"])
        self.assertIn(a1["id"], [h["id"] for h in data["alertsHistory"]])

    def test_b2_risco_alto_e_human_required_do_arquivo(self):
        rows = base_rows() + [gate("G1", "APPROVE", 0.9, 5, risk="alto")]
        write_log(rows)
        self.assertEqual(open_by_kind(state(), "human-required")[0]["owner"], "humano")
        rows = base_rows() + [gate("G3", "APPROVE", 0.9, 5)]
        write_log(rows)
        (GATES / "G3-D1.json").write_text(json.dumps({"gate": "G3", "demand": D, "recommendation": "APPROVE",
                                                      "cycle": 1, "human_required": True, "from": "qa"}))
        data = state()
        self.assertEqual(len(open_by_kind(data, "human-required")), 1)
        self.assertEqual(data["alerts"][0]["source"]["file"].split("/")[-1], "G3-D1.json")

    # ---------------- B3 (CA-S2)
    def test_b3_terceiro_return_e_reinicio(self):
        rows = base_rows() + [gate("G2", "RETURN", 0.8, 1, to="frontend"), gate("G2", "RETURN", 0.8, 2, to="frontend")]
        write_log(rows)
        data = state()
        self.assertFalse(open_by_kind(data, "cycle-limit"), "2 RETURN ainda é autocorreção")
        self.assertEqual(open_by_kind(data, "gate-return")[0]["returns"], 2)
        rows.append(gate("G2", "RETURN", 0.8, 3, to="frontend"))
        write_log(rows)
        data = state()
        b3 = open_by_kind(data, "cycle-limit")
        self.assertEqual(len(b3), 1)
        self.assertEqual((b3[0]["owner"], b3[0]["returns"], b3[0]["cycle"], b3[0]["kind"]), ("humano", 3, 3, "cycle-limit"))
        self.assertEqual(b3[0]["action"]["label"], "Decidir G2 — 3º ciclo")
        gate_ev = [e for e in server.enrich_log(server.read_log(), []) if e["type"] == "gate"]
        rows.append(human("G2", "APPROVE", 4))
        write_log(rows)
        data = state()
        self.assertFalse(open_by_kind(data, "cycle-limit"))
        b1 = open_by_kind(data, "gate-return")[0]
        self.assertEqual((b1["returns"], b1["owner"]), (0, "frontend"))
        self.assertTrue(gate_ev)

    # ---------------- B4
    def test_b4_triagem_abre_e_fecha(self):
        val = ev("validation", "arquiteto", 1, demand=D, status="perguntas",
                 questions=[{"id": "q1", "text": "?"}, {"id": "q2", "text": "?"}])
        rows = base_rows() + [val]
        write_log(rows)
        b4 = open_by_kind(state(), "triage-open")[0]
        self.assertEqual((b4["owner"], b4["title"], b4["action"]["href"]), ("humano", "2 perguntas da triagem",
                                                                          "#/demandas/D1/validacao"))
        write_log(rows + [ev("clarification", "humano", 2, demand=D, validation=val["id"])])
        self.assertFalse(state()["alerts"])
        write_log(rows + [ev("start", "humano", 2, demand=D, override=True)])
        self.assertFalse(state()["alerts"])
        write_log(rows + [ev("control", "humano", 2, demand=D, action="cancel")])
        self.assertFalse(state()["alerts"])

    # ---------------- A3
    def test_a3_pr_aguardando(self):
        rv = ev("review", "orquestrador", 3, demand=D, pr=104, url="https://example.invalid/pr/104")
        rows = base_rows() + [gate("G3", "APPROVE", 0.9, 2), rv]
        write_log(rows)
        a3 = open_by_kind(state(), "pr-waiting")[0]
        self.assertEqual((a3["severity"], a3["owner"], a3["action"]["external"]), ("aviso", "humano", rv["url"]))
        write_log(rows + [ev("delivered", "orquestrador", 5, demand=D, pr=104)])
        self.assertFalse(state()["alerts"])
        write_log(rows + [ev("review-rejected", "orquestrador", 5, demand=D, pr=104)])
        self.assertFalse(state()["alerts"])

    # ---------------- CA-S8 (sem bloqueio herdado)
    def test_historico_decidido_nao_abre_nada(self):
        rows = base_rows() + [
            gate("G3", "RETURN", 0.65, 1, demand=D2, risk="moderado", to="orquestrador"),
            human("G3", "APPROVE", 2, demand=D2),
            gate("G3", "APPROVE", 1.0, 3, demand=D2),
            gate("G1", "APPROVE", 0.96, 0.5, demand=None),   # squad base
            ev("review", "orquestrador", 4, demand=D2, pr=10), ev("delivered", "orquestrador", 5, demand=D2, pr=10)]
        write_log(rows)
        data = state()
        self.assertEqual(data["alerts"], [])
        kinds = {h["kind"] for h in data["alertsHistory"]}
        self.assertTrue({"human-required", "gate-return", "pr-waiting"} <= kinds)
        for h in data["alertsHistory"]:
            self.assertTrue(h["openedAt"] and h["closedAt"] and h["closedBy"])


class Agentes(unittest.TestCase):
    def setUp(self):
        reset_data()
        write_log(base_rows())

    def _backend(self, age_s, pending_tool_s=None):
        tool_ts = pending_tool_s if pending_tool_s is not None else age_s
        rows = [user("Backend: D1 --demand aaaaaaaaaaa1", age_s + 100),
                asst([{"type": "tool_use", "id": "t1", "name": "Bash",
                       "input": {"command": "mvn -q test", "description": "testes do serviço"}}], tool_ts)]
        subagent("s1", "b1", "Backend: D1 implementação", rows, age_s)
        if not (TRANS / "s1.jsonl").exists():
            (TRANS / "s1.jsonl").write_text("")

    def agent(self, data, role):
        return next(a for a in data["agents"] if a["agent"] == role)

    def test_a2_601_vs_599(self):
        self._backend(601)
        data = state()
        a2 = open_by_kind(data, "agent-stalled")
        self.assertEqual(len(a2), 1)
        self.assertEqual((a2[0]["owner"], a2[0]["agent"], a2[0]["id"]), ("humano", "backend", "agent-stalled:b1"))
        self.assertEqual(self.agent(data, "backend")["state"], "sem-progresso")
        reset_data(); write_log(base_rows())
        self._backend(599)
        data = state()
        self.assertFalse(open_by_kind(data, "agent-stalled"))
        self.assertEqual(self.agent(data, "backend")["state"], "trabalhando")

    def test_ferramenta_longa_sem_a2(self):
        self._backend(10, pending_tool_s=200)
        data = state()
        self.assertFalse(open_by_kind(data, "agent-stalled"))
        cur = self.agent(data, "backend")["current"]
        self.assertTrue(cur["long"])
        self.assertEqual(cur["label"], "Executando: testes do serviço")
        self.assertEqual(self.agent(data, "backend")["task"]["code"], "D1")

    def test_a2_run_externa_interrompida(self):
        (RUNS / "r1.json").write_text(json.dumps({"id": "r1", "agent": "qa", "runner": "codex", "status": "trabalhando",
                                                  "pid": 999999, "started": iso_ago(120), "demand": D}))
        data = state()
        a2 = open_by_kind(data, "agent-stalled")[0]
        self.assertEqual((a2["owner"], a2["agent"]), ("orquestrador", "qa"))
        self.assertEqual(self.agent(data, "qa")["state"], "interrompido")

    def test_orquestrador_espera_subagente_e_humano(self):
        main = [user("plantão", 300),
                asst([{"type": "tool_use", "id": "tu-b1", "name": "Agent",
                       "input": {"description": "Backend · D1: implementação", "prompt": "..."}}], 200),
                user([{"type": "tool_result", "tool_use_id": "tu-b1",
                       "content": [{"type": "text", "text": "Async agent launched successfully.\nagentId: b1 (internal)"}]}], 199),
                asst([{"type": "tool_use", "id": "q1", "name": "AskUserQuestion", "input": {"questions": []}}], 5)]
        jl(TRANS / "s1.jsonl", main, 5)
        self._backend(20)
        data = state()
        orq = self.agent(data, "orquestrador")
        self.assertEqual(orq["state"], "trabalhando")
        self.assertIn("backend", orq["waiting"]["on"])
        self.assertIn("humano", orq["waiting"]["on"])
        self.assertEqual(orq["waiting"]["reason"], "Pergunta aberta para você no terminal")
        self.assertEqual([s["agent"] for s in orq["subagents"]], ["backend"])
        # notificação de término: deixa de esperar o Backend
        main.append(user("<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>tu-b1</tool-use-id>\n"
                         "<output-file>x</output-file>\n<status>completed</status>\n</task-notification>", 1))
        jl(TRANS / "s1.jsonl", main, 1)
        orq = self.agent(state(), "orquestrador")
        self.assertEqual(orq["subagents"], [])

    def test_segredos_mascarados(self):
        cmd = ("gh auth login --with-token ghp_ABCDEFGHIJKLMNOPQRSTUVWX123 && export OPENAI=sk-proj-ABCDEFGHIJKLMNOPQRSTU "
               "&& psql password=hunter2 && curl -H 'Authorization: Bearer abc.def'")
        rows = [user("Backend: D1", 100),
                asst([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": cmd, "description": "x"}}], 5)]
        subagent("s1", "b1", "Backend: D1", rows, 5)
        (TRANS / "s1.jsonl").write_text("")
        data = state()
        c = self.agent(data, "backend")["recentCommands"][0]["command"]
        for secret in ("ghp_ABCDEFGHIJ", "sk-proj-ABC", "hunter2", "abc.def"):
            self.assertNotIn(secret, c)
        self.assertIn("***", c)
        run = next(r for r in data["_runs"] if r["id"] == "b1")
        self.assertNotIn("hunter2", json.dumps(run))


class Compatibilidade(unittest.TestCase):
    OLD_STATE_KEYS = {"now", "log", "gates", "runs", "handoffs", "github", "usage"}
    OLD_RUN_KEYS = {"id", "agent", "description", "model", "models", "modelProvider", "demand", "status", "started",
                    "updated", "toolCount", "current", "files", "activity"}

    def setUp(self):
        reset_data()

    def test_log_py_sem_step_igual_ao_anterior(self):
        old = TMP / "old_log.py"
        old.write_text(subprocess.run(["git", "show", "HEAD:tools/squad/log.py"], cwd=REPO, capture_output=True,
                                      text=True, check=True).stdout)
        args = ["--agent", "backend", "--type", "handoff", "--to", "auditor", "--title", "t", "--detail", "d",
                "--demand", D, "--evidence", "a=pass", "--ref", "x.py", "--model", "claude-opus-5-5"]
        out = []
        for script in (old, REPO / "tools/squad/log.py"):
            f = TMP / f"log-{script.stem}.jsonl"
            env = {**os.environ, "SQUAD_LOG": str(f)}
            env.pop("SQUAD_RUN", None)
            subprocess.run([sys.executable, str(script), *args], env=env, check=True, capture_output=True)
            e = json.loads(f.read_text())
            e.pop("id"), e.pop("ts")
            out.append(list(e.items()))
        self.assertEqual(out[0], out[1])
        f = TMP / "log-step.jsonl"
        subprocess.run([sys.executable, str(REPO / "tools/squad/log.py"), *args, "--step", "F2 · implementação"],
                       env={**os.environ, "SQUAD_LOG": str(f)}, check=True, capture_output=True)
        self.assertEqual(json.loads(f.read_text())["step"], "F2 · implementação")
        r = subprocess.run([sys.executable, str(REPO / "tools/squad/log.py"), *args, "--step", "x" * 41],
                           env={**os.environ, "SQUAD_LOG": str(f)}, capture_output=True)
        self.assertNotEqual(r.returncode, 0, "--step aceita no máximo 40 caracteres")

    def test_api_state_e_live_por_http(self):
        write_log(base_rows() + [gate("G2", "RETURN", 0.62, 5, to="backend")])
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        try:
            st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state").read())
            self.assertTrue(self.OLD_STATE_KEYS <= set(st))
            self.assertTrue({"version", "thresholds", "summary", "alerts", "alertsHistory", "agents"} <= set(st))
            g = next(e for e in st["log"] if e["type"] == "gate")
            self.assertEqual((g["cycle"], g["returns"]), (1, 1))
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live")
            body = resp.read()
            self.assertLessEqual(len(body), 64 * 1024)
            self.assertEqual(resp.headers["Cache-Control"], "no-store")
            live = json.loads(body)
            self.assertEqual(set(live), {"now", "version", "serverMs", "thresholds", "summary", "alerts", "agents"})
            self.assertEqual([a["agent"] for a in live["agents"]], al.ROLES)
            self.assertEqual(live["summary"]["bloqueios"], 1)
            self.assertEqual(live["alerts"][0]["kinds"], ["human-required", "gate-return"])
            self.assertEqual(live["version"], st["version"])
            self.assertEqual(resp.headers["X-Squad-Version"], live["version"])
        finally:
            httpd.shutdown()

    def test_runs_mantem_chaves(self):
        write_log(base_rows())
        rows = [user("QA: D1", 100), asst([{"type": "text", "text": "ok"}], 100)]
        subagent("s1", "q1", "QA: D1", rows, 100)
        (TRANS / "s1.jsonl").write_text("")
        run = state()["_runs"][0]
        self.assertTrue(self.OLD_RUN_KEYS <= set(run))
        self.assertTrue({"lastActivityAt", "stalled", "waitingOn"} <= set(run))
        self.assertFalse([k for k in run if k.startswith("_")])


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
