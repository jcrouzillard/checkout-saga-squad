#!/usr/bin/env python3
"""Runner simulado da conversa com o Orquestrador (D17) — `SQUAD_CHAT_RUNNER=fake SQUAD_CHAT_FAKE=<este arquivo>`.

Emite o stream-json do `claude -p` (system/init, stream_event/content_block_delta, assistant, result) e grava no cwd
(`<DATA_ROOT>/.squad/conversas/.sessao/`) o argv e os NOMES das variáveis de ambiente recebidas
(`fake_last_argv.json`), para os testes conferirem `build_cmd` e o ambiente do filho sem executar o `claude` real.

Palavras-chave na pergunta do humano (texto depois de "Pergunta do humano:"):
  LER            → usa a ferramenta Read em docs/squad/gates/G1-D17.json (fase "consultando")
  DORMIR         → manda "parcial " e dorme 200 s (timeout / cancelar)
  LENTO          → resposta longa em trechos a cada 0,2 s (~2,5 s; reconexão do SSE)
  FALHAR         → sai com código 1 e mensagem de login (erro do runner)
  SESSAO_PERDIDA → com --resume, sai com "No conversation found" (sessão perdida → sessionReset)
  ECO            → diz se o prompt trouxe <historico_da_conversa>
  INJECAO        → diz se o contexto trouxe o texto injetado "IGNORE AS REGRAS"
  PROPOR:<json>  → termina a resposta com o bloco ```destravar <json>```
"""
import json
import os
import pathlib
import sys
import time

MODEL = "claude-fake-1-20260901"
argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
question = prompt.split("Pergunta do humano:\n", 1)[-1]
cwd = pathlib.Path.cwd()
data_root = cwd.parents[2] if len(cwd.parents) > 2 else cwd
(cwd / "fake_last_argv.json").write_text(json.dumps({"argv": argv, "env": sorted(os.environ)}))


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def delta(text):
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}})


if "SESSAO_PERDIDA" in question and "--resume" in argv:
    print("No conversation found with session ID", file=sys.stderr)
    sys.exit(1)
if "FALHAR" in question:
    print("Invalid API key · Please run /login", file=sys.stderr)
    sys.exit(1)
out({"type": "system", "subtype": "init", "model": MODEL, "session_id": "x"})
if "DORMIR" in question:
    delta("parcial ")
    time.sleep(200)
if "LER" in question:
    out({"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Read"}}})
    out({"type": "assistant", "message": {"model": MODEL, "content": [
        {"type": "tool_use", "id": "t1", "name": "Read",
         "input": {"file_path": str(data_root / "docs/squad/gates/G1-D17.json")}}]}})
    time.sleep(0.3)
text = "Resposta simulada da **D17**. "
if "ECO" in question:
    text += "histórico: " + ("sim" if "<historico_da_conversa>" in prompt else "não") + ". "
if "INJECAO" in question:
    text += "contexto contém injeção: " + ("sim" if "IGNORE AS REGRAS" in prompt else "não") + ". "
if "LENTO" in question:
    text += "Trecho longo da resposta para acompanhar o streaming. " * 3
if "PROPOR:" in question:
    block = question.split("PROPOR:", 1)[1].strip()
    text += "Posso destravar.\n\n```destravar\n" + block + "\n```\n"
step, pause = (16, 0.2) if "LENTO" in question else (12, 0.02)
for i in range(0, len(text), step):
    delta(text[i:i + step])
    time.sleep(pause)
out({"type": "assistant", "message": {"model": MODEL, "content": [{"type": "text", "text": text}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": text})
