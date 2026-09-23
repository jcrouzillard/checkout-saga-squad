#!/usr/bin/env python3
"""Tee de statusline do Claude Code (D11, ADR-014, contrato docs/contracts/ui-consumo-da-ia.md §2).

Recebe no stdin o JSON que o Claude Code entrega à statusline, grava um snapshot mínimo do consumo
(`rate_limits.five_hour` / `seven_day`) em <DATA_ROOT>/.squad/usage/claude.json e encadeia a statusline
anterior do usuário com o MESMO stdin, devolvendo a saída e o código de saída dela sem alteração.

Uso (statusline):  python3 tools/squad/statusline_usage.py [--next "<comando anterior>"] [--data-root DIR]
Instalação (só o humano executa):
    python3 tools/squad/statusline_usage.py --install   [--settings ~/.claude/settings.json] [--data-root DIR]
    python3 tools/squad/statusline_usage.py --uninstall [--settings ~/.claude/settings.json]

DATA_ROOT = --data-root, senão $SQUAD_ROOT_DATA, senão a raiz do repositório deste script.
O snapshot contém só números e horários: nunca tokens, e-mail, session_id, caminhos ou outros campos.
"""
import argparse
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone

SCRIPT = pathlib.Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[2]
MARKER = "statusline_usage.py"
TEE_TIMEOUT_S = 1.0
REFRESH_UNCHANGED_S = 60  # mesmo sem mudança de valores, renova collectedAt no máximo a cada 60 s


def data_root(arg: str | None) -> pathlib.Path:
    return pathlib.Path(arg or os.environ.get("SQUAD_ROOT_DATA") or REPO_ROOT).expanduser().resolve()


