#!/usr/bin/env python3
"""Regras únicas de evidência (D16, ADR-019 §8; reutilizável pela D12/ADR-015). Somente stdlib, autossuficiente.

- Tipos permitidos por extensão **e** assinatura (imagem PNG/JPEG/WEBP; log .log/.txt/.json em UTF-8 sem NUL).
- Limites por arquivo, por envio, por bug e global.
- Máscara de logs: segredos, PII (e-mail, CPF, CNPJ, telefone, cartão Luhn, IP público), **endereço de entrega**
  (`shippingAddress` inteiro, CEP, nome do destinatário — ressalva 1 do G1) e pseudônimo estável de `customerId`
  por **HMAC-SHA256 com chave local** em `.squad/` (fora do git — ressalva 2).
- Bloqueio de segredo em texto livre (título/descrição) — regra do ADR-015, aqui sem depender dele.
- Remoção de metadados de imagem (PNG tEXt/iTXt/zTXt/eXIf/tIME; JPEG APP1–APP15/COM; WEBP EXIF/XMP) sem decodificar.
- Nome de arquivo sanitizado `[a-z0-9._-]`, ≤ 80 caracteres, sem caminho.

Nada aqui acessa rede; a única escrita em disco é a chave HMAC (`key_path`).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import re
import secrets
import struct

# ---------------------------------------------------------------- tipos e limites (§8.1)
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
LOG_EXT = {".log": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
           ".json": "text/plain; charset=utf-8"}   # .json servido como texto: nunca interpretado pelo navegador
MAX_IMAGE = 5 * 1024 * 1024
MAX_LOG = 1 * 1024 * 1024
MAX_FILES_PER_SUBMIT = 10
MAX_SUBMIT = 15 * 1024 * 1024
MAX_PER_BUG = 30 * 1024 * 1024
MAX_GLOBAL = 200 * 1024 * 1024
MAX_BODY = 22 * 1024 * 1024     # Content-Length das rotas de bug (base64 ≈ ×1,37 de 15 MB)
MAX_NAME = 80


class EvidenceError(Exception):
    """Erro de validação com status HTTP e código estável (mensagem em português)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def payload(self) -> dict:
        return {"error": self.message, "code": self.code}


def sanitize_name(name: str, max_len: int = MAX_NAME) -> str:
    """Só o nome-base, minúsculo, `[a-z0-9._-]`, sem pontos iniciais, ≤ max_len (preservando a extensão)."""
    base = re.split(r"[\\/]", str(name or ""))[-1].strip().lower()
    base = re.sub(r"[^a-z0-9._-]+", "-", base)
    base = re.sub(r"-{2,}", "-", base).lstrip(".-") or "arquivo"
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    ext = ("." + ext) if ext else ""
    stem = stem.strip("-.") or "arquivo"
    return stem[: max(1, max_len - len(ext))] + ext


def extension(name: str) -> str:
    return os.path.splitext(name.lower())[1]


def image_kind(data: bytes) -> str | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


EXT_KIND = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


def classify(name: str, data: bytes, generated: bool = False) -> dict:
    """Valida extensão + assinatura + limites. Devolve {type, mime, ext}. Levanta EvidenceError."""
    ext = extension(name)
    if ext in IMAGE_EXT:
        kind = image_kind(data)
        if kind != EXT_KIND[ext]:
            raise EvidenceError(415, "tipo_nao_permitido",
                                f"{name}: o conteúdo não é uma imagem {ext[1:].upper()} válida (assinatura não confere)")
        if len(data) > MAX_IMAGE:
            raise EvidenceError(413, "arquivo_grande", f"{name}: imagem acima de 5 MB")
        return {"type": "image", "mime": IMAGE_EXT[ext], "ext": ext}
    if ext in LOG_EXT:
        if image_kind(data) or data[:4] in (b"%PDF", b"PK\x03\x04", b"GIF8"):
            raise EvidenceError(415, "tipo_nao_permitido", f"{name}: arquivo binário com extensão de log")
        if b"\x00" in data:
            raise EvidenceError(415, "tipo_nao_permitido", f"{name}: log com byte NUL (binário)")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise EvidenceError(415, "tipo_nao_permitido", f"{name}: log não é UTF-8 válido") from None
        if ext == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError:
                raise EvidenceError(415, "tipo_nao_permitido", f"{name}: JSON inválido") from None
        if len(data) > MAX_LOG and not generated:
            raise EvidenceError(413, "arquivo_grande", f"{name}: log acima de 1 MB")
        return {"type": "log", "mime": LOG_EXT[ext], "ext": ext}
    raise EvidenceError(415, "tipo_nao_permitido",
                        f"{name}: tipo não permitido (aceitos: .png .jpg .jpeg .webp .log .txt .json)")


