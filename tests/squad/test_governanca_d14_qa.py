#!/usr/bin/env python3
"""D14 (`1e3d3c894630`) — cenários complementares do QA para CA-S1..S8 (contrato ui-governanca-squad-control §13.1
com as erratas do §16 e as prioridades do parecer G2-D14).

Reaproveita o ambiente sintético de `test_alertas_d14.py` (SQUAD_ROOT_DATA/SQUAD_LOG/SQUAD_TRANSCRIPTS num diretório
temporário): nada toca o log real. Cobre o que a suíte do Orquestrador não cobre:
  - fechamentos que faltavam: B2 por decisão, B3 por decisão/cancelamento, B4 por `start` sem override (não fecha),
    A1 por cancelamento, A2 por nova atividade, A3 por cancelamento, B1 por `delivered`;
  - errata 1: STALLED_MAX_S (run aberta sem atividade há > 1 h não gera A2 nem fica "trabalhando");
  - errata 2: run externa interrompida há 11 min => estado `interrompido` (não `sem-progresso`) e um único A2;
  - errata 3: G3 APPROVE sem PR com confiança baixa mantém B2 aberto com a demanda encerrada; decisão humana fecha;
  - confiança 0,695: baixa nos dois lados (servidor abre B2) e texto da regra;
  - thresholds.stalledMaxSeconds no /api/live e no /api/state; segredos mascarados também no /api/live.

Uso: python3 tests/squad/test_governanca_d14_qa.py
"""
import json
import os
import pathlib
import shutil
import sys
import threading
import unittest
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import test_alertas_d14 as t  # noqa: E402  (prepara o ambiente sintético antes de importar o servidor)

server, al = t.server, t.al
D, D2 = t.D, t.D2
gate, human, ev, base_rows, write_log, state, open_by_kind = (t.gate, t.human, t.ev, t.base_rows, t.write_log, t.state,
                                                              t.open_by_kind)


def agent(data, role):
    return next(a for a in data["agents"] if a["agent"] == role)


class Fechamentos(unittest.TestCase):
    def setUp(self):
        t.reset_data()

    def test_b1_fecha_com_delivered(self):
        rows = base_rows() + [gate("G2", "RETURN", 0.8, 5, to="backend"),
                              ev("delivered", "orquestrador", 8, demand=D, pr=7)]
        write_log(rows)
        data = state()
        self.assertFalse(data["alerts"])
        h = next(x for x in data["alertsHistory"] if x["kind"] == "gate-return")
        self.assertEqual((h["closedBy"], h["closedByEvent"]), ("orquestrador", rows[-1]["id"]))

    def test_b2_fecha_com_decisao_return_humano(self):
        rows = base_rows() + [gate("G1", "APPROVE", 0.9, 5, risk="alto")]
        write_log(rows)
        self.assertEqual([a["kind"] for a in state()["alerts"]], ["human-required"])
        rows.append(human("G1", "RETURN", 6))
        write_log(rows)
        data = state()
        self.assertFalse(open_by_kind(data, "human-required"))
        self.assertEqual(data["alertsHistory"][0]["closedBy"], "humano")

    def test_b3_fecha_com_cancelamento(self):
        rows = base_rows() + [gate("G2", "RETURN", 0.8, m, to="frontend") for m in (1, 2, 3)]
        write_log(rows)
        self.assertTrue(open_by_kind(state(), "cycle-limit"))
        rows.append(ev("control", "humano", 4, demand=D, action="cancel"))
        write_log(rows)
        data = state()
        self.assertFalse(data["alerts"])
        self.assertIn("cycle-limit", {h["kind"] for h in data["alertsHistory"]})

    def test_b3_em_outra_chave_nao_soma(self):
        """returns(k) é por (demanda, gate): 2 RETURN em G2 + 1 em G3 não é 3º ciclo."""
        rows = base_rows() + [gate("G2", "RETURN", 0.8, 1, to="frontend"), gate("G2", "RETURN", 0.8, 2, to="frontend"),
                              gate("G3", "RETURN", 0.8, 3, to="qa")]
        write_log(rows)
        self.assertFalse(open_by_kind(state(), "cycle-limit"))

    def test_b4_start_sem_override_nao_fecha(self):
        val = ev("validation", "arquiteto", 1, demand=D, status="perguntas", questions=[{"id": "q1", "text": "?"}])
        write_log(base_rows() + [val, ev("start", "humano", 2, demand=D)])
        b4 = open_by_kind(state(), "triage-open")
        self.assertEqual(len(b4), 1)
        self.assertEqual(b4[0]["title"], "1 pergunta da triagem")

    def test_a1_fecha_com_cancelamento(self):
        rows = base_rows() + [gate("G2", "APPROVE", 0.6, 5, to="qa"), human("G2", "APPROVE", 6)]
        write_log(rows)
        self.assertEqual([a["kind"] for a in state()["alerts"]], ["low-confidence"])
        rows.append(ev("control", "humano", 7, demand=D, action="cancel"))
        write_log(rows)
        self.assertFalse(state()["alerts"])

    def test_a3_fecha_com_cancelamento(self):
        rows = base_rows() + [ev("review", "orquestrador", 3, demand=D, pr=5, url="https://example.invalid/pr/5"),
                              ev("control", "humano", 4, demand=D, action="cancel")]
        write_log(rows)
        self.assertFalse(state()["alerts"])