def _iso(epoch) -> str | None:
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _window(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    pct = raw.get("used_percentage")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None
    return {"usedPercent": float(pct), "resetsAt": _iso(raw.get("resets_at"))}


def extract(payload: bytes) -> dict | None:
    """Whitelist: só five_hour/seven_day. Qualquer outro campo do JSON de entrada é descartado."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    rl = data.get("rate_limits") if isinstance(data, dict) else None
    if not isinstance(rl, dict):
        return None
    five, week = _window(rl.get("five_hour")), _window(rl.get("seven_day"))
    if five is None and week is None:
        return None
    return {"fiveHour": five, "sevenDay": week}


def write_snapshot(payload: bytes, root: pathlib.Path) -> None:
    values = extract(payload)
    if values is None:  # sem rate_limits / JSON inválido: não toca no snapshot anterior
        return
    target = root / ".squad/usage/claude.json"
    now = datetime.now(timezone.utc)
    try:
        prev = json.loads(target.read_text(encoding="utf-8"))
        prev_at = datetime.strptime(prev["collectedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if ({"fiveHour": prev.get("fiveHour"), "sevenDay": prev.get("sevenDay")} == values
                and (now - prev_at).total_seconds() < REFRESH_UNCHANGED_S):
            return  # valores iguais e coleta recente: evita reescrever a cada redesenho
    except Exception:
        pass
    snap = {"collectedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), **values}
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".claude.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        os.replace(tmp, target)  # atômico
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _tee(payload: bytes, root: pathlib.Path) -> None:
    try:
        write_snapshot(payload, root)
    except Exception:
        pass  # a statusline do usuário nunca quebra por causa do tee


def run_statusline(next_cmd: str | None, root: pathlib.Path) -> int:
    try:
        payload = sys.stdin.buffer.read()
    except Exception:
        payload = b""
    t = threading.Thread(target=_tee, args=(payload, root), daemon=True)
    t.start()
    rc = 0
    if next_cmd:
        sys.stdout.flush()
        # Sem timeout e com stdout/stderr herdados: saída byte a byte idêntica à do comando original.
        try:
            rc = subprocess.run(next_cmd, shell=True, input=payload).returncode
        except Exception:
            rc = 1
    else:
        sys.stdout.write("\n")
        sys.stdout.flush()
    t.join(TEE_TIMEOUT_S)  # o tee tem no máximo 1 s (em paralelo ao --next)
    return rc


# ---------------------------------------------------------------- instalação (só o humano executa)

def _load_settings(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"recusado: {path} não é um objeto JSON")
    return data


def _save_settings(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings.", suffix=".tmp", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def _backup(path: pathlib.Path) -> pathlib.Path | None:
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(f"{path.name}.bak-squad-{ts}")
    n = 1
    while bak.exists():
        bak = path.with_name(f"{path.name}.bak-squad-{ts}-{n}")
        n += 1
    shutil.copy2(path, bak)
    return bak


def _prev_file(root: pathlib.Path) -> pathlib.Path:
    return root / ".squad/usage/statusline.prev.json"


def install(settings_path: pathlib.Path, data_root_arg: str | None) -> int:
    settings = _load_settings(settings_path)
    current = settings.get("statusLine")
    if current is not None and (not isinstance(current, dict) or current.get("type") != "command"):
        print("recusado: statusLine atual não é do tipo 'command'; nada foi alterado.", file=sys.stderr)
        return 2
    prev_cmd = (current or {}).get("command")
    if prev_cmd is not None and not isinstance(prev_cmd, str):
        print("recusado: statusLine.command não é texto; nada foi alterado.", file=sys.stderr)
        return 2
    if prev_cmd and MARKER in prev_cmd:
        print("já instalado; nada foi alterado.")
        return 0
    cmd = f"python3 {shlex.quote(str(SCRIPT))}"
    if data_root_arg:
        cmd += f" --data-root={shlex.quote(str(data_root(data_root_arg)))}"
    if prev_cmd:
        cmd += f" --next={shlex.quote(prev_cmd)}"  # '=' aceita comando que comece com '-'
    bak = _backup(settings_path)
    root = data_root(data_root_arg)
    pf = _prev_file(root)
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(json.dumps({"settings": str(settings_path), "statusLine": current}, ensure_ascii=False, indent=2))
    new = dict(current or {"type": "command"})
    new["command"] = cmd
    settings["statusLine"] = new
    _save_settings(settings_path, settings)
    print(f"instalado em {settings_path}")
    if bak:
        print(f"backup: {bak}")
    print(f"snapshot: {root / '.squad/usage/claude.json'} (o painel deve usar este DATA_ROOT)")
    return 0


def _parse_our_command(cmd: str) -> tuple[str | None, str | None]:
    """Devolve (data_root, next) do comando instalado por nós."""
    argv = shlex.split(cmd)
    nxt = droot = None
    for i, a in enumerate(argv):
        if a.startswith("--next="):
            nxt = a[len("--next="):]
        if a.startswith("--data-root="):
            droot = a[len("--data-root="):]
        if a == "--next" and i + 1 < len(argv):
            nxt = argv[i + 1]
        if a == "--data-root" and i + 1 < len(argv):
            droot = argv[i + 1]
    return droot, nxt


def uninstall(settings_path: pathlib.Path, data_root_arg: str | None) -> int:
    settings = _load_settings(settings_path)
    current = settings.get("statusLine")
    cmd = current.get("command") if isinstance(current, dict) else None
    if not isinstance(cmd, str) or MARKER not in cmd:
        print("não instalado; nada foi alterado.")
        return 0
    droot, nxt = _parse_our_command(cmd)
    pf = _prev_file(data_root(data_root_arg or droot))
    restored, found = None, False
    try:
        saved = json.loads(pf.read_text(encoding="utf-8"))
        prev = saved.get("statusLine")
        prev_cmd = prev.get("command") if isinstance(prev, dict) else None
        if prev_cmd == nxt:  # só confia no arquivo lateral se bate com o --next instalado
            restored, found = prev, True
    except Exception:
        pass
    if not found:
        if nxt is not None:
            restored = dict(current)
            restored["command"] = nxt
        else:
            restored = None
    bak = _backup(settings_path)
    if restored is None:
        settings.pop("statusLine", None)
    else:
        settings["statusLine"] = restored  # só a chave statusLine; o resto do arquivo fica como está hoje
    _save_settings(settings_path, settings)
    try:
        pf.unlink()
    except OSError:
        pass
    print(f"desinstalado de {settings_path}; statusLine restaurada")
    if bak:
        print(f"backup: {bak}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--next", dest="next_cmd", help="statusline anterior a encadear (mesmo stdin)")
    ap.add_argument("--data-root", help="DATA_ROOT do snapshot (padrão: $SQUAD_ROOT_DATA ou raiz do repo)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true", help="instala o tee em statusLine (só o humano)")
    g.add_argument("--uninstall", action="store_true", help="restaura a statusLine anterior")
    ap.add_argument("--settings", default="~/.claude/settings.json", help="settings do Claude Code")
    args = ap.parse_args(argv)
    settings = pathlib.Path(args.settings).expanduser()
    if args.install:
        return install(settings, args.data_root)
    if args.uninstall:
        return uninstall(settings, args.data_root)
    return run_statusline(args.next_cmd, data_root(args.data_root))


if __name__ == "__main__":
    sys.exit(main())
