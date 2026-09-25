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
  FXD20          → texto FX do contrato ui-conversa-visual-v2 §4 (D20) em trechos de 20 caracteres a cada 0,45 s e 1 s
                   com o texto completo antes do fim
  MDV6           → Markdown completo do CA-V6 (D20): parágrafo, lista numerada, lista aninhada, código, bloco de 120
                   colunas, citação, tabela 4×3, link interno/externo, `**negrito` sem fechar e `<img onerror>` literal
  LONGO          → resposta longa (40 parágrafos curtos) em trechos a cada 0,25 s (~10 s; rolagem do CA-V7, D20)
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
if "FXD20" in question:   # D20 §4: FX com trechos ≥ 400 ms (streaming observável pelo navegador)
    text = ("Recebido. O registro confirma:\n\n- **08:47** – suas respostas à triagem da D19 foram registradas.\n"
            "- 08:47 – você iniciou a D19.\n\nUse `pending` e veja [o painel](#/painel).")
    step, pause = 20, 0.45
if "MDV6" in question:   # D20 CA-V6
    text = ("Parágrafo inicial com `código` e **negrito**.\n\n1. primeiro\n2. segundo\n\n- externo\n  - aninhado\n- outro\n\n"
            "```\n" + ("x" * 118) + "\n```\n\n> citação do registro\n\n| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n| 7 | 8 | 9 |\n\n"
            "Veja [o painel](#/painel) e [a doc](https://example.com/doc). Fim com **negrito sem fechar e <img src=x onerror=alert(1)>")
    step, pause = 40, 0.05
if "LONGO" in question:   # D20 CA-V7
    text = "".join(f"Parágrafo {i:02d} da resposta longa para testar a rolagem do painel.\n\n" for i in range(1, 41))
    step, pause = 70, 0.25
for i in range(0, len(text), step):
    delta(text[i:i + step])
    time.sleep(pause)
if "FXD20" in question:
    time.sleep(1.0)   # texto completo visível ao vivo antes do `fim` (CA-V2 compara ao vivo × final)
out({"type": "assistant", "message": {"model": MODEL, "content": [{"type": "text", "text": text}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": text})
