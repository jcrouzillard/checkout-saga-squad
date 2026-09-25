#!/usr/bin/env python3
"""Runner simulado da conversa (D19, QA). Formato de saída igual ao do `claude -p --output-format stream-json`.

- `DELEGAR:<json>` na pergunta → resposta termina com o bloco ```delegar com esse JSON (literal).
- `PROPOR:<json>` → bloco ```destravar (D17).
- Pedido pré-preenchido do servidor ("Delegar a correção do conflito do PR #n da Dk ...", "Delegar a continuidade ...",
  "Delegar ao dono ...", "Delegar uma nova tentativa ...") → bloco ```delegar derivado do pedido (como o modelo faria).
- Pedidos reservados ao humano (merge, cancelar, pausar, ...) → resposta que orienta o caminho no Squad Control, sem
  bloco (CA-24).
Nunca chama um modelo real.
"""
import json
import re
import sys

argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
q = prompt.split("Pergunta do humano:\n", 1)[-1].strip()
M = "claude-fake-1-20260901"


def out(o):
    print(json.dumps(o, ensure_ascii=False), flush=True)


out({"type": "system", "subtype": "init", "model": M, "session_id": "x"})
text = "Resposta simulada. "
code = (re.search(r"\b(D\d+)\b", q) or [None, None])[1]
alvo = (re.search(r"alvo ([A-Za-z0-9:_.-]+)\)", q) or [None, None])[1]
if "DELEGAR:" in q:
    text += "Posso delegar.\n\n```delegar\n" + q.split("DELEGAR:", 1)[1].strip() + "\n```\n"
elif "PROPOR:" in q:
    text += "Posso destravar.\n\n```destravar\n" + q.split("PROPOR:", 1)[1].strip() + "\n```\n"
elif q.startswith("Delegar") and code:
    tipo = ("conflito-develop" if "conflito do PR" in q else "pendencia-change-request" if "change-request" in q
            else "pendencia-agente-parado" if "nova tentativa" in q else "pendencia-handoff" if "handoff" in q
            else "ambiente-teste")
    block = {"demanda": code, "tipo": tipo, "tarefa": q[:1900]}
    if alvo:
        block["alvo"] = alvo
    text += f"Entendi: {tipo} na {code}. Confira o cartão.\n\n```delegar\n" + json.dumps(block, ensure_ascii=False) + "\n```\n"
elif re.search(r"\b(merge|cancel|paus|repriori|nova demanda|publi)", q, re.I):
    text += ("Isso é decisão sua e não vira delegação: faça pelo Squad Control (merge no GitHub; cancelar, pausar ou "
             "repriorizar na tela da demanda; nova demanda no botão Nova demanda; publicar no ambiente de teste).")
else:
    text += "Sem ação."
for i in range(0, len(text), 40):
    out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text[i:i + 40]}}})
out({"type": "assistant", "message": {"model": M, "content": [{"type": "text", "text": text}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": text})
