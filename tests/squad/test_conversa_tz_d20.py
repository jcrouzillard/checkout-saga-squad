#!/usr/bin/env python3
"""D20 (`41bdb8b49835`) — CA-V5 (defeito d): contexto e prompt da conversa no fuso do humano (QA, teste de reprodução).

Contrato: docs/contracts/ui-conversa-visual-v2.md §3.4 (servidor e prompt) e CA-V5; parecer docs/squad/gates/G1-D20.json
(a função real é `build_context`, não `context_block`; o `tz` atravessa POST → Engine.send → _run → build_context).

Causa do bug (reproduzida aqui): `build_context()` repassa `eventosRecentes[].ts` crus do decisions.jsonl (UTC,
`+00:00`) e o cabeçalho `<dados_da_squad gerado="…Z">` em UTC, sem dizer o fuso do humano; o POST ignora `tz`; o
prompt `docs/squad/prompts/conversa.md` não tem regra de horário. O modelo cita então 11:47 (UTC) onde o painel
mostra 08:47 (BRT).

Esperado: `build_context(state, data_root, tz=...)` (tz opcional, IANA validado por regex antes do `zoneinfo`;
inválido/ausente → fuso local do servidor, sem erro) com `ts` convertidos (`2026-09-25T08:47:11-03:00`) e cabeçalho
com `fuso="America/Sao_Paulo" utc="-03:00"` e `gerado=` no mesmo fuso; POST com `tz` → 202 inalterado e o prompt do
runner traz o fuso; registros `.squad/conversas/*.jsonl` continuam em UTC (`Z`).

Isolado: DATA_ROOT temporário e servidor do worktree em porta livre com o runner SIMULADO
(tests/squad/conversa_fake_runner.py) — sem POST no :7070, sem log real, sem `claude` real.
Uso: python3 tests/squad/test_conversa_tz_d20.py
"""
import http.client
import inspect
import json
import os
import pathlib
import re
import signal
import sys
import time
import types
import unittest
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tools/squad"))
sys.path.insert(0, str(HERE))
import conversa as cv  # noqa: E402
import test_conversa_d17 as h  # noqa: E402  (harness: make_data, start_server, free_port, TMP)

TS_UTC = "2026-09-25T11:47:11+00:00"
SP = "America/Sao_Paulo"


def state():
    rules = types.SimpleNamespace(codes={}, canceled=set(), delivered=set())
    return {"rows": [{"id": "e1", "ts": TS_UTC, "agent": "humano", "type": "human", "title": "respostas da triagem D19"}],
            "rules": rules}


def ctx(**kw):
    """Chama build_context com tz quando a assinatura aceita; hoje não aceita (a asserção abaixo mostra o UTC cru)."""
    if "tz" in inspect.signature(cv.build_context).parameters:
        return cv.build_context(state(), None, **kw)
    return cv.build_context(state(), None)


def parse(out: str):
    head = out.split("\n", 1)[0]
    body = json.loads(out.split("\n", 1)[1].rsplit("\n</dados_da_squad>", 1)[0])
    return head, body


def local_offset(ts_iso: str) -> str:
    d = datetime.fromisoformat(ts_iso).astimezone()
    o = d.strftime("%z")
    return f"{o[:3]}:{o[3:]}"


