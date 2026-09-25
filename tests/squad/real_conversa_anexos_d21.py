#!/usr/bin/env python3
"""D21 (71b7d9bc3313) — turnos REAIS de imagem na conversa (CA-I14/CA-I15, ressalvas 1 e 2 do G2-D21). Custo: manual.

Sobe o servidor DESTE repositório numa porta livre, com DATA_ROOT numa CÓPIA temporária (`--dir`, nunca o log real
nem a 7070) e um PATH com um "calço" que grava o argv de cada chamada ao CLI real (`argv.jsonl`) antes de executá-lo.
O DATA_ROOT vira um repositório git próprio (`git init` + commit vazio SÓ na cópia): no produtivo o cwd
`.squad/conversas/.sessao` fica dentro do repositório e o `codex exec resume` (sem `--skip-git-repo-check`) exige isso.

  python3 tests/squad/real_conversa_anexos_d21.py codex  --dir <scratch>/real-codex    # 3 turnos
  python3 tests/squad/real_conversa_anexos_d21.py claude --dir <scratch>/real-claude   # 2 turnos

codex  (CA-I15): T1 print.png → texto do alerta; T2 sem imagem → "191" por `exec resume`; T3 COM imagem nova
        (segundo.png) na sessão retomada e pergunta começando por "-" → texto da imagem nova. Prova: sessionReset falso
        em T2/T3, o mesmo threadId nos três e argv de T3 = `codex exec resume <threadId> --json -c
        sandbox_mode="read-only" --image=<abs> -- <prompt>`.
claude (CA-I14/ressalva 2): T1 print.png; T2 `--resume` COM duas imagens inline (segundo.png + quase5mb.png, sem
        SQUAD_CHAT_CLAUDE_B64_MAX) → texto das duas, `tools` vazio (sem plano B/Read), mesmo sessionId.
Saída: <dir>/resultado.json (turnos, argv, verificações) e código 0 se todas as verificações passarem.
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("runner", choices=("codex", "claude"))
ap.add_argument("--dir", required=True)
ap.add_argument("--no-git", action="store_true", help="não transforma a cópia em repositório git")
a = ap.parse_args()

base = pathlib.Path(a.dir).resolve()
shutil.rmtree(base, ignore_errors=True)
base.mkdir(parents=True)
os.environ["D21_TMP"] = str(base)
sys.path.insert(0, str(HERE))
import test_conversa_anexos_d21 as T  # noqa: E402

T.TMP = base
fx = T.prepare_fixtures(base / "fx")
T.FIX = fx
data = base / "data"
T.make_data(data)
(data / ".squad/conversas").mkdir(parents=True, exist_ok=True)
if not a.no_git:
    g = ["git", "-C", str(data), "-c", "user.name=qa", "-c", "user.email=qa@local"]
    subprocess.run(g[:3] + ["init", "-q"], check=True)
    (data / ".gitignore").write_text(".squad/\n")
    subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "copia de teste D21"], check=True)

real = shutil.which(a.runner)
shim = base / "bin"
shim.mkdir()
argv_log = base / "argv.jsonl"
(shim / a.runner).write_text(f"""#!{sys.executable}
import json, os, sys
with open({str(argv_log)!r}, "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}, ensure_ascii=False) + "\\n")
os.execv({real!r}, [{real!r}] + sys.argv[1:])
""")
(shim / a.runner).chmod(0o755)

port = T.free_port()
env = {"SQUAD_CHAT_RUNNER": a.runner, "SQUAD_CHAT_TIMEOUT_S": "300", "PATH": f"{shim}:{os.environ['PATH']}"}
p = T.start_server(data, port, env)
out = {"runner": a.runner, "port": port, "git": not a.no_git, "turns": [], "checks": {}}


def turn(cid, text, files):
    ids = []
    for f in files:
        st, r, _ = T.upload(cid, f, filename=f, port=port)
        assert st in (200, 201), (st, r)
        ids.append(r["id"])
    n0 = len(argv_log.read_text().splitlines()) if argv_log.exists() else 0
    t0 = time.time()
    st, r, evs = T.send(cid, text, ids or None, port=port)
    m = (evs[-1].get("data") or {}).get("message") if evs else r
    calls = [json.loads(x) for x in argv_log.read_text().splitlines()[n0:]] if argv_log.exists() else []
    rec = {"q": text, "images": files, "ids": ids, "http": st, "event": evs[-1]["event"] if evs else None,
           "status": (m or {}).get("status"), "text": (m or {}).get("text"), "error": (m or {}).get("error"),
           "model": (m or {}).get("model"), "sessionId": (m or {}).get("sessionId"),
           "sessionReset": (m or {}).get("sessionReset"), "tools": (m or {}).get("tools"),
           "calls": calls, "s": round(time.time() - t0, 1)}
    out["turns"].append(rec)
    print(json.dumps({k: v for k, v in rec.items() if k != "calls"}, ensure_ascii=False), flush=True)
    return rec


try:
    cid = T.new_conv(port)
    out["cid"] = cid
    anexos = data / f".squad/conversas/{cid}/anexos"
    t1 = turn(cid, "O que diz o alerta deste print? Responda só o texto do alerta.", ["print.png"])
    if a.runner == "codex":
        t2 = turn(cid, "Qual número de PR estava no print? Responda só o número.", [])
        t3 = turn(cid, "-leia a imagem que mandei agora e responda só o texto escrito nela.", ["segundo.png"])
        th = t1["sessionId"]
        exp = ["exec", "resume", th, "--json", "-c", 'sandbox_mode="read-only"',
               f"--image={anexos.resolve() / (t3['ids'][0] + '.png')}", "--", None]
        argv3 = t3["calls"][-1]["argv"] if t3["calls"] else []
        c = out["checks"]
        # A fonte 5×7 do print.png deixa "B" parecido com "8": o codex (gpt-5.6-sol) lê "ALERTA 86" (rodadas de 25/09).
        # O que o CA-I15 prova é que a imagem chegou: exige "#191"/"CONFLITO"; "B6" fica só registrado.
        c["T1 ok com imagem (#191 e CONFLITO)"] = t1["status"] == "ok" and "191" in (t1["text"] or "") and "CONFLITO" in (t1["text"] or "").upper()
        out["T1 leu B6 (informativo)"] = "B6" in (t1["text"] or "")
        c["T2 '191' sem sessionReset"] = t2["status"] == "ok" and "191" in (t2["text"] or "") and t2["sessionReset"] is False
        c["T3 sem sessionReset"] = t3["sessionReset"] is False
        c["mesmo threadId T1..T3"] = bool(th) and t2["sessionId"] == th and t3["sessionId"] == th
        c["T3 uma única chamada (sem nova sessão)"] = len(t3["calls"]) == 1
        c["argv T3 = exec resume <th> --json -c sandbox --image=<abs> -- <prompt>"] = (
            len(argv3) == len(exp) and argv3[:-1] == exp[:-1] and argv3[-1].endswith(t3["q"]))
        c["T3 prompt começa por '-' (na última posição, depois de --)"] = argv3[-2:-1] == ["--"] and "Pergunta do humano:\n-leia" in argv3[-1]
        c["T3 resposta com o texto da imagem nova"] = "4271" in (t3["text"] or "") and "KAFKA" in (t3["text"] or "").upper()
        out["argvT3"] = argv3[:-1] + [f"<prompt de {len(argv3[-1])} chars terminando em {argv3[-1][-80:]!r}>"] if argv3 else []
    else:
        t2 = turn(cid, "Leia as duas imagens que mandei agora e responda só o texto escrito em cada uma, na ordem "
                       "(imagem 1: ..., imagem 2: ...).", ["segundo.png", "quase5mb.png"])
        argv2 = t2["calls"][-1]["argv"] if t2["calls"] else []
        c = out["checks"]
        c["T1 ok com imagem (B6 e #191)"] = t1["status"] == "ok" and "B6" in (t1["text"] or "") and "191" in (t1["text"] or "")
        c["T2 retomado (--resume <mesmo uuid>)"] = "--resume" in argv2 and argv2[argv2.index("--resume") + 1] == t1["sessionId"]
        c["T2 stream-json (imagem inline)"] = argv2[:3] == ["-p", "--input-format", "stream-json"]
        c["T2 sem sessionReset"] = t2["sessionReset"] is False and t2["sessionId"] == t1["sessionId"]
        c["T2 sem ferramentas (sem plano B/Read)"] = t2["tools"] == []
        c["T2 texto das duas imagens"] = all(k in (t2["text"] or "").upper() for k in ("4271", "KAFKA", "5813"))
        c["SQUAD_CHAT_CLAUDE_B64_MAX ausente"] = "SQUAD_CHAT_CLAUDE_B64_MAX" not in os.environ
    out["ok"] = all(out["checks"].values())
finally:
    T.stop(p)
    (base / "resultado.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(json.dumps(out["checks"], ensure_ascii=False, indent=1))
sys.exit(0 if out.get("ok") else 1)
