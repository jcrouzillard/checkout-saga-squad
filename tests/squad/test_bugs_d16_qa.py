#!/usr/bin/env python3
"""D16 (`841f9a27e64a`) — verificações do QA sobre as demandas de bug (complementa tests/squad/test_bugs_d16.py).

Reaproveita o harness isolado de test_bugs_d16 (SQUAD_ROOT_DATA/SQUAD_LOG temporários, Jaeger/Grafana simulados,
executor falso do `docker compose logs`). Nenhum POST ao servidor real (:7070) nem ao log real; nenhum container.

- CORPUS: logs realistas do Spring Boot (tests/squad/d16_corpus.py) enviados e gerados do link → nada sensível no
  arquivo, diagnóstico preservado, e o arquivo gravado em bugs/ é IDÊNTICO à prévia confirmada (bytes e sha256).
- PRÉVIA: limite de 200 linhas da prévia versus o arquivo inteiro que vai ao git.
- DESEMPENHO: `.log` de ~1 MB com uma linha longa (base64) → prévia em < 3 s (servidor inteiro); e-mail sem
  retrocesso (1 MB); casos antes quadráticos (QA-D16-2, corrigido) agora em tempo linear.
- CHAVES CURTAS: pin/otp/cvv/cvc/passphrase (adendo do Orquestrador) sem pegar spin/pinned/otpEnabled.
- CA-13 REAL: `gitflow.py feature-start` (CLI) e `align_memory` num CLONE temporário com origin nu temporário e a
  pasta bugs/ ainda não rastreada.

Uso: python3 tests/squad/test_bugs_d16_qa.py
"""
import base64
import hashlib
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_bugs_d16 as h  # noqa: E402  (sobe o harness isolado: servidor, produtivo simulado, executor falso)
import d16_corpus as corpus  # noqa: E402

er, bugs, te, gitflow = h.er, h.bugs, h.te, h.gitflow
KEY = b"k" * 32
REPO = h.REPO


class CorpusExec(te.Exec):
    """`docker compose -p checkout-saga logs` → corpus realista (com o trace_id pedido)."""

    def run(self, cmd, cwd=None, timeout=120):
        self.calls.append(list(cmd))
        if cmd[:4] == ["docker", "compose", "-p", "checkout-saga"] and "logs" in cmd:
            return te.Result(0, corpus.compose_output(h.TID))
        return te.Result(1, "", "não simulado")


def corpus_text() -> str:
    return "\n".join(corpus.lines()) + "\n"


def draft_file(d, name) -> bytes:
    st, body, _ = h.call("GET", f"/api/bug/draft/{d}/{name}")
    assert st == 200, (st, body)
    return body if isinstance(body, bytes) else json.dumps(body).encode()


class Q01Corpus(unittest.TestCase):
    """Item 3 do QA: corpus realista → máscara + prévia confirmada == arquivo gravado."""

    def check_masked(self, text):
        leaked = [s for s in corpus.SENSITIVE if s in text]
        self.assertEqual(leaked, [], "valores sensíveis sobraram no arquivo mascarado")
        lost = [s for s in corpus.PRESERVED if s not in text]
        self.assertEqual(lost, [], "diagnóstico perdido pela máscara")

    def test_corpus_enviado_previa_igual_ao_gravado(self):
        st, d, _ = h.draft("produto", files=[h.upload("order-service.log", corpus_text().encode())])
        self.assertEqual(st, 201, d)
        ev = d["evidences"][0]
        blob = draft_file(d["draft"], ev["file"])
        self.check_masked(blob.decode())
        # a prévia (≤ 200 linhas) é exatamente o começo do arquivo do rascunho
        self.assertEqual(ev["preview"], "\n".join(blob.decode().splitlines()[:200]))
        self.assertEqual(ev["sha256"], hashlib.sha256(blob).hexdigest())
        # idempotente (a revarredura na confirmação não muda nada)
        self.assertEqual(er.mask_text(blob.decode(), er.load_key(h.DATA))[0].encode(), blob)
        st, t, _ = h.create_bug(d["draft"], title="Envio falha com endereço inválido")
        self.assertEqual(st, 201, t)
        saved = (h.DATA / t["bug"]["dir"] / "evidencias" / ev["file"]).read_bytes()
        self.assertEqual(saved, blob, "arquivo gravado em bugs/ difere da prévia confirmada")
        self.assertEqual(t["bug"]["evidences"][0]["sha256"], hashlib.sha256(saved).hexdigest())
        st, served, hdr = h.call("GET", f"/api/bug/{t['id']}/file/{ev['file']}")
        self.assertEqual((st, served), (200, saved))
        self.assertTrue(hdr["Content-Type"].startswith("text/plain"))
        # nenhum valor sensível foi para o log da squad
        log = h.LOG.read_text()
        self.assertEqual([s for s in corpus.SENSITIVE if s in log], [])

    def test_corpus_gerado_do_link(self):
        old = te.EXEC
        te.set_exec(CorpusExec())
        try:
            st, d, _ = h.draft("produto", link=f"http://localhost:16686/trace/{h.TID}")
        finally:
            te.set_exec(old)
        self.assertEqual(st, 201, d)
        logs = [e for e in d["evidences"] if e["origin"] == "compose-logs"]
        self.assertEqual(len(logs), 1, d["evidences"])
        blob = draft_file(d["draft"], logs[0]["file"]).decode()
        self.check_masked(blob)
        self.assertNotIn("outro trace", blob)                         # só linhas do trace pedido
        self.assertEqual(logs[0]["preview"], "\n".join(blob.splitlines()[:200]))

    def test_linhas_json_continuam_json(self):
        """JSON do logback continua JSON após a máscara (payload escapado 1–2 vezes, stack trace, SQL)."""
        masked, _ = er.mask_text(corpus_text(), KEY)
        for ln in masked.splitlines():
            json.loads(ln)

    def test_nome_sem_aspas_nao_atravessa_a_string_json(self):
        """CORRIGIDO em e565020 — era o defeito (QA-D16-4): `customerName=\\"Ana\\" cpf=...` dentro do `message` → o padrão `nome=` sem aspas
        consome a aspa de fechamento do JSON; nada vaza (mascara a mais), mas a linha deixa de ser JSON válido."""
        masked, _ = er.mask_text(corpus.lines()[8], KEY)
        json.loads(masked)


