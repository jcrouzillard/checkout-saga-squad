#!/usr/bin/env python3
"""Ambiente e versão do próprio Squad Control (D18, ADR-021, contrato `docs/contracts/ui-ambiente-e-versao.md`).

`Instance(root, port, data_root, log)` calcula na subida o ambiente (§1) e a versão (§2); `snapshot()` devolve o
objeto `instance` de `/api/state` e `GET /api/instance`, com a atualidade (§3) e o `dirty` em cache de 30 s.
Somente leitura; todo comando git tem timeout de 2 s e falha vira `null` (nunca derruba o servidor).
`/api/live` NÃO usa este módulo (orçamento do ADR-017).
"""
import os
import pathlib
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import testenv as te

GIT_TIMEOUT = 2.0
CACHE_S = 30.0
PROD_PORT = 7070
CODE_PATHS = ("tools/squad", "squad-control")   # o que o servidor executa/serve
ENVS = ("produtivo", "teste")
LABELS = {"produtivo": "Produtivo", "teste": "Teste", "desconhecido": "Ambiente desconhecido"}
FINAL_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SEP = " · "
PUBLISHER_WORKTREE = "plankton-squad-prev"   # D24 (ADR-025 §5): worktree de rollback do publicador
PUBLISH_MODES = ("principal", "anterior")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(root: pathlib.Path, *args: str, timeout: float = GIT_TIMEOUT) -> tuple[int, str] | None:
    """(returncode, stdout) ou None se o git não existe / estourou o tempo."""
    try:
        p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _out(root: pathlib.Path, *args: str) -> str | None:
    r = git(root, *args)
    return r[1].strip() if r and r[0] == 0 else None


def _under(p: pathlib.Path, base: pathlib.Path) -> bool:
    try:
        p.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


