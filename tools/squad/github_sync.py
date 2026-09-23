#!/usr/bin/env python3
"""Projeta o log da squad (decisions.jsonl) em Issues + GitHub Project (kanban).

O log continua sendo a fonte da verdade; o GitHub é uma projeção. O sync é idempotente:
eventos já processados ficam em docs/squad/memory/github-sync.json.

  task            -> nova issue (Em andamento)
  handoff         -> comentário com o brief; card vai para "Gate (Auditor)"
  evidence        -> comentário na issue em andamento do agente
  gate            -> parecer do Auditor comentado; APPROVE fecha (Concluído), RETURN volta para Em andamento,
                     confiança < 70% / risco alto -> "Intervenção humana"
  human           -> decisão humana comentada na issue do gate
  defect / change-request -> nova issue no Backlog
  decision        -> comentário no "Diário da squad"

Uso: python3 tools/squad/github_sync.py [--watch 20]
Config: SQUAD_GH_REPO (default jcrouzillard/checkout-saga-squad), SQUAD_GH_OWNER, SQUAD_GH_PROJECT (número).
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = ROOT / "docs/squad/memory/decisions.jsonl"
STATE = ROOT / "docs/squad/memory/github-sync.json"
HANDOFFS = ROOT / "docs/squad/memory/handoffs"
REPO = os.environ.get("SQUAD_GH_REPO", "jcrouzillard/checkout-saga-squad")
OWNER = os.environ.get("SQUAD_GH_OWNER", REPO.split("/")[0])
PROJECT = os.environ.get("SQUAD_GH_PROJECT", "1")

LABEL = {"orquestrador": "Orquestrador", "arquiteto": "Arquiteto", "backend": "Backend", "devops": "DevOps",
         "observabilidade": "Observabilidade", "qa": "QA", "auditor": "Auditor", "humano": "Humano"}
GATE_COVERS = {"G1": ["arquiteto"], "G2": ["backend", "devops", "observabilidade"], "G3": ["qa"]}
STATUS_ICON = {"pass": "✅", "fail": "❌", "validate": "🟡"}


def gh(*args: str, parse=False):
    out = subprocess.run(["gh", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {out.stderr.strip()}")
    return json.loads(out.stdout) if parse else out.stdout.strip()


def branch() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or "main"


class Sync:
    def __init__(self):
        self.s = json.loads(STATE.read_text()) if STATE.exists() else {"processed": [], "issues": {}}
        self.br = branch()
        if "project" not in self.s:
            self._load_project()

    # ---------- infraestrutura do Project ----------
    def _load_project(self):
        proj = gh("project", "view", PROJECT, "--owner", OWNER, "--format", "json", parse=True)
        fields = gh("project", "field-list", PROJECT, "--owner", OWNER, "--format", "json", parse=True)["fields"]
        f = {x["name"]: {"id": x["id"], "options": {o["name"]: o["id"] for o in x.get("options", [])}}
             for x in fields if x["name"] in ("Status", "Agente", "Fase")}
        self.s["project"] = {"id": proj["id"], "url": proj["url"], "fields": f}

    def save(self):
        STATE.write_text(json.dumps(self.s, ensure_ascii=False, indent=1))

    def set_field(self, issue: dict, field: str, value: str | None):
        fd = self.s["project"]["fields"].get(field)
        if not value or not fd or value not in fd["options"]:
            return
        gh("project", "item-edit", "--id", issue["item"], "--project-id", self.s["project"]["id"],
           "--field-id", fd["id"], "--single-select-option-id", fd["options"][value])
        if field == "Status":
            issue["status"] = value

    # ---------- helpers de issue ----------
    def link(self, path: str) -> str:
        return f"[`{path}`](https://github.com/{REPO}/blob/{self.br}/{path})"

    def create_issue(self, key: str, title: str, body: str, agent: str, labels: list[str], status: str,
                     phase: str | None) -> dict:
        labels = [f"agent:{agent}", "squad", *labels]
        url = gh("issue", "create", "-R", REPO, "--title", title, "--body", body, "--label", ",".join(labels))
        item = gh("project", "item-add", PROJECT, "--owner", OWNER, "--url", url, "--format", "json", parse=True)
        issue = {"number": int(url.rstrip("/").split("/")[-1]), "url": url, "item": item["id"], "agent": agent,
                 "status": None, "phase": phase, "handed": False, "closed": False,
                 "kind": "ticket" if any(l in ("defect", "change-request") for l in labels) else "task"}
        self.s["issues"][key] = issue
        self.set_field(issue, "Status", status)
        self.set_field(issue, "Agente", LABEL.get(agent))
        self.set_field(issue, "Fase", phase)
        print(f"  #{issue['number']} {title}")
        return issue

    def comment(self, issue: dict, body: str):
        gh("issue", "comment", str(issue["number"]), "-R", REPO, "--body", body)

    def close(self, issue: dict):
        if not issue["closed"]:
            gh("issue", "close", str(issue["number"]), "-R", REPO)
            issue["closed"] = True

    def reopen(self, issue: dict):
        if issue["closed"]:
            gh("issue", "reopen", str(issue["number"]), "-R", REPO)
            issue["closed"] = False

    def issues_of(self, agent: str, **filters) -> list[dict]:
        """Issues de tarefa do agente (tickets de defect/change-request ficam fora: são anotações, não trabalho em curso)."""
        out = [i for k, i in self.s["issues"].items()
               if i["agent"] == agent and not k.startswith("_") and i.get("kind", "task") != "ticket"]
        return [i for i in out if all(i.get(k) == v for k, v in filters.items())]

    def diary(self) -> dict:
        d = self.s["issues"].get("_diario")
        if not d:
            d = self.create_issue("_diario", "📒 Diário de decisões da squad",
                                  "Espelho das decisões registradas em "
                                  f"{self.link('docs/squad/memory/decisions.jsonl')}. Fonte da verdade: o log no repositório.",
                                  "orquestrador", [], "Em andamento", None)
        return d

    # ---------- formatação ----------
    def body(self, e: dict, header: str) -> str:
        lines = [f"**{header}** · `{e['agent']}` · {e['ts']}", "", f"### {e['title']}"]
        if e.get("detail"):
            lines += ["", e["detail"]]
        if e.get("evidences"):
            lines += ["", "| Evidência | Status |", "|---|---|"]
            lines += [f"| {v['name']} | {STATUS_ICON.get(v['status'], '')} {v['status']} |" for v in e["evidences"]]
        if e.get("refs"):
            lines += ["", "Arquivos: " + ", ".join(self.link(r) for r in e["refs"])]
        lines += ["", f"<sub>evento `{e['id']}` · gerado por tools/squad/github_sync.py</sub>"]
        return "\n".join(lines)

    @staticmethod
    def phase_of(e: dict) -> str | None:
        m = re.match(r"^(F\d|G\d)", e.get("title", "")) or re.search(r"gate (G\d)", e.get("title", ""))
        return m.group(1) if m else e.get("gate")

    def handoff_brief(self, agent: str) -> str:
        files = sorted(HANDOFFS.glob(f"*{agent}*"), key=lambda p: p.stat().st_mtime)
        return f"\n\n<details><summary>Brief de handoff ({files[-1].name})</summary>\n\n{files[-1].read_text()}\n</details>" if files else ""

    # ---------- eventos ----------
    def on_task(self, e):
        to = e.get("to", "orquestrador")
        phase = self.phase_of(e)
        self.create_issue(e["id"], e["title"] if phase else f"{e['title']}", self.body(e, "Delegação do Orquestrador"),
                          to, [], "Em andamento", phase)

    def on_handoff(self, e):
        agent = e["agent"]
        open_ = self.issues_of(agent, handed=False, closed=False)
        issue = open_[-1] if open_ else self.create_issue(
            e["id"], e["title"], self.body(e, "Entrega registrada (sem delegação prévia no log)"), agent, [],
            "Em andamento", {"arquiteto": "F1", "devops": "F2", "observabilidade": "F2", "backend": "F2", "qa": "F3"}.get(agent))
        self.comment(issue, self.body(e, f"Handoff → {LABEL.get(e.get('to'), e.get('to', ''))}") + self.handoff_brief(agent))
        issue["handed"] = True
        self.set_field(issue, "Status", "Gate (Auditor)")

    def on_evidence(self, e):
        open_ = self.issues_of(e["agent"], closed=False)
        if open_:
            self.comment(open_[-1], self.body(e, "Evidência"))

    def on_gate(self, e):
        g, rec = e.get("gate"), e.get("recommendation")
        conf = e.get("confidence")
        human = (conf is not None and conf < 0.7) or e.get("risk") == "alto"
        verdict = f"Parecer do Auditor · {g} · {rec} · {round((conf or 0) * 100)}% · risco {e.get('risk', '—')}"
        for agent in GATE_COVERS.get(g, []):
            for issue in self.issues_of(agent, handed=True, closed=False):
                self.comment(issue, self.body(e, verdict))
                if human:
                    self.set_field(issue, "Status", "Intervenção humana")
                elif rec == "APPROVE":
                    self.set_field(issue, "Status", "Concluído")
                    self.close(issue)
                else:
                    issue["handed"] = False
                    self.set_field(issue, "Status", "Em andamento")
        for issue in self.issues_of("auditor", closed=False):
            self.comment(issue, self.body(e, verdict))
            self.set_field(issue, "Status", "Concluído")
            self.close(issue)
        self.s.setdefault("gates", {})[g] = e["id"]

    def on_human(self, e):
        g = e.get("gate")
        targets = [i for a in GATE_COVERS.get(g, []) for i in self.issues_of(a)] or [self.diary()]
        for issue in targets[-3:]:
            self.comment(issue, self.body(e, f"Intervenção humana · {g or ''}"))
            if e.get("recommendation") == "RETURN":
                self.reopen(issue)
                issue["handed"] = False
                self.set_field(issue, "Status", "Em andamento")

    def on_ticket(self, e):
        label = e["type"]
        to = e.get("to") or e["agent"]
        self.create_issue(e["id"], f"[{label}] {e['title']}", self.body(e, label), to, [label], "Backlog", None)

    def on_decision(self, e):
        self.comment(self.diary(), self.body(e, "Decisão"))

    def on_start(self, e):
        issue = self.s["issues"].get(e.get("demand"))
        if not issue:
            return
        self.comment(issue, self.body(e, f"Demanda iniciada pelo humano · prioridade {e.get('priority', 'normal')} · rota {e.get('route', 'padrao')}"))
        self.set_field(issue, "Status", "Em andamento")
        label = f"prioridade:{e.get('priority', 'normal')}"
        subprocess.run(["gh", "label", "create", label, "--color", "1F3A5F", "-R", REPO, "-f"], capture_output=True)
        subprocess.run(["gh", "issue", "edit", str(issue["number"]), "-R", REPO, "--add-label", label], capture_output=True)

    def on_demand_event(self, e):
        """Qualquer evento que carregue `demand` também é comentado na issue da demanda; G3 APPROVE a conclui."""
        issue = self.s["issues"].get(e.get("demand"))
        if not issue or e["type"] in ("start", "task") and e["agent"] == "humano":
            return
        self.comment(issue, self.body(e, f"{e['type']} · {LABEL.get(e['agent'], e['agent'])}"))
        if e["type"] == "gate" and e.get("gate") == "G3" and e.get("recommendation") == "APPROVE":
            self.set_field(issue, "Status", "Concluído")
            self.close(issue)

    def run_once(self) -> int:
        done = set(self.s["processed"])
        events = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
        handlers = {"task": self.on_task, "handoff": self.on_handoff, "evidence": self.on_evidence,
                    "gate": self.on_gate, "human": self.on_human, "defect": self.on_ticket,
                    "change-request": self.on_ticket, "decision": self.on_decision, "start": self.on_start}
        n = 0
        for e in events:
            if e["id"] in done:
                continue
            h = handlers.get(e["type"])
            if h:
                print(f"{e['type']:<14} {e['agent']:<15} {e['title'][:70]}")
                h(e)
            if e.get("demand"):
                self.on_demand_event(e)
            self.s["processed"].append(e["id"])
            self.save()  # salva a cada evento: uma falha no meio não duplica issues
            n += 1
        return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="segundos entre sincronizações (0 = uma vez)")
    a = ap.parse_args()
    sync = Sync()
    print(f"Board: {sync.s['project']['url']}")
    while True:
        try:
            sync.run_once()
        except RuntimeError as err:  # rede/GitHub fora: a squad segue; tentamos de novo no próximo ciclo
            print(f"aviso: {err}", file=sys.stderr)
        if not a.watch:
            break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
