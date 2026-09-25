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
- Modelo (ADR-012): `--model <id>` (ou `SQUAD_MODEL`) vira `-m` no codex / `--model` no claude. O modelo GRAVADO no
  run é o efetivo: cabeçalho `model:`/`provider:` da saída do codex; `message.model` da transcrição do `claude -p`
  (identificada por `--session-id`). O alias do frontmatter (ex.: `opus`) só vai em `modelRequested`.
  O filho recebe `SQUAD_RUN` (e `SQUAD_MODEL`, se o ID já é conhecido) para os eventos herdarem run/modelo.
- Delegação (D19, ADR-022): `--delegation <id>` marca a run (`delegation` no `.squad/runs/<id>.json` e nos `progress`
  de início/fim — uma run delegada que parar não é delegável de novo), exporta `SQUAD_DELEGATION` e `SQUAD_LOG` (log
  ÚNICO da cópia principal, mesmo que o agente chame `log.py` relativo no worktree) e monta o prompt do
  `docs/squad/prompts/delegacao.md`: a tarefa confirmada pelo humano vai entre `<tarefa_confirmada_pelo_humano>`; o
  alvo (handoff, change-request, gate, evidência) e `--dados <arquivo>` (diffs, conflitos) vão entre `<dados>`.
  `--worktree <caminho>` = cwd do agente (worktree da demanda).
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
MAIN_LOG = pathlib.Path(os.environ.get("SQUAD_LOG") or ROOT / "docs/squad/memory/decisions.jsonl")
DELEGATION_PROMPT = ROOT / "docs/squad/prompts/delegacao.md"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from server import codex_header, provider_of, scan_transcript, model_fields  # noqa: E402

ALIASES = {"opus", "sonnet", "haiku", "fable", "inherit", "default", "best", "opusplan"}


def is_exact_id(model: str | None) -> bool:
    """Alias (opus, sonnet...) não é ID exato e nunca é gravado em `model`."""
    return bool(model) and model.lower() not in ALIASES


def claude_transcript(session_id: str) -> pathlib.Path:
    base = os.environ.get("SQUAD_TRANSCRIPTS")
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(ROOT))
    return (pathlib.Path(base) if base else pathlib.Path.home() / ".claude/projects" / slug) / f"{session_id}.jsonl"