class Q06ExtractedSummary(unittest.TestCase):
    """O resumo extraído do trace (`extracted.errorSpans[].exceptionMessage`/`statusDescription`) vai para o
    `bug.json`, que é commitado num repositório PÚBLICO."""
    TID_PII = "5bf92f3577b34da6a3ce929d0e0e4737"

    @classmethod
    def setUpClass(cls):
        h.Prod.traces[cls.TID_PII] = {"traceID": cls.TID_PII, "processes": {"p1": {"serviceName": "shipping-service"}},
            "spans": [{"traceID": cls.TID_PII, "spanID": "c1", "operationName": "shipping.commands process", "references": [],
                       "startTime": 1790282541550706, "duration": 1000, "processID": "p1",
                       "tags": [{"key": "otel.status_code", "value": "ERROR"},
                                {"key": "otel.status_description", "value": "cliente ana.ficticia@exemplo.com.br recusado"}],
                       "logs": [{"timestamp": 1790282541550800, "fields": [
                           {"key": "event", "value": "exception"}, {"key": "exception.type", "value": "java.lang.IllegalStateException"},
                           {"key": "exception.message", "value": "endereço inválido: " + corpus.ADDRESS_TOSTRING
                                                                  + " cpf=529.982.247-25 password=hunter2-inventado"}]}]}]}

    def draft_and_create(self):
        st, d, _ = h.draft("produto", link=f"http://localhost:16686/trace/{self.TID_PII}", includeLogs=False)
        self.assertEqual(st, 201, d)
        snap = draft_file(d["draft"], d["evidences"][0]["file"]).decode()
        st, t, _ = h.create_bug(d["draft"], title="Envio recusado")
        self.assertEqual(st, 201, t)
        return snap, (h.DATA / t["bug"]["dir"] / "bug.json").read_text(), d

    def test_snapshot_do_trace_mascarado(self):
        snap, _, _ = self.draft_and_create()
        for s in ("Rua das Acacias Ficticias", "ana.ficticia@exemplo.com.br", "529.982.247-25", "hunter2-inventado"):
            self.assertNotIn(s, snap)

    def test_resumo_extraido_no_bug_json_mascarado(self):
        """CORRIGIDO em e565020 — era o defeito (QA-D16-1): `extracted` (mensagem da exceção e status do span) é gravado em bug.json SEM máscara
        — endereço, e-mail, CPF e senha da mensagem da exceção vão para o git público; o arquivo 01-trace está
        mascarado, mas o resumo não. Também aparece na resposta do rascunho (prévia) e na página do bug."""
        _, doc, d = self.draft_and_create()
        leaked = [s for s in ("Rua das Acacias Ficticias", "ana.ficticia@exemplo.com.br", "529.982.247-25",
                              "hunter2-inventado") if s in doc or s in json.dumps(d["extracted"])]
        self.assertEqual(leaked, [])