class ErrataG2(unittest.TestCase):
    def setUp(self):
        t.reset_data()
        write_log(base_rows())

    def test_stalled_max_run_com_mais_de_1h_sem_a2(self):
        t.Agentes._backend(self, 3601)
        data = state()
        self.assertFalse(open_by_kind(data, "agent-stalled"), "run sem atividade há > 1 h é sessão morta")
        self.assertNotIn(agent(data, "backend")["state"], ("trabalhando", "sem-progresso"))
        self.assertEqual(data["thresholds"]["stalledMaxSeconds"], 3600)

    def test_stalled_limite_superior_3599(self):
        t.Agentes._backend(self, 3590)
        data = state()
        self.assertEqual(len(open_by_kind(data, "agent-stalled")), 1)
        self.assertEqual(agent(data, "backend")["state"], "sem-progresso")

    def test_a2_fecha_com_nova_atividade(self):
        t.Agentes._backend(self, 700)
        self.assertTrue(open_by_kind(state(), "agent-stalled"))
        t.reset_data(); write_log(base_rows())
        t.Agentes._backend(self, 5)   # a mesma run, agora com atividade recente
        data = state()
        self.assertFalse(open_by_kind(data, "agent-stalled"))
        self.assertEqual(agent(data, "backend")["state"], "trabalhando")

    def test_interrompido_tem_precedencia_sobre_sem_progresso(self):
        meta = {"id": "r9", "agent": "devops", "runner": "claude", "status": "trabalhando", "pid": 999999,
                "started": t.iso_ago(1500), "demand": D, "description": "DevOps: D1"}
        p = t.RUNS / "r9.json"
        p.write_text(json.dumps(meta))
        os.utime(p, (t.time.time() - 660, t.time.time() - 660))   # 11 min sem atividade
        data = state()
        a2 = open_by_kind(data, "agent-stalled")
        self.assertEqual(len(a2), 1, "um único A2 (sem duplicar interrompido + sem progresso)")
        self.assertIn("interrompido", a2[0]["title"])
        self.assertEqual(agent(data, "devops")["state"], "interrompido")

    def test_g3_approve_baixa_confianca_b2_aberto_e_fecha_com_decisao(self):
        rows = base_rows() + [gate("G2", "APPROVE", 0.9, 1, to="qa"), gate("G3", "APPROVE", 0.62, 5, to="orquestrador")]
        write_log(rows)
        b2 = open_by_kind(state(), "human-required")
        self.assertEqual(len(b2), 1)
        self.assertEqual((b2[0]["gate"], b2[0]["owner"], b2[0]["action"]["href"]), ("G3", "humano", "#/demandas/D1/gates"))
        rows.append(human("G3", "APPROVE", 6))
        write_log(rows)
        self.assertFalse(open_by_kind(state(), "human-required"))

    # D14-QA-2 corrigido em e33a092 (A1 fecha com a demanda encerrada).
    def test_g3_approve_baixa_confianca_nada_aberto_apos_decisao(self):
        rows = base_rows() + [gate("G2", "APPROVE", 0.9, 1, to="qa"), gate("G3", "APPROVE", 0.62, 5, to="orquestrador")]
        write_log(rows)
        data = state()
        b2 = open_by_kind(data, "human-required")
        self.assertEqual(len(b2), 1)
        self.assertEqual((b2[0]["gate"], b2[0]["owner"], b2[0]["action"]["href"]), ("G3", "humano", "#/demandas/D1/gates"))
        rows.append(human("G3", "APPROVE", 6))
        write_log(rows)
        data = state()
        self.assertFalse(open_by_kind(data, "human-required"))
        # demanda encerrada (G3 APPROVE sem PR) => A1 do G3 também não deveria ficar aberto (§5.2 A1: fecha com demanda encerrada)
        self.assertFalse(data["alerts"], f"sobrou aberto em demanda encerrada: {[a['id'] for a in data['alerts']]}")

    def test_g3_com_pr_delivered_fecha_tudo(self):
        rows = base_rows() + [gate("G3", "APPROVE", 0.62, 5), ev("delivered", "orquestrador", 6, demand=D, pr=3)]
        write_log(rows)
        self.assertFalse(state()["alerts"])