def check_submission(sizes: list[int], bug_total: int = 0, global_total: int = 0):
    if len(sizes) > MAX_FILES_PER_SUBMIT:
        raise EvidenceError(413, "arquivos_demais", f"no máximo {MAX_FILES_PER_SUBMIT} arquivos por envio")
    if sum(sizes) > MAX_SUBMIT:
        raise EvidenceError(413, "envio_grande", "envio acima de 15 MB somados")
    if bug_total + sum(sizes) > MAX_PER_BUG:
        raise EvidenceError(413, "bug_cheio", "o bug passaria de 30 MB de evidências")
    if global_total + sum(sizes) > MAX_GLOBAL:
        raise EvidenceError(413, "armazenamento_de_bugs_cheio",
                            "armazenamento de bugs acima de 200 MB: migre ou limpe antes de registrar novos")


def truncate_log(text: str, limit: int = MAX_LOG) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    cut = raw[: limit - 64].decode("utf-8", errors="ignore")
    cut = cut[: cut.rfind("\n") + 1] or cut
    return cut + "[TRUNCADO: log gerado passou de 1 MB]\n", True


# ---------------------------------------------------------------- evidência do ambiente de teste (§5)
TEST_PROJECT = "checkout-teste"
PROD_PORTS = {5432, 29092, 4317, 4318, 16686, 9090, 3000, 3001, 8080, 8081, 8082, 8083, 8084, 8090, 7070}
TEST_PORTS = {p + 10000 for p in PROD_PORTS} | {26686, 13001, 19090} | set(range(18080, 18091))
_HOSTPORT = re.compile(r"(?:localhost|127\.0\.0\.1):(\d{5})\b")


def looks_like_test_env(text: str) -> bool:
    if TEST_PROJECT in text:
        return True
    return any(int(m.group(1)) in TEST_PORTS for m in _HOSTPORT.finditer(text))


