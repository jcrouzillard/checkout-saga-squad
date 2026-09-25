#!/usr/bin/env python3
"""Resolvedor de produto e códigos de demanda congelados (D23 · F2a, ADR-024 §4.2/§4.4.1/§4.10, errata §11).

Contrato: docs/contracts/f2a-resolvedor-de-produto.md. Só stdlib; nenhum efeito colateral na importação.

  python3 tools/squad/product.py resolve [--product <id>] [--json]      caminhos resolvidos
  python3 tools/squad/product.py codes [--check] [--json] [--log <arq>] id → código (congelado/gravado/posicional)
  python3 tools/squad/product.py freeze-codes --until <id> [--log <arq>] --out <arq>
                                                                         gera a tabela congelada (só LÊ o log)

Precedência do produto: argumento (--product) > $SQUAD_PRODUCT > checkout-saga.
Precedência dos caminhos: $SQUAD_LOG > $SQUAD_ROOT_DATA > raiz do repositório; transcrições: $SQUAD_TRANSCRIPTS > slug.
Sem nenhuma variável definida, todo caminho é o de hoje (CA-1). CLIs saem com código 2 em ProductError.
"""
import argparse
import dataclasses
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone

DEFAULT_PRODUCT = "checkout-saga"
PLATFORM_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRODUCTS_DIR = "docs/squad/products"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
PREFIX_RE = re.compile(r"^[A-Z]$")
CODE_RE = re.compile(r"^([A-Z])([1-9][0-9]*)$")
# Produto implícito sem cadastro: o comportamento de hoje não depende do arquivo (§2).
BUILTIN = {DEFAULT_PRODUCT: {"name": "Checkout Saga", "code_prefix": "D"}}
LOCK_TIMEOUT_S = 5.0
TRANSCRIPT_DIRS_TTL_S = 30.0
CANONICAL_LOG = "docs/squad/memory/decisions.jsonl"
# D26 §3.1: `[executors]` ausente = os dois executores permitidos e semente `claude`
EXECUTOR_NAMES = ("claude", "codex")
DEFAULT_EXECUTORS = {"allowed": ["claude", "codex"], "seed": {"runner": "claude", "model": None}}

# Divergências conhecidas (contrato §4.3): código citado em documentos/branches/pareceres ≠ código do painel.
F2A_ALIASES = [
    {"alias": "D7", "id": "e31bdfb73679", "code": "D8", "sources": [
        "docs/contracts/ui-cancelar-demanda.md", "tests/ui/checklist-cancelar-d7.md",
        "feature/D7-cancelar-demanda-na-validacao", "docs/squad/gates/G1-D7.json", "docs/squad/gates/G2-D7.json",
        "docs/squad/gates/G2-D7-2.json", "docs/squad/gates/G3-D7.json", "docs/adr/024-plataforma-multiproduto.md",
        "docs/contracts/plataforma-multiproduto-mapa.md"]},
    {"alias": "D8", "id": "349e5b1bf818", "code": "D7", "sources": [
        "docs/adr/011-merge-com-revisao-humana.md", "docs/contracts/entrega-por-pr.md",
        "tests/ui/checklist-entrega-por-pr-d8.md", "feature/D8-entrega-por-pr-com-revisao-humana",
        "docs/squad/gates/G1-D8.json", "docs/squad/gates/G2-D8.json", "docs/squad/gates/G2-D8-2.json",
        "docs/squad/gates/G3-D8.json", "docs/adr/024-plataforma-multiproduto.md",
        "docs/contracts/plataforma-multiproduto-mapa.md"]},
    {"alias": "D9", "id": "174084ec85d0", "code": "D10", "sources": [
        "docs/adr/012-modelo-no-log-da-squad.md", "docs/contracts/ui-modelo-por-agente.md",
        "feature/D9-modelo-usado-na-demanda", "docs/squad/gates/G1-D9.json", "docs/squad/gates/G2-D9.json",
        "docs/squad/gates/G3-D9.json", "docs/adr/024-plataforma-multiproduto.md",
        "docs/contracts/plataforma-multiproduto-mapa.md"]},
    {"alias": "D10", "id": "f2324e0f25de", "code": "D9", "sources": [
        "docs/contracts/d10-alinhamento.md", "feature/D10-alinhar-documentacao-codigo-infra",
        "docs/squad/gates/G1-D10.json", "docs/squad/gates/G2-D10.json", "docs/squad/gates/G3-D10.json",
        "docs/adr/024-plataforma-multiproduto.md", "docs/contracts/plataforma-multiproduto-mapa.md"]},
]