class ContextoNoFuso(unittest.TestCase):
    def test_1_assinatura_aceita_tz_opcional(self):
        p = inspect.signature(cv.build_context).parameters
        self.assertIn("tz", p, "build_context não recebe o fuso do humano (defeito d: contexto só em UTC)")
        self.assertIsNot(p["tz"].default, inspect.Parameter.empty, "tz deve ser opcional")

    def test_2_eventos_convertidos_para_o_fuso(self):
        _, body = parse(ctx(tz=SP))
        self.assertEqual(body["eventosRecentes"][0]["ts"], "2026-09-25T08:47:11-03:00",
                         "eventosRecentes[].ts saiu cru em UTC — o modelo cita 11:47 onde o painel mostra 08:47")

    def test_3_cabecalho_com_fuso_e_gerado_local(self):
        head, _ = parse(ctx(tz=SP))
        self.assertIn(f'fuso="{SP}"', head, f"cabeçalho sem o fuso do humano: {head}")
        self.assertIn('utc="-03:00"', head, head)
        g = re.search(r'gerado="([^"]+)"', head)
        self.assertTrue(g and g.group(1).endswith("-03:00"), f"gerado= deveria estar no fuso do humano: {head}")

    def test_4_tz_invalido_cai_no_fuso_do_servidor_sem_erro(self):
        for bad in ("../x", "A" * 65, "America/Sao_Paulo; rm", "Nao/Existe_Zona"):
            with self.subTest(tz=bad):
                head, body = parse(ctx(tz=bad))
                ts = body["eventosRecentes"][0]["ts"]
                self.assertTrue(ts.endswith(local_offset(TS_UTC)), f"tz inválido deve usar o fuso do servidor: {ts}")
                self.assertIn(f'utc="{local_offset(TS_UTC)}"', head, head)
                self.assertNotIn(bad, head)

    def test_5_prompt_tem_regra_de_horario(self):
        txt = (REPO / "docs/squad/prompts/conversa.md").read_text(encoding="utf-8")
        self.assertTrue("<dados_da_squad fuso>" in txt, "conversa.md sem a regra de horário do §3.4.3")
        self.assertIn("Nunca escreva um horário UTC sem conversão", txt)


class RotaComTz(unittest.TestCase):
    """POST /api/conversas/<id>/mensagens com `tz` → 202; o prompt do runner simulado traz o fuso; registros em UTC."""

    @classmethod
    def setUpClass(cls):
        cls.data = h.TMP / "data-d20"
        h.make_data(cls.data)
        cls.port = h.free_port()
        cls.proc = h.start_server(cls.data, cls.port, err_name="server-d20")

    @classmethod
    def tearDownClass(cls):
        try:
            os.killpg(cls.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        cls.proc.wait(5)

    def req(self, m, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(m, path, body=json.dumps(body) if body is not None else None,
                  headers={"Host": f"localhost:{self.port}", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"null")

    def turn(self, tz):
        s, j = self.req("POST", "/api/conversas", {})
        self.assertIn(s, (200, 201), j)
        cid = j.get("id") or j.get("conversa", {}).get("id") or j.get("meta", {}).get("id")
        body = {"text": "a que horas registrei as respostas da D19?"}
        if tz is not None:
            body["tz"] = tz
        s, j = self.req("POST", f"/api/conversas/{cid}/mensagens", body)
        self.assertEqual(s, 202, j)
        self.assertEqual(set(j), {"turn", "message", "stream"}, "resposta do POST deve ficar inalterada")
        for _ in range(100):
            recs = [json.loads(x) for x in (self.data / f".squad/conversas/{cid}.jsonl").read_text().splitlines()]
            if any(r.get("role") == "orquestrador" and r.get("status") for r in recs):
                break
            time.sleep(0.1)
        argv = json.loads((self.data / ".squad/conversas/.sessao/fake_last_argv.json").read_text())["argv"]
        return recs, argv[argv.index("-p") + 1]

    def test_6_tz_valido_chega_ao_contexto_e_registro_segue_utc(self):
        recs, prompt = self.turn(SP)
        head = next(x for x in prompt.splitlines() if x.startswith("<dados_da_squad"))
        self.assertIn(f'fuso="{SP}"', head, f"o tz do POST não chegou ao contexto do runner: {head}")
        for r in recs:
            for k in ("ts", "createdAt"):
                if r.get(k):
                    self.assertTrue(r[k].endswith("Z"), f"registro da conversa deve continuar em UTC: {r[k]}")

    def test_7_tz_invalido_202_e_fuso_do_servidor(self):
        _, prompt = self.turn("../x")
        head = next(x for x in prompt.splitlines() if x.startswith("<dados_da_squad"))
        self.assertIn("fuso=", head, f"sem tz válido o contexto deve declarar o fuso do servidor: {head}")
        self.assertNotIn("../x", head)


def tearDownModule():
    import shutil
    shutil.rmtree(h.TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