class Q02Preview(unittest.TestCase):
    def test_previa_limitada_a_200_linhas_arquivo_inteiro_no_git(self):
        """Contrato §9: `preview` = até 200 linhas; o arquivo gravado tem TODAS as linhas (a UI precisa dizer isso)."""
        text = "".join(f"linha {i} ok\n" for i in range(500))
        st, d, _ = h.draft("operacao", files=[h.upload("longo.log", text.encode())])
        self.assertEqual(st, 201, d)
        ev = d["evidences"][0]
        self.assertEqual(len(ev["preview"].splitlines()), 200)
        self.assertEqual(len(draft_file(d["draft"], ev["file"]).decode().splitlines()), 500)


class Q03Performance(unittest.TestCase):
    """Item 4 do QA: prévia de um .log de ~1 MB com uma linha longa (base64) em < 3 s."""

    def test_previa_1mb_linha_base64_menos_de_3s(self):
        rnd = random.Random(16)
        line = "INFO anexo=" + base64.b64encode(rnd.randbytes(780_000)).decode()
        text = corpus_text() + line[: 1024 * 1024 - len(corpus_text()) - 200] + "\n"
        self.assertGreater(len(text.encode()), 1_000_000)
        self.assertLessEqual(len(text.encode()), er.MAX_LOG)
        t0 = time.monotonic()
        st, d, _ = h.draft("produto", files=[h.upload("grande.log", text.encode())])
        dt = time.monotonic() - t0
        self.assertEqual(st, 201, d)
        self.assertLess(dt, 3.0, f"prévia de 1 MB levou {dt:.2f} s")
        print(f"\n  prévia de {len(text.encode()) / 1e6:.2f} MB (linha base64 de {len(line) / 1e3:.0f} KB): {dt:.2f} s",
              file=sys.stderr)

    def test_email_sem_retrocesso_1mb(self):
        for text in ("a" * 1_000_000, "a.b-c_d" * 140_000 + "@x", "x@" + "y" * 999_990):
            t0 = time.monotonic()
            er.mask_text(text, KEY)
            self.assertLess(time.monotonic() - t0, 1.5)

    def _quick(self, text, limit=1.0):
        t0 = time.monotonic()
        er.mask_text(text, KEY)
        return time.monotonic() - t0

    def test_barras_invertidas_em_sequencia(self):
        """CORRIGIDO em e565020 — era o defeito (QA-D16-2): `chave_valor` começa com `\\\\*` sem âncora → quadrático numa sequência de barras:
        20 KB de `\\` levam ~22 s (1 MB: horas). Correção sugerida: `(?<!\\\\)` antes do `\\\\*` inicial."""
        self.assertLess(self._quick("\\" * 5_000), 0.5)

    def test_pontos_e_digitos_em_sequencia(self):
        """CORRIGIDO em e565020 — era o defeito (QA-D16-2): `_REC_START` (`(?<![\\w$])[\\w$.]*[Aa]ddress`) recomeça a cada caractere depois de
        `.` → quadrático em `....`, `1.1.1.` ou domínios longos: 40 KB ~4–9 s. Correção: `(?<![\\w$.])`."""
        self.assertLess(self._quick("." * 20_000), 0.5)


class Q04ShortKeys(unittest.TestCase):
    """Adendo do Orquestrador: pin/otp/cvv/cvc/passphrase mascarados; spin/pinned/otpEnabled não."""

    def test_chaves_curtas(self):
        masked_cases = ["pin=4321", "otp=998877", "cvv=123", "cvc: 456", "passphrase=abc", "card_pin=77",
                        "x-otp: 55", '"cvv":"123"', "cvv='123'", '{\\"pin\\":\\"4321\\"}', "PIN=4321",
                        "userPassphrase='a b c'"]
        for s in masked_cases:
            m, _ = er.mask_text(s, KEY)
            self.assertIn("[MASCARADO:segredo]", m, s)
            self.assertTrue(er.find_secrets(s), s)
        for s in ["spin=3", "pinned=true", "otpEnabled=true", "spinner: 1", "cvvRequired=false", "opinion=ok"]:
            m, _ = er.mask_text(s, KEY)
            self.assertEqual(m, s, s)

    def test_chaves_camel_case_de_cartao(self):
        """CORRIGIDO em e565020 — era o defeito (QA-D16-3): chaves camelCase com as palavras curtas não são mascaradas: `"cardCvv":"123"`,
        `"cardPin"`, `"pinCode"`, `"otpCode"` (cvv é dado de cartão; PCI). `card_pin`/`x-otp` funcionam."""
        for s in ['"cardCvv":"123"', '"cardPin":"1111"', '"pinCode":"4321"', '"otpCode":"998877"']:
            m, _ = er.mask_text(s, KEY)
            self.assertIn("[MASCARADO:segredo]", m, s)