class ProductError(Exception):
    """Cadastro ausente/inválido, id desconhecido, código indevido. CLIs saem com código 2."""


class LockTimeout(ProductError):
    """Trava `codes.lock` não obtida em LOCK_TIMEOUT_S: nada foi gravado (servidor 503, log.py código 1)."""


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    code_prefix: str
    platform_root: pathlib.Path
    repo_root: pathlib.Path
    data_root: pathlib.Path
    log: pathlib.Path
    memory_dir: pathlib.Path
    gates_dir: pathlib.Path
    handoffs_dir: pathlib.Path
    inbox_dir: pathlib.Path
    runs_dir: pathlib.Path
    locks_dir: pathlib.Path
    config_dir: pathlib.Path
    explicit: bool
    # D26 (ADR-027, contrato executor-e-modelo-por-agente §3.1): guarda/semente dos executores e runtime por máquina
    executors: dict = dataclasses.field(default_factory=lambda: dict(DEFAULT_EXECUTORS))
    runtime_dir: pathlib.Path | None = None

    def with_log(self, log) -> "Product":
        """Mesmo produto com outro log (ex.: `server.LOG` trocado em teste); memory_dir acompanha o log."""
        log = pathlib.Path(log)
        return dataclasses.replace(self, log=log, memory_dir=log.parent)

    @property
    def memory_in_repo(self) -> bool:
        """Log = o do repositório (o caso de hoje): só então as operações de memória no git agem (§5.1)."""
        return same_path(self.log, self.repo_root / CANONICAL_LOG)


def same_path(a, b) -> bool:
    try:
        return pathlib.Path(a).resolve() == pathlib.Path(b).resolve()
    except OSError:
        return pathlib.Path(a).absolute() == pathlib.Path(b).absolute()


# ============================================================== cadastro
_toml_cache: dict = {}


