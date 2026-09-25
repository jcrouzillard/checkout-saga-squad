#!/usr/bin/env python3
"""Executa um papel da squad no executor configurado para ele (Claude Code ou Codex).

  python3 tools/squad/run_agent.py qa "Validar o cenário X" --demand <id>
  python3 tools/squad/run_agent.py arquiteto @docs/tarefa.md
  python3 tools/squad/run_agent.py auditor "..." --demand <id> --gate G2 [--worktree <dir>]
  python3 tools/squad/run_agent.py auditor "..." --runner codex --dry-run     # --runner/--model só com --dry-run

- D26 (ADR-027): o executor e o modelo vêm de `tools/squad/executores.py resolve` (camadas squad → agente → demanda;
  foto por demanda). `SQUAD_RUNNER`/`SQUAD_MODEL` NÃO configuram mais (aviso se diferirem); `SQUAD_MODEL` do pai nunca
  vira `--model` do filho. O comando segue o perfil do papel (leitura · auditoria · escrita · orquestracao, §7.1).
  Código 3 = política `parar` com o executor indisponível (nada é iniciado); 4 = configuração ilegível.

- O prompt do papel é o corpo de `.claude/agents/<papel>.md` (o frontmatter só serve ao Claude Code); o Orquestrador
  usa `docs/squad/orquestrador.md`. As regras comuns vêm de `AGENTS.md`.
- Cada execução grava `.squad/runs/<id>.json` (metadados) e `.squad/runs/<id>.log` (saída ao vivo), lidos pelo
  Squad Control, e registra `progress` no log da squad no início e no fim.
- A execução é bloqueante: o Orquestrador de qualquer fornecedor delega chamando este script.
- Modelo (ADR-012): `--model <id>` (ou `SQUAD_MODEL`) vira `-m` no codex / `--model` no claude. O modelo GRAVADO no
  run é o efetivo: cabeçalho `model:`/`provider:` da saída do codex; `message.model` da transcrição do `claude -p`
  (identificada por `--session-id`). O alias do frontmatter (ex.: `opus`) só vai em `modelRequested`.
  O filho recebe `SQUAD_RUN` (e `SQUAD_MODEL` SÓ com o modelo efetivo desta run, se o ID já é conhecido).
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
DELEGATION_PROMPT = ROOT / "docs/squad/prompts/delegacao.md"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from server import codex_header, provider_of, scan_transcript, model_fields  # noqa: E402
import product  # noqa: E402  (D23, F2a §6: runs no data_root resolvido e caminho exato da transcrição)
import executores as ex  # noqa: E402  (D26: resolvedor único de executor/modelo)

PRODUCT = product.resolve()
RUNS = PRODUCT.runs_dir          # = ROOT/.squad/runs sem $SQUAD_ROOT_DATA (o mesmo RUNS_DIR do servidor)
MAIN_LOG = PRODUCT.log           # $SQUAD_LOG > $SQUAD_ROOT_DATA > repositório

ALIASES = {"opus", "sonnet", "haiku", "fable", "inherit", "default", "best", "opusplan"}


def is_exact_id(model: str | None) -> bool:
    """Alias (opus, sonnet...) não é ID exato e nunca é gravado em `model`."""
    return bool(model) and model.lower() not in ALIASES


def claude_transcript(session_id: str, cwd: pathlib.Path = ROOT) -> pathlib.Path:
    """D23 (F2a §6): pasta do cwd EFETIVO do filho (o worktree, com --worktree), mesma regra do servidor."""
    return product.transcript_dir_for(cwd) / f"{session_id}.jsonl"

# D26 (ADR-027, contrato §7.1): o comando vem do PERFIL do papel × executor resolvido (executores.profile_cmd).
# Mantidos só como referência dos perfis antigos; nenhum caminho os usa para montar o comando.
RUNNERS = ("claude", "codex")


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


def effective_model(runner: str, out_path: pathlib.Path, session_id: str | None,
                    transcript: pathlib.Path | None = None) -> dict:
    """Modelo que de fato rodou: cabeçalho do codex ou transcrição do claude -p."""
    if runner == "codex" and out_path.exists():
        head = codex_header(out_path.read_text(encoding="utf-8", errors="ignore")[:20000])
        if head.get("model"):
            return {"model": head["model"], "modelProvider": provider_of(head["model"], head.get("provider"), runner)}
    if runner == "claude" and session_id:
        f = model_fields(scan_transcript(transcript or claude_transcript(session_id))["models"], "anthropic")
        if f["model"]:
            return {"model": f["model"], "modelProvider": f["modelProvider"]}
    return {}


def log(role: str, title: str, run_id: str, runner: str, demand: str | None, detail: str = "",
        model: str | None = None, delegation: str | None = None, res: dict | None = None):
    args = [sys.executable, str(ROOT / "tools/squad/log.py"), "--agent", role, "--type", "progress",
            "--title", title, "--run", run_id, "--runner", runner]
    if res:   # D26 §9.2: configurado × efetivo
        args += ["--runner-configured", res["configured"]["runner"], "--config-source", res["source"],
                 "--profile", res["profile"]]
        if res["configured"].get("model"):
            args += ["--model-configured", res["configured"]["model"]]
        if res.get("fallback"):
            args += ["--fallback", json.dumps({"reason": res["fallback"]["reason"], "from": res["fallback"]["from"]},
                                              ensure_ascii=False)]
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


def auth_failed_early(out_path: pathlib.Path, run_id: str) -> bool:
    """§6.3: saída casa falha de autenticação nas 50 primeiras linhas e o agente não registrou nenhum progress."""
    try:
        head = "\n".join(out_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:50])
    except OSError:
        return False
    if not ex.AUTH_FAIL_RE.search(head):
        return False
    return not any(e.get("type") == "progress" and e.get("run") == run_id
                   and not str(e.get("title", "")).startswith(("Iniciado via", "Finalizado via")) for e in read_events())


def verify_block(a, cwd: pathlib.Path) -> str:
    """§7.4: roda `gate.py verify` (lista fixa) ANTES do Auditor e devolve o JSON para o bloco <dados>."""
    if not (a.gate and a.demand):
        return ""
    p = subprocess.run([sys.executable, str(ROOT / "tools/squad/gate.py"), "verify", "--gate", a.gate, "--demand",
                        a.demand, "--worktree", str(cwd), "--json"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "SQUAD_LOG": str(MAIN_LOG)})
    return p.stdout.strip() or json.dumps({"gate": a.gate, "demand": a.demand, "erro": p.stderr.strip()[-500:]})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("role")
    p.add_argument("task", help="texto da tarefa ou @arquivo")
    p.add_argument("--runner", choices=sorted(RUNNERS), help="SÓ com --dry-run (a escolha real vem do painel)")
    p.add_argument("--demand")
    p.add_argument("--model", help="SÓ com --dry-run (a escolha real vem do painel)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--read-only", action="store_true", help="perfil `leitura` (= --context triagem)")
    p.add_argument("--context", choices=ex.CONTEXTS, help="plantao|conversa|triagem|passo (padrão: passo; "
                                                          "plantao para o orquestrador sem --demand)")
    p.add_argument("--no-snapshot", action="store_true", help="não cria a foto da demanda (triagem)")
    p.add_argument("--gate", choices=["G1", "G2", "G3"], help="D26: gate avaliado (auditor: gate.py verify/record)")
    p.add_argument("--fallback-of", help="D26 §6.3: run que falhou por autenticação (usa o padrão da squad; 1 vez)")
    p.add_argument("--delegation", help="D19: id do evento `delegation` que esta run executa")
    p.add_argument("--worktree", help="D19: worktree da demanda (cwd do agente)")
    p.add_argument("--dados", help="D19: arquivo com dados (diff, conflitos, trechos do log) — vai entre <dados>")
    a = p.parse_args()
    if (a.runner or a.model) and not a.dry_run:
        print("run_agent: --runner/--model só valem com --dry-run; use o painel (Squad Control → Executores) ou "
              "`tools/squad/executores.py`", file=sys.stderr)
        sys.exit(2)
    role_file(a.role)
    ctx_name = a.context or ("triagem" if a.read_only else "plantao" if a.role == "orquestrador" and not a.demand
                             else "passo")
    forced = None
    # G2-D26: o id da run nasce ANTES do resolvedor para o `executor-fallback` apontar a run que explica (B9 por run)
    run_id = f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{a.role}-{uuid.uuid4().hex[:6]}"
    try:
        ectx = ex.context(MAIN_LOG)
        if a.fallback_of:
            prev = ex.resolve(a.role, a.demand, ctx_name, make_snapshot=not a.no_snapshot, do_check=False, ctx=ectx,
                              record=False, persist=not a.dry_run)
            forced = {"runner": prev["runner"], "detail": "sem-login"}
        res = ex.resolve(a.role, a.demand, ctx_name, make_snapshot=not a.no_snapshot, do_check=not a.dry_run,
                         ctx=ectx, forced_unavailable=forced, persist=not a.dry_run, run=run_id)
    except ex.ExecError as e:
        print(f"run_agent: {e.message}", file=sys.stderr)   # código 3: `executor-fallback{action:parou}` já gravado
        sys.exit(e.exit_code)
    except product.ProductError as e:
        print(f"run_agent: {e}", file=sys.stderr)
        sys.exit(ex.EXIT_CONFIG)
    for w in res["warnings"]:
        if w.startswith("variavel_ignorada:"):
            print(f"run_agent: aviso: {w.split(':', 1)[1]} ignorada (a configuração vem do painel/executores.py)",
                  file=sys.stderr)
    if a.dry_run and a.runner:   # simulação: outro executor/modelo só para ver o comando
        res = {**res, "runner": a.runner, "model": a.model, "profile": ex.profile_of(a.role, a.runner, ctx_name)}
        res["modelArg"] = a.model or (role_model_alias(a.role) if a.runner == "claude" else None)
        res["via"] = ex.via_of(a.runner, a.model)
    elif a.dry_run and a.model:
        res = {**res, "model": a.model, "modelArg": a.model, "via": ex.via_of(res["runner"], a.model)}
    if a.read_only:
        res["profile"] = "leitura"
    runner, model_arg, profile = res["runner"], res["modelArg"], res["profile"]

    task = (ROOT / a.task[1:]).read_text(encoding="utf-8") if a.task.startswith("@") else a.task
    cwd = pathlib.Path(a.worktree).resolve() if a.worktree else ROOT
    if a.worktree and not cwd.is_dir():
        sys.exit(f"worktree inexistente: {cwd}")
    if a.delegation:
        extra = pathlib.Path(a.dados).read_text(encoding="utf-8", errors="ignore")[:20000] if a.dados else ""
        task = f"{task}\n\n{delegation_prompt(a.delegation, str(cwd) if a.worktree else None, extra)}"
    audit_ro = a.role == "auditor" and profile == "auditoria"
    if audit_ro and not a.dry_run:
        vb = verify_block(a, cwd)
        if vb:
            task += f"\n\n<dados>\n{_data(vb)}\n</dados>"
    read_only = profile in ("leitura", "auditoria")
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
    if read_only:
        prompt = prompt.replace("- Registre marcos do seu trabalho", "- Modo SOMENTE LEITURA: não escreva arquivos nem rode comandos; ignore a linha abaixo sobre registrar marcos.\n- (Não) Registre marcos do seu trabalho")
    if audit_ro:
        prompt += ("- Perfil `auditoria` (somente leitura): NÃO grave `docs/squad/gates/*.json` nem o evento `gate`. "
                   "Termine com UM bloco ```parecer contendo o JSON do parecer (formato de `docs/squad/gates.md` e "
                   "`.claude/agents/auditor.md`); quem grava é o chamador (`tools/squad/gate.py record`). Use o "
                   "`status` de cada verificação do `gate.py verify` (bloco <dados>) como evidência, com `\"check\": "
                   "\"<id>\"`; não reexecute build/testes.\n")
    if a.delegation:
        prompt = prompt.replace("`python3 tools/squad/log.py", f"`python3 \"{ROOT / 'tools/squad/log.py'}\"")
    try:
        cmd = ex.profile_cmd(profile, runner, prompt, cwd, product.resolve().data_root, MAIN_LOG.parent, RUNS)
    except ex.ExecError as e:
        print(f"run_agent: {e.message}", file=sys.stderr)
        sys.exit(e.exit_code)
    session_id = None
    if runner == "claude":
        session_id = str(uuid.uuid4())
        cmd += ["--session-id", session_id]
    cmd = ex.with_model(cmd, runner, model_arg)
    requested = model_arg
    known_model = model_arg if is_exact_id(model_arg) else None   # só o efetivo desta run (nunca o do pai)
    configured_fields = {"runnerConfigured": res["configured"]["runner"],
                         "modelConfigured": res["configured"].get("model"), "configSource": res["source"],
                         "profile": profile,
                         "fallback": ({"reason": res["fallback"]["reason"], "from": res["fallback"]["from"]}
                                      if res.get("fallback") else None)}
    if a.fallback_of:
        configured_fields["fallbackOf"] = a.fallback_of
    if a.dry_run:
        prompt_idx = 2
        shown = cmd[:-1] if runner == "codex" else cmd[:prompt_idx] + ["<prompt>"] + cmd[prompt_idx + 1:]
        print(json.dumps({"runner": runner, "cmd": shown,
                          "sessionId": session_id, "modelRequested": requested, "via": res["via"],
                          **configured_fields,
                          "env": {"SQUAD_RUN": run_id, **({"SQUAD_MODEL": known_model} if known_model else {}),
                                  **({"SQUAD_DELEGATION": a.delegation, "SQUAD_LOG": str(MAIN_LOG)}
                                     if a.delegation else {})},
                          "cwd": str(cwd), "delegation": a.delegation,
                          "prompt": prompt}, ensure_ascii=False, indent=2))
        return

    RUNS.mkdir(parents=True, exist_ok=True)
    meta_path, out_path = RUNS / f"{run_id}.json", RUNS / f"{run_id}.log"
    meta = {"id": run_id, "agent": a.role, "runner": runner, "demand": a.demand,
            "description": f"{a.role.capitalize()} · {task.strip().splitlines()[0][:80]}",
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "trabalhando",
            **configured_fields}
    if a.gate:
        meta["gate"] = a.gate
    if requested:
        meta["modelRequested"] = requested
    if session_id:
        meta["sessionId"] = session_id
        meta["transcript"] = str(claude_transcript(session_id, cwd))   # D23 (F2a §6): caminho exato
    if a.delegation:
        meta["delegation"] = a.delegation
        meta["worktree"] = str(cwd)
    log(a.role, f"Iniciado via {runner}: {task.strip().splitlines()[0][:100]}", run_id, runner, a.demand,
        model=known_model, delegation=a.delegation, res=res)
    child_env = {**os.environ, "SQUAD_RUN": run_id}
    child_env.pop("SQUAD_MODEL", None)          # D26: nunca herda o modelo do pai
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
    meta.update(effective_model(runner, out_path, session_id,
                                pathlib.Path(meta["transcript"]) if meta.get("transcript") else None))
    retry = code != 0 and not a.fallback_of and auth_failed_early(out_path, run_id)
    if retry:
        meta["authFailure"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    tail = out_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-15:]
    log(a.role, f"Finalizado via {runner} (código {code})", run_id, runner, a.demand, "\n".join(tail)[-1500:],
        model=meta.get("model"), delegation=a.delegation, res=res)
    if retry:   # §6.3: falha de autenticação na saída → mesma política, UMA vez (nova run com --fallback-of)
        ex.invalidate(ectx, runner)
        argv = [sys.executable, str(pathlib.Path(__file__).resolve()), *[x for x in sys.argv[1:]], "--fallback-of", run_id]
        sys.exit(subprocess.run(argv, env={k: v for k, v in os.environ.items()}).returncode)
    if audit_ro:   # §7.3: o parecer do Auditor somente leitura é gravado pelo chamador
        rec = [sys.executable, str(ROOT / "tools/squad/gate.py"), "record", "--from-output", str(out_path),
               "--run", run_id, "--worktree", str(cwd)]
        if a.demand:
            rec += ["--demand", a.demand]
        if meta.get("model"):
            rec += ["--model", meta["model"]]
        if a.delegation:
            rec += ["--delegation", a.delegation]
        r = subprocess.run(rec, cwd=ROOT, capture_output=True, text=True, env={**os.environ, "SQUAD_LOG": str(MAIN_LOG)})
        print((r.stdout + r.stderr).strip())
    print(out_path.read_text(encoding="utf-8", errors="ignore")[-4000:])
    sys.exit(code)


if __name__ == "__main__":
    main()
