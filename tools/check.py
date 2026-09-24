#!/usr/bin/env python3
"""Static checks the bot cannot make on itself at import time.

    python tools/check.py

Run it before a deploy. It starts nothing — no bot, no server, no network — it only reads the
source and imports the i18n package.

`bot/i18n/__init__.py` already validates the keys that ARE defined: EN/UZ key parity, matching
placeholders, and namespace ownership. What it cannot see is a key a router *references* but
nobody defined, because `t()` is documented to fall back to returning the key itself. That
fallback is right at runtime — a missing string should never crash the bot mid-payment — but it
means a whole screen can render `home.upcoming.title` raw at the owner and still pass every import
check. That happened once, to 112 keys across two sections, and this file exists so it cannot
happen quietly again.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The prefixes owned by bot/i18n/*.py. A literal starting with one of these is a translation
# key; anything else in the source is just a string.
NAMESPACES = (
    "auth", "common", "guard", "home", "lang", "pay", "record", "settings", "system", "wallet",
)
KEY_RE = re.compile(r"""["']((?:%s)\.[A-Za-z0-9_.]+)["']""" % "|".join(NAMESPACES))

failures: list[str] = []


def source_files() -> list[Path]:
    """Every module that could reference a key — the dictionaries themselves excluded."""
    return sorted(p for p in (ROOT / "bot").rglob("*.py") if "i18n" not in p.parts)


def check_keys_resolve() -> None:
    from bot import i18n

    known = set(i18n._EN)
    missing: dict[str, set[str]] = {}
    for path in source_files():
        found = {m.group(1) for m in KEY_RE.finditer(path.read_text(encoding="utf-8"))}
        unknown = found - known
        if unknown:
            missing[str(path.relative_to(ROOT))] = unknown
    if missing:
        for path, keys in missing.items():
            failures.append(f"{path}: {len(keys)} undefined i18n key(s): {', '.join(sorted(keys))}")
    print(f"  i18n: {len(known)} keys defined, "
          f"{sum(len(v) for v in missing.values())} referenced-but-undefined")


def check_dead_keys() -> None:
    """Defined and never referenced. A warning, not a failure — some are looked up dynamically."""
    from bot import i18n

    used: set[str] = set()
    for path in source_files():
        used |= {m.group(1) for m in KEY_RE.finditer(path.read_text(encoding="utf-8"))}
    dead = sorted(k for k in i18n._EN if k not in used)
    print(f"  i18n: {len(dead)} defined-but-unreferenced (dynamic lookups land here too)")
    for key in dead:
        print(f"      · {key}")


def callback_handlers() -> list[dict]:
    """Every callback filter, in the order the dispatcher will consult it.

    Router order comes from main.py's include loop, and within a router aiogram checks handlers
    in registration order — the first whose filters pass wins and the rest never run.
    """
    main_src = (ROOT / "bot" / "main.py").read_text(encoding="utf-8")
    match = re.search(r"for r in \(([^)]*)\)", main_src, re.S)
    order = [x.strip().split(".")[0] for x in match.group(1).replace("\n", " ").split(",")
             if x.strip() and x.strip() != "router"] if match else []
    rank = {name: i for i, name in enumerate(order)}

    out: list[dict] = []
    for path in sorted((ROOT / "bot" / "routers").glob("*.py")):
        name = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                if not ast.unparse(dec.func).endswith("callback_query"):
                    continue
                text = ast.unparse(dec)
                state = re.search(r"StateFilter\(([^)]*)\)", text)
                for kind, pattern in (("eq", r"F\.data\s*==\s*'([^']*)'"),
                                      ("pre", r"F\.data\.startswith\('([^']*)'\)")):
                    for m in re.finditer(pattern, text):
                        out.append({
                            "router": name, "kind": kind, "value": m.group(1),
                            "line": node.lineno, "fn": node.name,
                            "state": state.group(1).strip() if state else None,
                            "rank": rank.get(name, 99),
                        })
    out.sort(key=lambda h: (h["rank"], h["line"]))
    return out


def check_callback_shadowing(handlers: list[dict]) -> None:
    """A `startswith` filter that swallows a longer filter registered after it.

    Only counts when the earlier handler can actually fire wherever the later one can: a
    stateless prefix shadows everything below it, but two handlers under different
    `StateFilter`s never compete. Getting that distinction wrong turns every deliberate
    stale-button fallback into a false alarm.
    """
    bad = []
    for i, first in enumerate(handlers):
        if first["kind"] != "pre":
            continue
        for later in handlers[i + 1:]:
            if later["value"] == first["value"]:
                continue
            if not later["value"].startswith(first["value"]):
                continue
            if first["state"] is None or first["state"] == later["state"]:
                bad.append((first, later))
    for a, b in bad:
        failures.append(
            f"{a['router']}.py:{a['line']} {a['fn']} startswith({a['value']!r}) shadows "
            f"{b['router']}.py:{b['line']} {b['fn']} {b['kind']}({b['value']!r})")
    print(f"  callbacks: {len(handlers)} handlers, {len(bad)} shadowed")


def check_callback_data_size(handlers: list[dict]) -> None:
    """Telegram rejects callback_data over 64 BYTES. Literals only — an f-string's ids are
    unbounded here, so this catches the static half and leaves the dynamic half to review."""
    over = [h for h in handlers if len(h["value"].encode()) > 64]
    for h in over:
        failures.append(f"{h['router']}.py:{h['line']}: callback_data literal over 64 bytes")
    print(f"  callbacks: {len(over)} literals over the 64-byte cap")


def check_legacy_patterns() -> None:
    """Constructs the rebuild retired. Each one is a bug the audit actually found."""
    banned = {
        r"\bcb\.answer\(": "cb.answer() — use common.ack(cb), which is idempotent per query id",
        r"dt\.date\.today\(\)": "dt.date.today() — UTC in the container; use bot.clock",
        r"\bdatetime\.now\(\)": "datetime.now() — UTC in the container; use bot.clock",
        r"""strftime\(["']%Y-%m["']\)""": "strftime('%Y-%m') — use clock.month()",
    }
    exempt = {"bot/clock.py", "bot/common.py"}
    total = 0
    for pattern, why in banned.items():
        for path in source_files():
            rel = str(path.relative_to(ROOT))
            if rel in exempt:
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip().startswith("#") or '"""' in line:
                    continue
                if re.search(pattern, line):
                    failures.append(f"{rel}:{n}: {why}")
                    total += 1
    print(f"  legacy: {total} occurrence(s) of retired constructs")


def main() -> int:
    print("Checking the bot (nothing is started) …\n")
    check_keys_resolve()
    handlers = callback_handlers()
    check_callback_shadowing(handlers)
    check_callback_data_size(handlers)
    check_legacy_patterns()
    check_dead_keys()

    print()
    if failures:
        print(f"FAILED — {len(failures)} problem(s):\n")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