def _load_toml(path: pathlib.Path, pid: str) -> dict:
    try:
        st = path.stat()
        key = (str(path), pid, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key and key in _toml_cache:
        return _toml_cache[key]
    meta = _parse_toml(path, pid)
    if key:
        _toml_cache.clear()
        _toml_cache[key] = meta
    return meta


def _parse_toml(path: pathlib.Path, pid: str) -> dict:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ProductError(f"{path}: cadastro ilegível ({e})") from e
    if data.get("schema") != 1:
        raise ProductError(f"{path}: campo `schema` deve ser 1")
    prod = data.get("product")
    if not isinstance(prod, dict):
        raise ProductError(f"{path}: tabela [product] obrigatória")
    for field in ("id", "name", "code_prefix"):
        if not isinstance(prod.get(field), str) or not prod[field].strip():
            raise ProductError(f"{path}: campo `product.{field}` obrigatório (texto)")
    if prod["id"] != pid:
        raise ProductError(f"{path}: campo `product.id` ({prod['id']}) difere da pasta ({pid})")
    if not PREFIX_RE.match(prod["code_prefix"]):
        raise ProductError(f"{path}: campo `product.code_prefix` inválido ({prod['code_prefix']!r}; esperado ^[A-Z]$)")
    _parse_executors(path, data.get("executors"))   # D26: [executors] inválido também é cadastro inválido
    return {"name": prod["name"], "code_prefix": prod["code_prefix"]}   # demais tabelas: aceitas e ignoradas (F2b)


def load_executors(path: pathlib.Path) -> dict:
    """D26 §3.1: `[executors]` do product.toml (ausente/arquivo ausente = DEFAULT_EXECUTORS)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return _parse_executors(path, None)
    except tomllib.TOMLDecodeError as e:
        raise ProductError(f"{path}: cadastro ilegível ({e})") from e
    return _parse_executors(path, data.get("executors"))


def _parse_executors(path: pathlib.Path, table) -> dict:
    """D26 §3.1: `[executors] allowed = [...]`, `seed = {runner, model?}`; ausente = DEFAULT_EXECUTORS."""
    if table is None:
        return {"allowed": list(DEFAULT_EXECUTORS["allowed"]), "seed": dict(DEFAULT_EXECUTORS["seed"])}
    if not isinstance(table, dict):
        raise ProductError(f"{path}: [executors] deve ser uma tabela")
    allowed = table.get("allowed", list(DEFAULT_EXECUTORS["allowed"]))
    if (not isinstance(allowed, list) or not allowed
            or any(not isinstance(x, str) or x not in EXECUTOR_NAMES for x in allowed)):
        raise ProductError(f"{path}: executors.allowed inválido (esperado subconjunto não vazio de {list(EXECUTOR_NAMES)})")
    seed = table.get("seed", {"runner": allowed[0]})
    if not isinstance(seed, dict) or seed.get("runner") not in allowed:
        raise ProductError(f"{path}: executors.seed.runner deve estar em executors.allowed")
    model = seed.get("model")
    if model is not None and not isinstance(model, str):
        raise ProductError(f"{path}: executors.seed.model deve ser texto")
    return {"allowed": sorted(set(allowed), key=allowed.index), "seed": {"runner": seed["runner"], "model": model or None}}


def resolve(product: str | None = None) -> Product:
    env_product = os.environ.get("SQUAD_PRODUCT") or None
    chosen = product or env_product
    explicit = bool(chosen)
    pid = chosen or DEFAULT_PRODUCT
    if not ID_RE.match(pid):
        raise ProductError(f"id de produto inválido: {pid!r} (esperado ^[a-z][a-z0-9-]{{1,40}}$)")
    config_dir = PLATFORM_ROOT / PRODUCTS_DIR / pid
    toml = config_dir / "product.toml"
    if toml.exists():
        meta = _load_toml(toml, pid)
    elif not explicit and pid in BUILTIN:
        meta = BUILTIN[pid]
    else:
        raise ProductError(f"produto desconhecido: {pid} (sem {toml})")
    repo_root = PLATFORM_ROOT                       # F2a: a mesma árvore de onde a squad roda (como hoje)
    data_root = pathlib.Path(os.environ.get("SQUAD_ROOT_DATA") or repo_root).resolve()
    log = pathlib.Path(os.environ.get("SQUAD_LOG") or data_root / CANONICAL_LOG)
    return Product(id=pid, name=meta["name"], code_prefix=meta["code_prefix"], platform_root=PLATFORM_ROOT,
                   repo_root=repo_root, data_root=data_root, log=log, memory_dir=log.parent,
                   gates_dir=data_root / "docs/squad/gates", handoffs_dir=data_root / "docs/squad/memory/handoffs",
                   inbox_dir=data_root / "docs/squad/inbox", runs_dir=data_root / ".squad/runs",
                   locks_dir=data_root / ".squad/locks", config_dir=config_dir, explicit=explicit,
                   executors=load_executors(toml),
                   runtime_dir=data_root / ".squad")   # F3: $SQUAD_HOME/products/<id>/runtime (fora do escopo)


# ============================================================== códigos
def read_rows(log: pathlib.Path) -> list[dict]:
    try:
        text = pathlib.Path(log).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    rows = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def human_tasks(rows) -> list[dict]:
    return [e for e in rows if e.get("type") == "task" and e.get("agent") == "humano" and e.get("id")]


def positional_codes(rows, prefix: str = "D") -> dict[str, str]:
    """Regra de hoje (alerts.demand_codes da develop): n-ésimo `task` do humano no log = prefixo + n."""
    return {e["id"]: f"{prefix}{n}" for n, e in enumerate(human_tasks(rows), 1)}


_codes_cache: dict = {}


def frozen_table(p: Product | None = None) -> dict:
    """codes.json do produto (cache por mtime/tamanho); {} se ausente, ilegível ou de outro prefixo."""
    p = p or resolve()
    path = p.config_dir / "codes.json"
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _codes_cache.get("key") != key:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        _codes_cache.update(key=key, data=data if isinstance(data, dict) else {})
    data = _codes_cache["data"]
    return data if data.get("prefix") == p.code_prefix else {}


def _num(code: str) -> int:
    m = CODE_RE.match(code or "")
    return int(m.group(2)) if m else 0


def _valid(code, prefix: str) -> bool:
    m = CODE_RE.match(code) if isinstance(code, str) else None
    return bool(m) and m.group(1) == prefix


def _compute(rows, p: Product) -> tuple[dict[str, str], list[dict]]:
    prefix = p.code_prefix
    frozen = frozen_table(p).get("codes") or {}
    tasks = human_tasks(rows)
    owner: dict[str, str] = {}                       # código → id que o detém
    for t in tasks:                                  # congelado vale primeiro, sempre
        if t["id"] in frozen:
            owner.setdefault(frozen[t["id"]], t["id"])
    conflicts = []
    accepted: dict[str, str] = {}                    # id → código gravado aceito
    for t in tasks:
        c = t.get("code")
        if t["id"] in frozen or not _valid(c, prefix):
            continue
        if c in owner and owner[c] != t["id"]:
            conflicts.append({"code": c, "kept": owner[c], "dropped": t["id"]})
            continue
        owner.setdefault(c, t["id"])
        accepted[t["id"]] = c
    taken = set(owner)
    out, last = {}, 0
    for t in tasks:
        if t["id"] in out:
            continue                                 # id repetido no log: vale o primeiro
        if t["id"] in frozen:
            c = frozen[t["id"]]
        elif t["id"] in accepted:
            c = accepted[t["id"]]
        else:
            n = last + 1
            while f"{prefix}{n}" in taken:
                n += 1
            c = f"{prefix}{n}"
            taken.add(c)
        out[t["id"]] = c
        last = max(last, _num(c))
    return out, conflicts


def demand_codes(rows, p: Product | None = None) -> dict[str, str]:
    """id → código de cada `task` do humano (§4.4): congelado > `code` gravado > posicional (lacuna). Só leitura."""
    return _compute(rows, p or resolve())[0]


def _source_matches(source: str, sources) -> bool:
    n = str(source).strip().replace("\\", "/")
    try:
        path = pathlib.Path(n)
        if path.is_absolute():
            n = path.resolve().relative_to(PLATFORM_ROOT).as_posix()
    except (OSError, ValueError):
        pass
    n = n.removeprefix("./").removeprefix("origin/").removeprefix("refs/heads/")
    for s in sources or []:
        if n == s or s.endswith("/" + n) or n.endswith("/" + s):
            return True
    return False


def resolve_code(ref: str, rows, p: Product | None = None, source: str | None = None) -> str | None:
    """Código, apelido ou id → id da demanda. Sem `source`, um código resolve SEMPRE para o congelado/atual; o apelido
    (ex.: D7 → e31bdfb73679) só vale no contexto de uma das suas `sources` (contrato §4.3)."""
    p = p or resolve()
    ref = str(ref or "").strip()
    codes = demand_codes(rows, p)
    if re.fullmatch(r"[0-9a-f]{12}", ref) and ref in codes:
        return ref
    if source:
        for a in frozen_table(p).get("aliases") or []:
            if str(a.get("alias", "")).upper() == ref.upper() and _source_matches(source, a.get("sources")):
                return a.get("id")
    by_code = {v.upper(): k for k, v in codes.items()}
    return by_code.get(ref.upper())


# ============================================================== gravação (única) de `task` do humano
def _flock(fd: int, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise LockTimeout(f"trava de códigos ocupada há mais de {timeout:.0f} s: nada gravado")
            time.sleep(0.02)


def append_task(entry: dict, p: Product | None = None) -> dict:
    """Grava UM `task` do humano com `code`/`code_prefix` sob trava exclusiva entre processos (§4.2)."""
    p = p or resolve()
    if "code" in entry or "code_prefix" in entry:
        raise ProductError("append_task: o código só nasce aqui (entry já traz code)")
    if entry.get("type") != "task" or entry.get("agent") != "humano":
        raise ProductError("append_task: só grava `task` do humano")
    p.locks_dir.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(p.locks_dir / "codes.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _flock(lock_fd, LOCK_TIMEOUT_S)
        rows = read_rows(p.log)
        top = max((_num(c) for c in demand_codes(rows, p).values() if _valid(c, p.code_prefix)), default=0)
        out = {**entry, "code": f"{p.code_prefix}{top + 1}", "code_prefix": p.code_prefix}
        p.log.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return out
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


# ============================================================== transcrições (§6)
def _slug(path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(pathlib.Path(path).resolve()))


def transcript_dir_for(path) -> pathlib.Path:
    """$SQUAD_TRANSCRIPTS, senão ~/.claude/projects/<caminho absoluto do cwd da sessão com [^A-Za-z0-9] → '->."""
    env = os.environ.get("SQUAD_TRANSCRIPTS")
    if env:
        return pathlib.Path(env)
    return pathlib.Path.home() / ".claude/projects" / _slug(path)


def _worktrees(root: pathlib.Path) -> tuple[list[pathlib.Path], pathlib.Path | None]:
    """(todos os worktrees, cópia principal = o que está em develop) pelo `git worktree list --porcelain`."""
    try:
        r = subprocess.run(["git", "-C", str(root), "worktree", "list", "--porcelain"], capture_output=True,
                           text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return [], None
    if r.returncode != 0:
        return [], None
    out, main, path = [], None, None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            path = pathlib.Path(line[len("worktree "):])
            out.append(path)
        elif line.strip() == "branch refs/heads/develop" and path and main is None:
            main = path
    return out, main


_dirs_cache: dict = {}


def transcript_dirs(p: Product | None = None) -> list[pathlib.Path]:
    """Pastas de transcrição a varrer: [$SQUAD_TRANSCRIPTS] (exclusivo) ou as do data_root, repo_root, cópia principal
    e de cada worktree — só as que existem, sem repetição, lista em cache por 30 s (orçamento do /api/live)."""
    env = os.environ.get("SQUAD_TRANSCRIPTS")
    if env:
        return [pathlib.Path(env)]
    p = p or resolve()
    key = (str(p.data_root), str(p.repo_root), str(pathlib.Path.home()), os.environ.get("SQUAD_MAIN_ROOT"))
    now = time.monotonic()
    hit = _dirs_cache.get(key)
    if hit and now - hit[0] < TRANSCRIPT_DIRS_TTL_S:
        return list(hit[1])
    wts, main = _worktrees(p.repo_root)
    env_main = os.environ.get("SQUAD_MAIN_ROOT")
    cands = [p.data_root, p.repo_root, pathlib.Path(env_main) if env_main else main]
    if main and not env_main:
        more, _ = _worktrees(main)                   # a lista de worktrees é a mesma, mas vale a da cópia principal
        wts = more or wts
    cands += wts
    out, seen = [], set()
    for c in cands:
        if not c:
            continue
        d = transcript_dir_for(c)
        if str(d) not in seen and d.is_dir():
            seen.add(str(d))
            out.append(d)
    _dirs_cache[key] = (now, out)
    return list(out)


def find_transcript(session_id: str, p: Product | None = None) -> pathlib.Path | None:
    """<sessionId>.jsonl na primeira pasta de transcript_dirs() que o tiver (runs antigas, sem `transcript`)."""
    for d in transcript_dirs(p):
        f = d / f"{session_id}.jsonl"
        if f.exists():
            return f
    return None


# ============================================================== CLI
def freeze(rows, until: str, prefix: str = "D") -> dict[str, str]:
    """Regra posicional de hoje aplicada aos `task` do humano até `until` (inclusive)."""
    tasks = human_tasks(rows)
    ids = [t["id"] for t in tasks]
    if until not in ids:
        raise ProductError(f"--until {until}: não é `task` do humano no log")
    cut = tasks[: ids.index(until) + 1]
    return {t["id"]: f"{prefix}{n}" for n, t in enumerate(cut, 1)}


def cmd_freeze(a) -> int:
    p = resolve(a.product)
    log = pathlib.Path(a.log) if a.log else p.log
    raw = log.read_bytes()
    rows = read_rows(log)
    codes = freeze(rows, a.until, p.code_prefix)
    for al in F2A_ALIASES:
        if codes.get(al["id"]) != al["code"]:
            raise ProductError(f"apelido {al['alias']}: {al['id']} deveria ser {al['code']}, é {codes.get(al['id'])}")
    table = {
        "schema": 1, "product": p.id, "prefix": p.code_prefix,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule": f"posicional do painel em {datetime.now(timezone.utc).date().isoformat()}: "
                "n-ésimo task com agent=humano no log",
        "source": {"log": CANONICAL_LOG, "lines": len(raw.decode("utf-8").splitlines()),
                   "sha256": hashlib.sha256(raw).hexdigest(), "lastTaskId": a.until},
        "codes": codes,
        "aliases": F2A_ALIASES if p.id == DEFAULT_PRODUCT else [],
    }
    out = pathlib.Path(a.out)
    if same_path(out, log):
        raise ProductError("--out não pode ser o log")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(codes)} códigos congelados ({min(codes.values(), key=_num)}–{max(codes.values(), key=_num)}) "
          f"até {a.until} → {out}")
    return 0