class Q07Revalidacao(unittest.TestCase):
    """Revalidação após e565020: resumo de painel/alerta mascarado, entradas patológicas de 1 MB lineares, camelCase
    e falsos positivos, efeitos colaterais declarados (`"auth":{...}` por campo; `mapPin` mascarado)."""
    PII = ("ana.ficticia@exemplo.com.br", "529.982.247-25", "hunter2-inventado", "tok_live_inventado")

    def test_resumo_de_painel_e_alerta_mascarado(self):
        h.DASHBOARD["panels"].append({"id": 97, "type": "stat", "title": "Pedidos de ana.ficticia@exemplo.com.br senha=hunter2-inventado",
                                      "targets": [{"expr": 'sum(rate(x{email="ana.ficticia@exemplo.com.br"}[5m]))'}]})
        h.Prod.rules["r-pii"] = {"uid": "r-pii", "title": "Falha cpf 529.982.247-25 password=hunter2-inventado", "condition": "C",
                                 "for": "1m", "labels": {}, "annotations": {}, "data": [{"model": {"expr": 'up{token="tok_live_inventado"}'}}]}
        for link in ("http://localhost:3001/d/checkout-saga/x?viewPanel=97&from=now-1h&to=now",
                     "http://localhost:3001/alerting/grafana/r-pii/view"):
            st, d, _ = h.draft("operacao", link=link)
            self.assertEqual(st, 201, d)
            self.assertEqual([x for x in self.PII if x in json.dumps(d, ensure_ascii=False)], [], link)

    def test_entradas_patologicas_1mb(self):
        for name, text in (("barras", "\\" * 1_000_000), ("pontos", "." * 1_000_000), ("1.1.", "1.1." * 250_000),
                           ("dominio", "a" + ".sub-dominio" * 85_000), ("Address[", "Address[" * 125_000),
                           ("aspas escapadas", '\\"' * 500_000), ("customerName", 'customerName=\\"' * 60_000)):
            t0 = time.monotonic()
            er.mask_text(text, KEY)
            self.assertLess(time.monotonic() - t0, 1.0, name)

    def test_camel_case_e_falsos_positivos(self):
        for s in ['"pwd":"abc"', "userPwd=abc", "DB_PWD=abc", '"auth":"Basic dXNlcjpwYXNz"', "x-auth: abc", "cvv_number=1"]:
            self.assertIn("[MASCARADO:segredo]", er.mask_text(s, KEY)[0], s)
        for s in ['"author":"ana"', "oauth2Client=web", "PWD=/home/app", "authorId=7", "authType=BASIC", '"pinCount":3',
                  '"authenticated":true', '"otpauth":"x"']:
            self.assertEqual(er.mask_text(s, KEY)[0], s, s)

    def test_efeitos_colaterais_declarados(self):
        m, _ = er.mask_text('{"auth":{"user":"ana","password":"hunter2-inventado","token":"tok_live_inventado"}}', KEY)
        json.loads(m)
        self.assertNotIn("hunter2-inventado", m)
        self.assertNotIn("tok_live_inventado", m)
        self.assertEqual(er.mask_text("mapPin=1", KEY)[0], "mapPin=[MASCARADO:segredo]")   # a mais: aceitável


