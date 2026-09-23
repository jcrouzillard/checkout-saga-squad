#!/usr/bin/env python3
"""Executa um papel da squad com o fornecedor de IA escolhido (Claude Code ou Codex).

  SQUAD_RUNNER=codex  python3 tools/squad/run_agent.py qa "Validar o cenário X" --demand <id>
  SQUAD_RUNNER=claude python3 tools/squad/run_agent.py arquiteto @docs/tarefa.md
  python3 tools/squad/run_agent.py auditor "..." --runner codex --dry-run

- O prompt do papel é o corpo de `.claude/agents/<papel>.md` (o frontmatter só serve ao Claude Code); o Orquestrador
  usa `docs/squad/orquestrador.md`. As regras comuns vêm de `AGENTS.md`.
- Cada execução grava `.squad/runs/<id>.json` (metadados) e `.squad/runs/<id>.log` (saída ao vivo), lidos pelo
  Squad Control, e registra `progress` no log da squad no início e no fim.
- A execução é bloqueante: o Orquestrador de qualquer fornecedor delega chamando este script.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNS = ROOT / ".squad/runs"

RUNNERS = {
    # Claude Code em modo não interativo: edições aceitas, Bash liberado para build/testes/log.py.
    "claude": lambda prompt: ["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                              "--allowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    # Codex CLI em modo não interativo, com escrita restrita ao repositório.
    "codex": lambda prompt: ["codex", "exec", "-C", str(ROOT), "-s", "workspace-write", prompt],
}


def role_prompt(role: str) -> str:
    path = ROOT / ("docs/squad/orquestrador.md" if role == "orquestrador" else f".claude/agents/{role}.md")
    if not path.exists():
        sys.exit(f"papel desconhecido: {role} ({path} não existe)")
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()  # remove o frontmatter do Claude Code


def log(role: str, title: str, run_id: str, runner: str, demand: str | None, detail: str = ""):
    args = [sys.executable, str(ROOT / "tools/squad/log.py"), "--agent", role, "--type", "progress",
            "--title", title, "--run", run_id, "--runner", runner]
    if demand:
        args += ["--demand", demand]
    if detail:
        args += ["--detail", detail]
    subprocess.run(args, cwd=ROOT, capture_output=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("role")
    p.add_argument("task", help="texto da tarefa ou @arquivo")
    p.add_argument("--runner", default=os.environ.get("SQUAD_RUNNER", "claude"), choices=sorted(RUNNERS))
    p.add_argument("--demand")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    task = (ROOT / a.task[1:]).read_text(encoding="utf-8") if a.task.startswith("@") else a.task
    run_id = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{a.role}-{uuid.uuid4().hex[:6]}"
    prompt = (
        "Você é um agente da squad do projeto neste repositório. Leia primeiro `AGENTS.md` (regras comuns, "
        "ownership, protocolo de handoff, Git Flow e limites de autonomia) e siga-o.\n\n"
        f"# Seu papel\n\n{role_prompt(a.role)}\n\n# Tarefa\n\n{task}\n\n"
        "# Registro\n\n"
        f"- Registre marcos do seu trabalho: `python3 tools/squad/log.py --agent {a.role} --type progress "
        f"--run {run_id} --title \"<o que está fazendo>\"`"
        + (f" --demand {a.demand}" if a.demand else "") + ".\n"
        "- Handoffs, pareceres e evidências seguem o protocolo de `AGENTS.md`"
        + (f", sempre com `--demand {a.demand}`" if a.demand else "") + ".\n"
        "- Não faça commit, push nem merge: quem integra é o Orquestrador, via `tools/squad/gitflow.py`.\n"
    )
    cmd = RUNNERS[a.runner](prompt)
    if a.dry_run:
        print(json.dumps({"runner": a.runner, "cmd": cmd[:-1] if a.runner == "codex" else cmd[:2] + ["<prompt>"] + cmd[3:],
                          "prompt": prompt}, ensure_ascii=False, indent=2))
        return

    RUNS.mkdir(parents=True, exist_ok=True)
    meta_path, out_path = RUNS / f"{run_id}.json", RUNS / f"{run_id}.log"
    meta = {"id": run_id, "agent": a.role, "runner": a.runner, "demand": a.demand,
            "description": f"{a.role.capitalize()} · {task.strip().splitlines()[0][:80]}",
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "trabalhando"}
    log(a.role, f"Iniciado via {a.runner}: {task.strip().splitlines()[0][:100]}", run_id, a.runner, a.demand)
    with out_path.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        meta["pid"] = proc.pid
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        code = proc.wait()
    meta.update({"status": "concluído" if code == 0 else "falhou", "exitCode": code,
                 "ended": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    tail = out_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-15:]
    log(a.role, f"Finalizado via {a.runner} (código {code})", run_id, a.runner, a.demand, "\n".join(tail)[-1500:])
    print(out_path.read_text(encoding="utf-8", errors="ignore")[-4000:])
    sys.exit(code)


if __name__ == "__main__":
    main()