# ================================================================ §1 ambiente
def environment(root: pathlib.Path, port: int, data_root: pathlib.Path, log: pathlib.Path,
                env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    root, data_root, log = root.resolve(), data_root.resolve(), pathlib.Path(log).resolve()
    in_repo = _out(root, "rev-parse", "--is-inside-work-tree") == "true"          # regra 3, sem depender da 4
    main = te.find_main_root(root, timeout=GIT_TIMEOUT) if in_repo else None     # R1: sem fallback para ROOT
    data_is_main = bool(main) and (data_root == main or _under(log, main))       # R4: SQUAD_LOG também conta
    out = {"port": port, "worktree": root.name, "root": str(root), "dataRoot": str(data_root),
           "log": str(log), "dataIsMain": data_is_main}

    raw = env.get("SQUAD_ENV")
    if raw is not None:
        v = raw.strip()
        if v in ENVS:
            name, source, reason = v, "SQUAD_ENV", f"SQUAD_ENV={v}"
        else:
            name, source, reason = "desconhecido", "SQUAD_ENV", f"valor inválido: {raw}"
    elif not in_repo:
        name, source, reason = "desconhecido", "indeterminado", "git indisponível ou fora de repositório"
    else:
        source = "inferido"
        where = "cópia principal" if main and root == main else (
            "publicador (rollback)" if root.name == PUBLISHER_WORKTREE else f"worktree {root.name}")
        parts = [where, f"porta {port}"]
        if main is None:
            parts.append("nenhum worktree em develop")
        own_data = data_root == root and _under(log, root)
        if data_root != root:
            parts.append(f"dados de {data_root.name}")
        if not _under(log, data_root):
            parts.append(f"log em {log}")
        if main is not None and root == main and port == PROD_PORT and own_data:
            name = "produtivo"
            parts = ["cópia principal (develop)", f"porta {port}"]
        else:
            name = "teste"
        reason = ", ".join(parts)
    return {"name": name, "label": LABELS[name], "source": source, "reason": reason, **out}


# ================================================================ §2 versão
def pom_version(root: pathlib.Path) -> str | None:
    """`<project><version>` (filho direto de <project>, não o do <parent>)."""
    try:
        tree = ET.parse(root / "pom.xml").getroot()
    except (OSError, ET.ParseError):
        return None
    for child in tree:
        if child.tag.rsplit("}", 1)[-1] == "version":
            return (child.text or "").strip() or None
    return None


def latest_release(root: pathlib.Path) -> str | None:
    """Maior tag `vX.Y.Z` final do repositório (não `git describe`: v1.0.0 não é ancestral de develop).
    R6: pré-releases (v1.1.0-rc1) só entram se não houver nenhuma final."""
    out = _out(root, "tag", "--list", "v[0-9]*", "--sort=-v:refname")
    if not out:
        return None
    tags = [t.strip() for t in out.splitlines() if t.strip()]
    finals = [t for t in tags if FINAL_TAG.match(t)]
    if finals:
        return max(finals, key=lambda t: tuple(int(x) for x in FINAL_TAG.match(t).groups()))
    return tags[0] if tags else None


def dirty(root: pathlib.Path) -> bool | None:
    out = git(root, "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHS)
    return bool(out[1].strip()) if out and out[0] == 0 else None


def display(b: dict) -> str:
    s = SEP.join([b.get("release") or "sem tag", b.get("pom") or "pom ?", b.get("commit") or "commit ?"])
    return s + (" +alterações" if b.get("dirty") else "")


def build(root: pathlib.Path) -> dict:
    full = _out(root, "rev-parse", "HEAD")
    branch = _out(root, "rev-parse", "--abbrev-ref", "HEAD") if full else None
    b = {"release": latest_release(root) if full else None, "pom": pom_version(root),
         "commit": full[:7] if full else None, "commitFull": full,
         "branch": None if branch in (None, "HEAD") else branch,
         "dirty": dirty(root) if full else None, "startedAt": _now()}
    b["display"] = display(b)
    return b


# ================================================================ §3 atualidade + objeto
class Instance:
    def __init__(self, root: pathlib.Path, port: int, data_root: pathlib.Path, log: pathlib.Path,
                 env: dict | None = None, cache_s: float = CACHE_S):
        self.root = pathlib.Path(root).resolve()
        self.cache_s = cache_s
        self.env = environment(self.root, port, pathlib.Path(data_root), pathlib.Path(log), env)
        self.build = build(self.root) if self.env["source"] != "indeterminado" else {
            "release": None, "pom": pom_version(self.root), "commit": None, "commitFull": None, "branch": None,
            "dirty": None, "startedAt": _now()}
        self.build.setdefault("display", display(self.build))
        # D24 (contrato §4.4): só acréscimos dentro de `build`/`freshness`
        e = os.environ if env is None else env
        mode = (e.get("SQUAD_PUBLISH_MODE") or "").strip()
        self.build["mode"] = mode if mode in PUBLISH_MODES else "principal"
        self.build["pid"] = os.getpid()
        self.reverted = (e.get("SQUAD_PUBLISH_REVERTED") or "").strip() or None
        self._lock = threading.Lock()
        self._at = 0.0
        self._fresh: dict | None = None
        self._diff: dict = {}          # headNow -> nº de arquivos mudados em CODE_PATHS (R2: diff só em HEAD novo)

    def _refresh(self) -> dict:
        full = self.build.get("commitFull")
        if not full:
            return {"state": "indeterminado", "headNow": None, "changedPaths": None, "checkedAt": _now()}
        head = _out(self.root, "rev-parse", "HEAD")
        self.build["dirty"] = dirty(self.root)                     # R3: dirty acompanha o que está no disco
        self.build["display"] = display(self.build)
        if not head:
            return {"state": "indeterminado", "headNow": None, "changedPaths": None, "checkedAt": _now()}
        if head == full:
            n = 0
        elif head in self._diff:
            n = self._diff[head]
        else:
            r = git(self.root, "diff", "--name-only", full, head, "--", *CODE_PATHS)
            n = len([x for x in r[1].splitlines() if x.strip()]) if r and r[0] == 0 else None
            if n is not None:
                self._diff = {head: n}
        state = "indeterminado" if n is None else ("atual" if n == 0 else "desatualizado")
        return {"state": state, "headNow": head[:7], "changedPaths": n, "checkedAt": _now()}

    def snapshot(self) -> dict:
        with self._lock:
            if self._fresh is None or time.monotonic() - self._at >= self.cache_s:
                self._fresh = self._refresh()
                if self.reverted:   # D24: no ar o commit anterior depois de uma publicação que falhou
                    self._fresh.update(state="revertido", failedCommit=self.reverted[:7])
                self._at = time.monotonic()
            return {"environment": dict(self.env), "build": dict(self.build), "freshness": dict(self._fresh)}