class Confianca(unittest.TestCase):
    def setUp(self):
        t.reset_data()

    def test_0695_e_baixa_e_0700_nao(self):
        write_log(base_rows() + [gate("G2", "APPROVE", 0.695, 5, to="qa")])
        b2 = open_by_kind(state(), "human-required")
        self.assertEqual(len(b2), 1)
        self.rule_0695 = b2[0]["rule"]
        print(f"\n    texto da regra com 0,695: {b2[0]['rule']!r} / título: {b2[0]['title']!r}", file=sys.stderr)
        t.reset_data()
        write_log(base_rows() + [gate("G2", "APPROVE", 0.70, 5, to="qa")])
        self.assertFalse(state()["alerts"])

    # D14-QA-1 corrigido em e33a092 (pct_text: casa decimal só quando o arredondamento esconderia o valor abaixo do limite).
    def test_texto_da_regra_0695_nao_contraditorio(self):
        """0,695 aparece como '69,5%' na regra e no título; nunca 'confiança 70% < 70%'."""
        write_log(base_rows() + [gate("G2", "APPROVE", 0.695, 5, to="qa")])
        b2 = open_by_kind(state(), "human-required")[0]
        self.assertNotIn("70% < 70%", b2["rule"])
        self.assertIn("69,5% < 70%", b2["rule"])
        self.assertIn("69,5%", b2["title"])

    def test_pct_text_inteiro_nos_demais_casos(self):
        self.assertEqual(al.pct_text(0.62), "62")
        self.assertEqual(al.pct_text(0.70), "70")
        self.assertEqual(al.pct_text(0.9), "90")
        self.assertEqual(al.pct_text(0.694), "69")
        self.assertEqual(al.pct_text(0.695), "69,5")
        self.assertIsNone(al.pct_text(None))

    @unittest.expectedFailure   # DEFEITO D14-QA-5 (orquestrador): pct_text usa :.1f (arredonda) e 0,6996 lê "70,0% < 70%"; o front trunca (69,9%)
    def test_pct_text_06996_nao_vira_70(self):
        """Valor baixo que arredonda para 70,0 com 1 casa: o texto não pode ler '70,0% < 70%' (o front mostra 69,9%)."""
        txt = al.pct_text(0.6996)
        self.assertNotIn(txt, ("70", "70,0"))


class ApiHttp(unittest.TestCase):
    def setUp(self):
        t.reset_data()

    def test_live_thresholds_e_segredos(self):
        write_log(base_rows())
        cmd = "export GH=ghp_ABCDEFGHIJKLMNOPQRSTUVWX123 token=abc123 && curl -H 'Authorization: Bearer xyz.789'"
        rows = [t.user("Backend: D1", 100),
                t.asst([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": cmd, "description": "x"}}], 5)]
        t.subagent("s1", "b1", "Backend: D1", rows, 5)
        (t.TRANS / "s1.jsonl").write_text("")
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        try:
            live = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live").read().decode()
            st = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state").read().decode()
        finally:
            httpd.shutdown()
        for body in (live, st):
            for secret in ("ghp_ABCDEFGHIJ", "abc123", "xyz.789"):
                self.assertNotIn(secret, body)
            self.assertEqual(json.loads(body)["thresholds"]["stalledMaxSeconds"], 3600)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(t.TMP, ignore_errors=True)