def check(rows, p: Product) -> list[str]:
    problems = []
    codes, conflicts = _compute(rows, p)
    for c in conflicts:
        problems.append(f"conflito: {c['code']} gravado em {c['dropped']} já é de {c['kept']}")
    frozen = frozen_table(p).get("codes") or {}
    present = {t["id"] for t in human_tasks(rows)}
    pos = positional_codes(rows, p.code_prefix)
    for i, c in frozen.items():
        if i not in present:
            problems.append(f"congelado ausente do log: {i} ({c})")
        elif pos.get(i) != c:
            problems.append(f"divergência com a regra posicional: {i} congelado {c}, posicional {pos.get(i)}")
    dup = {}
    for i, c in frozen.items():
        dup.setdefault(c, []).append(i)
    problems += [f"código congelado repetido: {c} em {', '.join(ids)}" for c, ids in dup.items() if len(ids) > 1]
    return problems


def cmd_codes(a) -> int:
    p = resolve(a.product)
    rows = read_rows(pathlib.Path(a.log) if a.log else p.log)
    codes = demand_codes(rows, p)
    aliases = frozen_table(p).get("aliases") or []
    problems = check(rows, p) if a.check else []
    if a.json:
        print(json.dumps({"product": p.id, "prefix": p.code_prefix, "codes": codes, "aliases": aliases,
                          "problems": problems}, ensure_ascii=False, indent=2))
    else:
        for i, c in codes.items():
            print(f"{c:>5}  {i}")
        for al in aliases:
            print(f"apelido {al['alias']} → {al['id']} ({al['code']}) em {len(al.get('sources') or [])} fonte(s)")
        for pr in problems:
            print(f"PROBLEMA: {pr}", file=sys.stderr)
    return 1 if problems else 0


def cmd_resolve(a) -> int:
    p = resolve(a.product)
    d = {k: (str(v) if isinstance(v, pathlib.Path) else v) for k, v in dataclasses.asdict(p).items()}
    print(json.dumps(d, ensure_ascii=False, indent=2) if a.json else "\n".join(f"{k}: {v}" for k, v in d.items()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("resolve"); s.add_argument("--product"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("codes"); s.add_argument("--product"); s.add_argument("--log")
    s.add_argument("--check", action="store_true"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("freeze-codes"); s.add_argument("--product"); s.add_argument("--log")
    s.add_argument("--until", required=True); s.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        return {"resolve": cmd_resolve, "codes": cmd_codes, "freeze-codes": cmd_freeze}[a.cmd](a)
    except ProductError as e:
        print(f"product.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
