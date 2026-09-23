#!/usr/bin/env python3
"""Validação agêntica de uma demanda (D4 / ADR-008), independente de fornecedor.

  python3 tools/squad/triage.py <id da demanda> [--runner claude|codex]

Roda o Arquiteto em modo SOMENTE LEITURA (run_agent.py --read-only), extrai o JSON da resposta e grava UM evento
`validation` no log da squad. O agente não escreve nada; quem registra é este executor.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG = ROOT / "docs/squad/memory/decisions.jsonl"
DIMS = {"objetivo", "aceite", "escopo", "restricoes", "tipo"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("demand")
    p.add_argument("--runner", default=os.environ.get("SQUAD_RUNNER", "claude"))
    a = p.parse_args()
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    d = next((r for r in rows if r.get("id") == a.demand and r.get("type") == "task"), None)
    if not d:
        sys.exit(f"demanda {a.demand} não encontrada")
    subprocess.run([sys.executable, str(ROOT / "tools/squad/log.py"), "--agent", "arquiteto", "--type", "progress",
                    "--demand", a.demand, "--runner", a.runner, "--title", "Triagem: validando a clareza da demanda"],
                   cwd=ROOT, capture_output=True)
    task = (f"{(ROOT / 'docs/squad/prompts/triagem.md').read_text(encoding='utf-8')}\n\n## Demanda a validar\n\n"
            f"- Título: {d['title'].replace('Demanda: ', '')}\n- Tipo informado: {d.get('kind')}\n"
            f"- Descrição: {d.get('detail') or '(vazia)'}\n")
    tmp = ROOT / ".squad" / f"triagem-{a.demand}.md"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(task, encoding="utf-8")
    out = subprocess.run([sys.executable, str(ROOT / "tools/squad/run_agent.py"), "arquiteto", f"@{tmp.relative_to(ROOT)}",
                          "--runner", a.runner, "--demand", a.demand, "--read-only"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    result, dec = None, json.JSONDecoder()
    for i, ch in enumerate(out):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(out[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "status" in obj:
                result = obj
    failed = result is None
    if failed:
        result = {"status": "perguntas", "questions": [{"dimension": "objetivo",
                  "text": "A validação automática não conseguiu analisar a demanda; descreva o resultado esperado e como verificar que está pronto."}]}
    qs = [q for q in result.get("questions", []) if (q.get("text") or "").strip()][:5]
    status = "ok" if result.get("status") == "ok" or not qs else "perguntas"
    args = [sys.executable, str(ROOT / "tools/squad/log.py"), "--agent", "arquiteto", "--type", "validation",
            "--demand", a.demand, "--to", "humano", "--status", status, "--runner", a.runner,
            "--title", ("Validação automática falhou: responda a pergunta ou inicie com override" if failed
                        else "Validação: pronta para iniciar" if status == "ok" else f"Validação: {len(qs)} pergunta(s)")]
    if failed:
        args += ["--detail", "O agente de triagem não devolveu um resultado válido; veja .squad/runs/ (saída do runner)."]
    for q in (qs if status == "perguntas" else []):
        dim = q.get("dimension") if q.get("dimension") in DIMS else "escopo"
        args += ["--question", f"{dim}::{q['text'].strip()}"]
    if result.get("suggestedKind") in ("produto", "operacao") and result["suggestedKind"] != d.get("kind"):
        args += ["--suggested-kind", result["suggestedKind"]]
    print(subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout.strip())


if __name__ == "__main__":
    main()
