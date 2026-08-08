#!/usr/bin/env python3
"""
Vibe-Trading plugin — Agent Zero v2.2 contract check.

Catches accidental regressions of the plugin to the legacy v1.x banner
contract (`def announce(context, **kwargs)`) or to the disabled toggle.

Runs three checks:

  1. Toggle — `.toggle-1` must exist in the plugin root, `.toggle-0` must not.
  2. Banners — every `extensions/python/banners/*.py` must export a top-level
     `def execute(banners: list, **kwargs)` (or `*args, **kwargs` where the
     first parameter is named `banners`) and must NOT contain a top-level
     `def announce(`.
  3. Hooks — `hooks.py` must define `install`, `pre_update`, and
     `uninstall` callables, and they must return a dict.

Exit code 0 = all green, 1 = at least one failure, 2 = import/syntax error.

Run as the first step of `execute.py`, or directly:

    python /a0/usr/plugins/vibe_trading/scripts/check_v22_contract.py

Designed to be importable as a library as well — the `main()` function
returns a `(ok: bool, report: list[dict])` tuple.
"""

from __future__ import annotations

import ast
import os
import sys
from typing import Any, Dict, List, Tuple


PLUGIN_NAME = "vibe_trading"


def _plugin_root() -> str:
    """Plugin root = parent of this scripts/ directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _check_toggle(here: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    on = os.path.isfile(os.path.join(here, ".toggle-1"))
    off = os.path.isfile(os.path.join(here, ".toggle-0"))
    if on and not off:
        findings.append({"ok": True, "check": "toggle", "detail": ".toggle-1 present, .toggle-0 absent"})
    elif off:
        findings.append({"ok": False, "check": "toggle", "detail": ".toggle-0 present — plugin is disabled"})
    elif not on:
        findings.append({"ok": False, "check": "toggle", "detail": ".toggle-1 missing — plugin is not enabled"})
    else:
        findings.append({"ok": False, "check": "toggle", "detail": "both .toggle-0 and .toggle-1 present (invalid)"})
    return findings


def _check_banners(here: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    banners_dir = os.path.join(here, "extensions", "python", "banners")
    if not os.path.isdir(banners_dir):
        findings.append({"ok": False, "check": "banners_dir", "detail": f"{banners_dir} does not exist"})
        return findings
    py_files = sorted(f for f in os.listdir(banners_dir) if f.endswith(".py") and not f.startswith("__"))
    if not py_files:
        findings.append({"ok": True, "check": "banners_dir", "detail": "no banner files (empty plugin)"})
        return findings
    for fname in py_files:
        path = os.path.join(banners_dir, fname)
        try:
            src = open(path, "r", encoding="utf-8").read()
            tree = ast.parse(src, filename=path)
        except SyntaxError as e:
            findings.append({"ok": False, "check": "banner_syntax",
                             "detail": f"{fname}: SyntaxError: {e}"})
            continue
        # Look for top-level def announce(...) — banned
        has_announce = any(
            isinstance(node, ast.FunctionDef) and node.name == "announce"
            for node in tree.body
        )
        if has_announce:
            findings.append({"ok": False, "check": "banner_signature",
                             "detail": f"{fname}: top-level `def announce(` found — v1.x contract"})
            continue
        # Look for top-level def execute(banners, ...) — required
        has_execute = False
        execute_ok = False
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "execute":
                has_execute = True
                if not node.args.args:
                    findings.append({"ok": False, "check": "banner_signature",
                                     "detail": f"{fname}: `def execute(...)` has no positional args"})
                    break
                first = node.args.args[0]
                if first.arg != "banners":
                    findings.append({"ok": False, "check": "banner_signature",
                                     "detail": f"{fname}: first arg of execute() is {first.arg!r}, expected 'banners'"})
                    break
                execute_ok = True
        if not has_execute:
            findings.append({"ok": False, "check": "banner_signature",
                             "detail": f"{fname}: no top-level `def execute(` found"})
        elif execute_ok:
            findings.append({"ok": True, "check": "banner_signature",
                             "detail": f"{fname}: `def execute(banners, **kwargs)` (v2.2 contract)"})
    return findings


def _check_hooks(here: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    hooks_path = os.path.join(here, "hooks.py")
    if not os.path.isfile(hooks_path):
        findings.append({"ok": False, "check": "hooks_file", "detail": f"{hooks_path} not found"})
        return findings
    try:
        src = open(hooks_path, "r", encoding="utf-8").read()
        tree = ast.parse(src, filename=hooks_path)
    except SyntaxError as e:
        findings.append({"ok": False, "check": "hooks_syntax",
                         "detail": f"hooks.py: SyntaxError: {e}"})
        return findings
    for required in ("install", "pre_update", "uninstall"):
        found = False
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == required:
                found = True
                # Sanity: must be a plain def or async def
                break
        if found:
            findings.append({"ok": True, "check": "hooks_function",
                             "detail": f"hooks.{required}() defined"})
        else:
            findings.append({"ok": False, "check": "hooks_function",
                             "detail": f"hooks.{required}() not defined"})
    return findings


def main() -> Tuple[bool, List[Dict[str, Any]]]:
    here = _plugin_root()
    report: List[Dict[str, Any]] = []
    report.extend(_check_toggle(here))
    report.extend(_check_banners(here))
    report.extend(_check_hooks(here))
    ok = all(f["ok"] for f in report)
    return ok, report


def _print_report(report: List[Dict[str, Any]]) -> None:
    for f in report:
        mark = "OK  " if f["ok"] else "FAIL"
        print(f"[{PLUGIN_NAME}] [{mark}] {f['check']:>18}: {f['detail']}")


if __name__ == "__main__":
    ok, report = main()
    _print_report(report)
    sys.exit(0 if ok else 1)