READ_ONLY = {
    "claude": lambda prompt: ["claude", "-p", prompt, "--allowedTools", "Read", "Glob", "Grep"],
    "codex": lambda prompt: ["codex", "exec", "-C", str(ROOT), "-s", "read-only", prompt],
}
RUNNERS = {
    # Claude Code em modo não interativo: edições aceitas, Bash liberado para build/testes/log.py.
    "claude": lambda prompt, cwd=ROOT: ["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                                        "--allowedTools", "Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    # Codex CLI em modo não interativo, com escrita restrita ao repositório (ou ao worktree da demanda).
    "codex": lambda prompt, cwd=ROOT: ["codex", "exec", "-C", str(cwd), "-s", "workspace-write", prompt],
}


def _data(text: str) -> str:
    """Neutraliza marcas de fechamento dentro de dados/tarefa (nada sai da própria seção)."""
    return re.sub(r"</?\s*(dados|tarefa_confirmada_pelo_humano)\s*>", lambda m: m.group(0).replace("<", "&lt;"),
                  text or "", flags=re.I)


def read_events() -> list[dict]:
    try:
        return [json.loads(l) for l in MAIN_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def delegation_prompt(delegation_id: str, worktree: str | None, extra_data: str = "") -> str:
    """Seção da delegação no prompt do executor (contrato §8.3, §10). Só a tarefa confirmada é instrução do humano."""
    rows = read_events()
    dl = next((e for e in rows if e.get("id") == delegation_id and e.get("type") == "delegation"), None)
    if dl is None:
        sys.exit(f"delegação {delegation_id} não encontrada em {MAIN_LOG}")
    try:
        base = DELEGATION_PROMPT.read_text(encoding="utf-8").strip()
    except OSError:
        base = "# Delegação\nExecute só a tarefa confirmada pelo humano, dentro das regras de AGENTS.md."
    fill = {"{LOG_PY}": str(ROOT / "tools/squad/log.py"), "{GITFLOW_PY}": str(ROOT / "tools/squad/gitflow.py"),
            "{LOG}": str(MAIN_LOG), "{WORKTREE}": worktree or "(o Orquestrador informa)",
            "{DELEGATION}": delegation_id, "{DEMAND}": dl.get("demand") or "", "{BRANCH}": dl.get("branch") or ""}
    for k, v in fill.items():
        base = base.replace(k, v)
    target = dl.get("target") or ""
    tid = target.split(":", 1)[-1] if target.startswith(("handoff-stalled:", "change-request-open:")) else target
    related = [e for e in rows if e.get("id") in (tid, (target.split(":", 1)[-1] if ":" in target else None))]
    data = {"delegacao": {k: dl.get(k) for k in ("id", "demand", "category", "target", "owner", "risk", "attempt",
                                                 "pr", "branch", "run", "title")},
            "alvo": [{k: e.get(k) for k in ("id", "type", "agent", "to", "title", "detail", "refs", "evidences",
                                            "gate", "recommendation") if e.get(k) is not None} for e in related]}
    return (f"{base}\n\n<tarefa_confirmada_pelo_humano>\n{_data(dl.get('detail') or '')}\n</tarefa_confirmada_pelo_humano>\n\n"
            f"<dados>\n{_data(json.dumps(data, ensure_ascii=False, indent=1))}"
            + (f"\n{_data(extra_data)}" if extra_data else "") + "\n</dados>")


def role_file(role: str) -> pathlib.Path:
    path = ROOT / ("docs/squad/orquestrador.md" if role == "orquestrador" else f".claude/agents/{role}.md")
    if not path.exists():
        sys.exit(f"papel desconhecido: {role} ({path} não existe)")
    return path


def role_prompt(role: str) -> str:
    text = role_file(role).read_text(encoding="utf-8")
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S).strip()  # remove o frontmatter do Claude Code


def role_model_alias(role: str) -> str | None:
    m = re.match(r"\A---\n(.*?)\n---\n", role_file(role).read_text(encoding="utf-8"), flags=re.S)
    mm = re.search(r"^model:\s*(\S+)", m.group(1), flags=re.M) if m else None
    return mm.group(1) if mm else None


def effective_model(runner: str, out_path: pathlib.Path, session_id: str | None) -> dict:
    """Modelo que de fato rodou: cabeçalho do codex ou transcrição do claude -p."""
    if runner == "codex" and out_path.exists():
        head = codex_header(out_path.read_text(encoding="utf-8", errors="ignore")[:20000])
        if head.get("model"):
            return {"model": head["model"], "modelProvider": provider_of(head["model"], head.get("provider"), runner)}
    if runner == "claude" and session_id:
        f = model_fields(scan_transcript(claude_transcript(session_id))["models"], "anthropic")
        if f["model"]:
            return {"model": f["model"], "modelProvider": f["modelProvider"]}
    return {}


def log(role: str, title: str, run_id: str, runner: str, demand: str | None, detail: str = "",
        model: str | None = None, delegation: str | None = None):
    args = [sys.executable, str(ROOT / "tools/squad/log.py"), "--agent", role, "--type", "progress",
            "--title", title, "--run", run_id, "--runner", runner]
    if demand:
        args += ["--demand", demand]
    if delegation:
        args += ["--delegation", delegation]
    if model:
        args += ["--model", model]
    if detail:
        args += ["--detail", detail]
    env = {k: v for k, v in os.environ.items() if k not in ("SQUAD_MODEL", "SQUAD_RUN", "SQUAD_DELEGATION")}
    subprocess.run(args, cwd=ROOT, capture_output=True, env=env)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("role")
    p.add_argument("task", help="texto da tarefa ou @arquivo")
    p.add_argument("--runner", default=os.environ.get("SQUAD_RUNNER", "claude"), choices=sorted(RUNNERS))
    p.add_argument("--demand")
    p.add_argument("--model", default=os.environ.get("SQUAD_MODEL") or None,
                   help="modelo pedido ao fornecedor (-m no codex, --model no claude); padrão: $SQUAD_MODEL")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--read-only", action="store_true", help="sem escrita nem shell (ex.: triagem de demandas)")
    p.add_argument("--delegation", help="D19: id do evento `delegation` que esta run executa")
    p.add_argument("--worktree", help="D19: worktree da demanda (cwd do agente)")
    p.add_argument("--dados", help="D19: arquivo com dados (diff, conflitos, trechos do log) — vai entre <dados>")
    a = p.parse_args()

    task = (ROOT / a.task[1:]).read_text(encoding="utf-8") if a.task.startswith("@") else a.task
    cwd = pathlib.Path(a.worktree).resolve() if a.worktree else ROOT
    if a.worktree and not cwd.is_dir():
        sys.exit(f"worktree inexistente: {cwd}")
    if a.delegation:
        extra = pathlib.Path(a.dados).read_text(encoding="utf-8", errors="ignore")[:20000] if a.dados else ""
        task = f"{task}\n\n{delegation_prompt(a.delegation, str(cwd) if a.worktree else None, extra)}"
    run_id = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{a.role}-{uuid.uuid4().hex[:6]}"
    prompt = (
        "Você é um agente da squad do projeto neste repositório. Leia primeiro `AGENTS.md` (regras comuns, "
        "ownership, protocolo de handoff, Git Flow e limites de autonomia) e siga-o.\n\n"
        f"# Seu papel\n\n{role_prompt(a.role)}\n\n# Tarefa\n\n{task}\n\n"
        "# Registro\n\n"
        f"- Registre marcos do seu trabalho: `python3 tools/squad/log.py --agent {a.role} --type progress "
        f"--run {run_id} --title \"<o que está fazendo>\"`"
        + (f" --demand {a.demand}" if a.demand else "")
        + (f" --delegation {a.delegation}" if a.delegation else "") + ".\n"
        "- Handoffs, pareceres e evidências seguem o protocolo de `AGENTS.md`"
        + (f", sempre com `--demand {a.demand}`" if a.demand else "") + ".\n"
        "- Não faça commit, push nem merge: quem integra é o Orquestrador, via `tools/squad/gitflow.py`.\n"
    )
    if a.read_only:
        prompt = prompt.replace("- Registre marcos do seu trabalho", "- Modo SOMENTE LEITURA: não escreva arquivos nem rode comandos; ignore a linha abaixo sobre registrar marcos.\n- (Não) Registre marcos do seu trabalho")
    if a.delegation:
        prompt = prompt.replace("`python3 tools/squad/log.py", f"`python3 \"{ROOT / 'tools/squad/log.py'}\"")
    cmd = READ_ONLY[a.runner](prompt) if a.read_only else RUNNERS[a.runner](prompt, cwd)
    session_id = None
    if a.runner == "claude":
        session_id = str(uuid.uuid4())
        cmd += ["--session-id", session_id] + (["--model", a.model] if a.model else [])
    elif a.model:
        cmd = cmd[:-1] + ["-m", a.model, cmd[-1]]  # prompt continua sendo o último argumento
    requested = a.model or (role_model_alias(a.role) if a.runner == "claude" else None)
    known_model = a.model if is_exact_id(a.model) else None
    if a.dry_run:
        print(json.dumps({"runner": a.runner, "cmd": cmd[:-1] if a.runner == "codex" else cmd[:2] + ["<prompt>"] + cmd[3:],
                          "sessionId": session_id, "modelRequested": requested,
                          "env": {"SQUAD_RUN": run_id, **({"SQUAD_MODEL": known_model} if known_model else {}),
                                  **({"SQUAD_DELEGATION": a.delegation, "SQUAD_LOG": str(MAIN_LOG)}
                                     if a.delegation else {})},
                          "cwd": str(cwd), "delegation": a.delegation,
                          "prompt": prompt}, ensure_ascii=False, indent=2))
        return

    RUNS.mkdir(parents=True, exist_ok=True)
    meta_path, out_path = RUNS / f"{run_id}.json", RUNS / f"{run_id}.log"
    meta = {"id": run_id, "agent": a.role, "runner": a.runner, "demand": a.demand,
            "description": f"{a.role.capitalize()} · {task.strip().splitlines()[0][:80]}",
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "trabalhando"}
    if requested:
        meta["modelRequested"] = requested
    if session_id:
        meta["sessionId"] = session_id
    if a.delegation:
        meta["delegation"] = a.delegation
        meta["worktree"] = str(cwd)
    log(a.role, f"Iniciado via {a.runner}: {task.strip().splitlines()[0][:100]}", run_id, a.runner, a.demand,
        model=known_model, delegation=a.delegation)
    child_env = {**os.environ, "SQUAD_RUN": run_id}
    child_env.pop("SQUAD_MODEL", None)
    child_env.pop("SQUAD_DELEGATION", None)
    if known_model:
        child_env["SQUAD_MODEL"] = known_model
    if a.delegation:   # log único: mesmo um `log.py` relativo no worktree grava no log da cópia principal
        child_env.update(SQUAD_DELEGATION=a.delegation, SQUAD_LOG=str(MAIN_LOG))
    with out_path.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                env=child_env)
        meta["pid"] = proc.pid
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        code = proc.wait()
    meta.update({"status": "concluído" if code == 0 else "falhou", "exitCode": code,
                 "ended": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    meta.update(effective_model(a.runner, out_path, session_id))
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    tail = out_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-15:]
    log(a.role, f"Finalizado via {a.runner} (código {code})", run_id, a.runner, a.demand, "\n".join(tail)[-1500:],
        model=meta.get("model"), delegation=a.delegation)
    print(out_path.read_text(encoding="utf-8", errors="ignore")[-4000:])
    sys.exit(code)


if __name__ == "__main__":
    main()