# ---------------------------------------------------------------- segredos e PII (§8.2)
SECRET_PATTERNS = [
    ("chave_privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)),
    ("jwt", re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+")),
    ("authorization", re.compile(r"(?i)(authorization\\?\"?\s*[:=]\s*\\?\"?)[A-Za-z]+ [^\s\"'\\,}]+")),
    ("github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("github_pat", re.compile(r"\bgithub_pat_\w+")),
    ("aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("sk", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("slack", re.compile(r"\bxox[bap]-[\w-]+")),
    ("url_credencial", re.compile(r"(?<=://)(?!\[MASCARADO)[^/\s:@\"']+:[^/\s@\"']+(?=@)")),
    ("cookie", re.compile(r"(?i)((?<![\w-])(?:set-)?cookie\\?\"?\s*[=:]\s*\\?\"?)(?!\[MASCARADO)([^\s\"\\][^\r\n\"\\]*)")),
    # chaves compostas (accessToken, bearer_token, x-api-key, client_secret...): sem \b antes da palavra-chave
    ("chave_valor", re.compile(
        r"(?i)(\\?\"?(?<![\w.-])[\w.-]{0,80}?(?:password|passwd|senha|secret|token|api[_-]?key|access[_-]?key|"
        r"credential)[\w.-]{0,80}\\?\"?"
        r"\s*[=:]\s*\\?\"?)(?!\[MASCARADO)([^\s\"'\\,;&}]+)")),
]
SECRET_MASK = "[MASCARADO:segredo]"


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _cpf_ok(d: str) -> bool:
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


ADDRESS_KEYS = r"(?:shippingAddress|shipping_address|billingAddress|endereco|enderecoEntrega|address)"
NAME_KEYS = r"(?:customerName|recipient|recipientName|destinatario|fullName|nomeCompleto|nome)"
ZIP_KEYS = r"(?:zipCode|zip_code|zip|cep|postalCode|postal_code)"
STREET_KEYS = r"(?:street|logradouro|rua|complement|complemento)"
Q = r"\\?\""   # aspas, possivelmente escapadas (JSON dentro de mensagem de log)

PII_PATTERNS = [
    # endereço de entrega inteiro (JSON, JSON escapado e toString Java) — ressalva 1
    ("endereco", re.compile("(" + Q + ADDRESS_KEYS + Q + r"\s*:\s*)\{[^{}]*\}")),
    ("endereco", re.compile(r"(\b" + ADDRESS_KEYS + r"\s*=\s*)\w*[\[{(][^\]})]*[\]})]")),
    # toString de record/classe sem chave antes: Address[street=..., number=...], ShippingAddress{...}
    ("endereco", re.compile(r"((?<![\w$])[\w$.]*[Aa]ddress)[\[{](?=[^\]{}\n]*=)[^\]{}\n]*[\]}]")),
    ("endereco", re.compile(r"((?<![\w.])" + STREET_KEYS + r"=)[^,\]})\n]+")),
    ("cep", re.compile(r"((?<![\w.])" + ZIP_KEYS + r"=)[\d.\s-]{5,10}(?=[,\]})\s]|$)")),
    ("nome", re.compile(r"((?<![\w.])" + NAME_KEYS + r"=)[^,\]})\n]+")),
    ("endereco", re.compile("(" + Q + STREET_KEYS + Q + r"\s*:\s*)" + Q + r"[^\"\\]*" + Q)),
    ("cep", re.compile("(" + Q + ZIP_KEYS + Q + r"\s*:\s*)" + Q + r"?[\d.\s-]{5,10}" + Q + r"?")),
    ("nome", re.compile("(" + Q + NAME_KEYS + Q + r"\s*:\s*)" + Q + r"[^\"\\]*" + Q)),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("cnpj", re.compile(r"(?<![\w./-])\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?![\w-])")),
    ("cpf", re.compile(r"(?<![\w.-])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\w-])")),
    # separadores opcionais (529982247-25, 529 982 247 25, 52998224725): só com dígito verificador válido
    ("cpf", re.compile(r"(?<![\w.-])\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}(?![\w-])"),
     lambda v: _cpf_ok(re.sub(r"\D", "", v))),
    ("cartao", re.compile(r"(?<![\w-])[3-6]\d{3}(?:[ -]?\d){9,15}(?![\w-])"),
     lambda v: 13 <= len(re.sub(r"\D", "", v)) <= 19 and _luhn(re.sub(r"\D", "", v))),
    ("cep", re.compile(r"(?<![\w-])\d{5}-\d{3}(?![\w-])")),
    ("telefone", re.compile(r"(?:\+55\s?)?\(\d{2}\)\s?9?\d{4}-?\d{4}(?!\d)|\+55\s?\d{2}\s?9?\d{4}-?\d{4}(?!\d)")),
    ("ip", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"), _public_ip),
    ("ip", re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])"), _public_ip),
]
CUSTOMER_RE = [re.compile("(" + Q + r"customerId" + Q + r"\s*:\s*" + Q + r")([^\"\\]+)(" + Q + ")"),
               re.compile(r"(\bcustomerId=)([^&\s\"',;}\]]+)()")]
PSEUDO_RE = re.compile(r"^cust-[0-9a-f]{8}$")


def key_path(data_root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(data_root) / ".squad/bug-pseudonym.key"


def load_key(data_root: pathlib.Path) -> bytes:
    """Chave HMAC local (32 bytes), criada uma vez em `.squad/` (ignorado pelo git) com permissão 600."""
    p = key_path(data_root)
    try:
        k = p.read_bytes()
        if len(k) >= 32:
            return k
    except OSError:
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    k = secrets.token_bytes(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(k)
    return k


def pseudonym(value: str, key: bytes) -> str:
    return "cust-" + hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]


def mask_text(text: str, key: bytes) -> tuple[str, dict]:
    """Aplica a máscara (idempotente). Devolve (texto, contagens por categoria e por tipo — nunca o valor)."""
    counts = {"secret": 0, "pii": 0, "endereco": 0, "pseudonimo": 0}
    by_type: dict[str, int] = {}

    def bump(cat: str, typ: str):
        counts[cat] += 1
        by_type[typ] = by_type.get(typ, 0) + 1

    for typ, rx in SECRET_PATTERNS:
        def rep(m, typ=typ):
            bump("secret", typ)
            if typ in ("authorization", "cookie", "chave_valor"):
                return m.group(1) + SECRET_MASK
            return SECRET_MASK
        text = rx.sub(rep, text)
    for item in PII_PATTERNS:
        typ, rx = item[0], item[1]
        ok = item[2] if len(item) > 2 else None
        cat = "endereco" if typ in ("endereco", "cep", "nome") else "pii"
        label = f"[MASCARADO:{typ}]"

        def rep(m, typ=typ, ok=ok, cat=cat, label=label):
            whole = m.group(0)
            key = m.group(1) if m.re.groups else ""
            if "[MASCARADO:" in whole[len(key):] or (ok and not ok(whole)):
                return whole
            bump(cat, typ)
            if not key:
                return label
            if '\\"' in key:          # JSON escapado dentro de uma mensagem de log
                return key + '\\"' + label + '\\"'
            return key + ('"' + label + '"' if '"' in key else label)
        text = rx.sub(rep, text)
    for rx in CUSTOMER_RE:
        def rep(m):
            v = m.group(2)
            if PSEUDO_RE.match(v) or v.startswith("[MASCARADO"):
                return m.group(0)
            bump("pseudonimo", "customerId")
            return m.group(1) + pseudonym(v, key) + m.group(3)
        text = rx.sub(rep, text)
    return text, {**counts, "byType": by_type}


def find_secrets(text: str) -> list[str]:
    """Tipos de segredo presentes num texto livre (título/descrição): se houver, a criação é bloqueada (ADR-015)."""
    return sorted({typ for typ, rx in SECRET_PATTERNS if rx.search(text or "")})


# ---------------------------------------------------------------- metadados de imagem (§8.3)
PNG_DROP = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"}


def _strip_png(data: bytes) -> tuple[bytes, int]:
    out, pos, removed = [data[:8]], 8, 0
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 12 + length
        if end > len(data):
            raise EvidenceError(415, "tipo_nao_permitido", "PNG truncado")
        if ctype in PNG_DROP:
            removed += 1
        else:
            out.append(data[pos:end])
        pos = end
        if ctype == b"IEND":
            break
    else:
        raise EvidenceError(415, "tipo_nao_permitido", "PNG sem IEND")
    return b"".join(out), removed


def _strip_jpeg(data: bytes) -> tuple[bytes, int]:
    out, pos, removed = [data[:2]], 2, 0
    while pos < len(data):
        if data[pos] != 0xFF:
            raise EvidenceError(415, "tipo_nao_permitido", "JPEG malformado")
        marker = data[pos + 1]
        if marker == 0xFF:          # preenchimento
            pos += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD8)):   # marcadores sem comprimento
            out.append(data[pos:pos + 2])
            pos += 2
            continue
        if marker == 0xD9:
            out.append(data[pos:pos + 2])
            break
        (length,) = struct.unpack(">H", data[pos + 2:pos + 4])
        seg_end = pos + 2 + length
        if marker == 0xDA:          # SOS: o resto é o fluxo comprimido
            out.append(data[pos:])
            break
        if 0xE1 <= marker <= 0xEF or marker == 0xFE:
            removed += 1
        else:
            out.append(data[pos:seg_end])
        pos = seg_end
    return b"".join(out), removed


def _strip_webp(data: bytes) -> tuple[bytes, int]:
    chunks, pos, removed = [], 12, 0
    while pos + 8 <= len(data):
        ctype = data[pos:pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        end = pos + 8 + size + (size & 1)
        if ctype in (b"EXIF", b"XMP "):
            removed += 1
        else:
            chunks.append(bytearray(data[pos:end]))
        pos = end
    for c in chunks:
        if c[:4] == b"VP8X" and len(c) >= 9:
            c[8] &= ~0x0C & 0xFF      # limpa as flags EXIF (0x08) e XMP (0x04)
    body = b"WEBP" + b"".join(bytes(c) for c in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body, removed


def strip_image_metadata(data: bytes) -> tuple[bytes, int]:
    kind = image_kind(data)
    try:
        if kind == "png":
            return _strip_png(data)
        if kind == "jpeg":
            return _strip_jpeg(data)
        if kind == "webp":
            return _strip_webp(data)
    except (struct.error, IndexError):
        raise EvidenceError(415, "tipo_nao_permitido", "imagem malformada") from None
    raise EvidenceError(415, "tipo_nao_permitido", "imagem de tipo não permitido")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