class Q05CA13Real(unittest.TestCase):
    """Item 5 do QA: CLI do gitflow e align_memory num clone temporário com bugs/ não rastreado."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="squad-d16-ca13-")).resolve()
        cls.origin = cls.tmp / "origin.git"
        cls.clone = cls.tmp / "clone"
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        run = lambda *a, cwd=None: subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True)  # noqa: E731
        run("git", "clone", "-q", "--no-checkout", str(REPO), str(cls.clone))
        run("git", "checkout", "-q", "-b", "develop", head, cwd=cls.clone)
        # o working tree do worktree pode ter arquivos novos do QA não commitados: o clone usa o HEAD commitado +
        # o gitflow.py atual (o que está sob teste)
        shutil.copy2(REPO / "tools/squad/gitflow.py", cls.clone / "tools/squad/gitflow.py")
        if (REPO / "tools/squad/product.py").exists():
            shutil.copy2(REPO / "tools/squad/product.py", cls.clone / "tools/squad/product.py")
        # D23 (F2a §5.1): `feature-start <código> --demand <id>` exige o `task` do humano no log e o código resolvido
        # igual ao informado. Semeia o `task` da demanda do bug com o código gravado D99 (código gravado vale, §4.4).
        with (cls.clone / "docs/squad/memory/decisions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "aaaaaaaaaaa1", "ts": "2026-09-24T00:00:00+00:00", "agent": "humano",
                                "type": "task", "title": "Demanda: bug de teste", "kind": "produto",
                                "code": "D99", "code_prefix": "D"}, ensure_ascii=False) + "\n")
        run("git", "config", "user.email", "qa@squad.local", cwd=cls.clone)
        run("git", "config", "user.name", "qa", cwd=cls.clone)
        run("git", "add", "-A", cwd=cls.clone)
        run("git", "commit", "-q", "--allow-empty", "-m", "base do teste", cwd=cls.clone)
        run("git", "init", "-q", "--bare", str(cls.origin))
        run("git", "remote", "set-url", "origin", str(cls.origin), cwd=cls.clone)   # NUNCA o repositório real
        run("git", "push", "-q", "origin", "develop", cwd=cls.clone)
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith("SQUAD_")}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def git(self, *a, cwd=None):
        return subprocess.run(["git", *a], cwd=cwd or self.clone, capture_output=True, text=True).stdout

    def make_bug(self, kind, demand):
        folder = self.clone / f"docs/squad/{kind}/bugs/{demand}"
        (folder / "evidencias").mkdir(parents=True)
        (folder / "bug.json").write_text(json.dumps({"demand": demand, "kind": kind}))
        (folder / "evidencias/01-erro.log").write_text("falha\n")
        with (self.clone / f"docs/squad/{kind}/bugs/index.jsonl").open("a") as f:
            f.write(json.dumps({"demand": demand}) + "\n")

    def test_feature_start_e_align_memory(self):
        self.assertEqual(self.git("remote", "get-url", "origin").strip(), str(self.origin))
        self.make_bug("produto", "aaaaaaaaaaa1")
        self.assertIn("?? docs/squad/produto/", self.git("status", "--porcelain"))      # colapsado sem -uall
        p = subprocess.run(["python3", "tools/squad/gitflow.py", "feature-start", "D99", "bug-teste", "--demand",
                            "aaaaaaaaaaa1"], cwd=self.clone, capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "feature/D99-bug-teste")
        # só o log da squad (o `decision` da branch criada) pode estar pendente: é memória viva (STATE)
        dirty = [l[3:] for l in self.git("status", "--porcelain", "-uall").splitlines()]
        self.assertEqual([d for d in dirty if not d.startswith("docs/squad/memory/")], [])
        on_origin = self.git("ls-tree", "-r", "--name-only", "develop", cwd=self.origin).split()
        self.assertIn("docs/squad/produto/bugs/aaaaaaaaaaa1/bug.json", on_origin)
        self.assertIn("docs/squad/produto/bugs/aaaaaaaaaaa1/evidencias/01-erro.log", on_origin)
        msg = self.git("log", "-1", "--format=%s", "develop", "--", "docs/squad/produto/bugs").strip()
        self.assertEqual(msg, "Sincronização da memória da squad")
        # align_memory sem pasta operacao/bugs em lugar nenhum (o `checkout develop -- <pasta>` falha e é tolerado)
        self.git("switch", "-q", "develop")
        code = "import sys; sys.path.insert(0, 'tools/squad'); import gitflow; gitflow.align_memory('feature/D99-bug-teste')"
        p = subprocess.run(["python3", "-c", code], cwd=self.clone, capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        # bug novo de operação criado na develop (não rastreado) → snapshot → align_memory leva à feature
        self.make_bug("operacao", "bbbbbbbbbbb2")
        code2 = "import sys; sys.path.insert(0, 'tools/squad'); import gitflow; gitflow.snapshot_state()"
        p = subprocess.run(["python3", "-c", code2], cwd=self.clone, capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.git("status", "--porcelain", "-uall").strip(), "")   # bug + log commitados
        p = subprocess.run(["python3", "-c", code], cwd=self.clone, capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        feat = self.git("ls-tree", "-r", "--name-only", "feature/D99-bug-teste", cwd=self.origin).split()
        self.assertIn("docs/squad/operacao/bugs/bbbbbbbbbbb2/evidencias/01-erro.log", feat)
        self.assertIn("docs/squad/produto/bugs/aaaaaaaaaaa1/bug.json", feat)
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD").strip(), "develop")


def tearDownModule():
    h.tearDownModule()


if __name__ == "__main__":
    unittest.main(verbosity=2)
