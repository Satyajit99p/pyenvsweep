"""Command-line interface for pyenvsweep."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyze import PROTECTED, duplicates, group_by_name, prune_plan, required_by, requested_unused, uninstall
from .scan import Environment, Package, norm, scan


def mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def table(headers: list[str], rows: list[list]) -> str:
    cells = [headers] + [[str(c) for c in row] for row in rows]
    widths = [max(len(c) for c in col) for col in zip(*cells)]

    def fmt(row) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip()

    lines = [fmt(headers), fmt(["-" * w for w in widths])]
    lines += [fmt(row) for row in cells[1:]]
    return "\n".join(lines)


def pick_env(envs: list[Environment], text: str) -> Environment:
    """Select one environment by a part of its path. Must match exactly one."""
    matches = [e for e in envs if text.lower() in e.prefix.lower()]
    if len(matches) != 1:
        found = "\n  ".join(e.prefix for e in matches) or "none"
        sys.exit(f"--env '{text}' matched {len(matches)} environments ({found}).\n"
                 "Run `pyenvsweep envs` and use a more specific part of the path.")
    return matches[0]


def warn_if_base(env: Environment) -> None:
    if env.is_base:
        print("WARNING: this is your global Python. Removing packages here can break other tools.\n")


def uninstall_all(env: Environment, pkgs: list[Package]) -> int:
    failed = []
    for pkg in pkgs:
        ok = uninstall(env, pkg.name)
        print(f"{'removed' if ok else 'FAILED '}  {pkg.name} {pkg.version}")
        if not ok:
            failed.append(pkg.name)
    if failed:
        print(f"\n{len(failed)} failed: {', '.join(failed)}. This can happen in uv-managed venvs, which have no pip.")
    return 1 if failed else 0


def cmd_envs(envs: list[Environment], args) -> None:
    rows = [[i, mb(e.size), len(e.packages), "global" if e.is_base else "venv", e.prefix]
            for i, e in enumerate(envs, 1)]
    print(table(["#", "size", "packages", "type", "path"], rows))
    print(f"\nTotal: {mb(sum(e.size for e in envs))} across {len(envs)} environments")


def cmd_packages(envs: list[Environment], args) -> None:
    if args.env:
        env = pick_env(envs, args.env)
        pkgs = sorted(env.packages, key=lambda p: -p.size)
        print(table(["package", "version", "size", "location"],
                    [[p.name, p.version, mb(p.size), p.location] for p in pkgs]))
        return

    rows = []
    for items in group_by_name(envs).values():
        if args.duplicates and len(items) < 2:
            continue
        versions = sorted({p.version for _, p in items})
        total = sum(p.size for _, p in items)
        rows.append((len(items), total, items[0][1].name, versions))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print(table(["package", "versions", "envs", "total size"],
                [[name, ", ".join(v), n, mb(s)] for n, s, name, v in rows]))
    if args.duplicates:
        extra = sum(e for _, _, e in duplicates(envs))
        print(f"\nExtra copies (everything beyond the largest copy of each package): {mb(extra)}")


def cmd_prune(envs: list[Environment], args) -> int:
    env = pick_env(envs, args.env)
    plan = prune_plan(env, keep=args.keep, cascade=not args.no_cascade)
    print(f"Protected (never listed): {', '.join(sorted(PROTECTED))}\n")
    review = requested_unused(env, keep=args.keep)
    if review:
        print("Installed by you and used by nothing else. Not removed automatically; "
              "remove one with `remove NAME --env ...` if you no longer need it:")
        print(table(["package", "version", "size"],
                    [[p.name, p.version, mb(p.size)] for p in review]))
        print()
    if not plan:
        print("No leftover dependencies to remove.")
        return 0
    warn_if_base(env)
    print("Leftover dependencies (installed for another package that is gone):")
    print(table(["package", "version", "size"],
                [[p.name, p.version, mb(p.size)] for p in plan]))
    print(f"\n{len(plan)} packages, {mb(sum(p.size for p in plan))} would be freed. Listed in uninstall order.")
    if not args.yes:
        print("Dry run: nothing was removed. Add --yes to uninstall. Use --keep NAME to protect a package.")
        return 0
    return uninstall_all(env, plan)


def cmd_remove(envs: list[Environment], args) -> int:
    env = pick_env(envs, args.env)
    key = norm(args.name)
    pkg = next((p for p in env.packages if p.key == key), None)
    if pkg is None:
        sys.exit(f"{args.name} is not installed in {env.prefix}")
    if key in PROTECTED:
        sys.exit(f"{pkg.name} is protected and will not be removed")
    users = required_by(env, key)
    if users and not args.force:
        sys.exit(f"{pkg.name} is required by {', '.join(users)}. Remove those first, or pass --force.")
    warn_if_base(env)
    print(f"{pkg.name} {pkg.version} ({mb(pkg.size)}) in {env.prefix}")
    if not args.yes:
        print("Dry run: nothing was removed. Add --yes to uninstall.")
        return 0
    return uninstall_all(env, [pkg])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pyenvsweep",
        description="List, audit and remove packages across all Python environments on this machine.")
    p.add_argument("--root", action="append", type=Path,
                   help="folder to search for venvs (repeatable; default: your home folder)")
    p.add_argument("--no-base", action="store_true", help="skip the global Python")
    p.add_argument("--trust", action="store_true",
                   help="run discovered venv interpreters without asking (required when not interactive)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("envs", help="list every environment with its size")

    pk = sub.add_parser("packages", help="list packages; with --env, list one environment")
    pk.add_argument("--env", help="part of the environment path")
    pk.add_argument("--duplicates", action="store_true", help="only packages in more than one environment")

    pr = sub.add_parser("prune", help="find orphans (nothing requires them) and optionally uninstall them")
    pr.add_argument("--env", required=True, help="part of the environment path")
    pr.add_argument("--keep", action="append", default=[], metavar="NAME", help="never remove this package")
    pr.add_argument("--no-cascade", action="store_true", help="only the first round of orphans")
    pr.add_argument("--yes", action="store_true", help="actually uninstall (default is a dry run)")

    rm = sub.add_parser("remove", help="uninstall one package from one environment")
    rm.add_argument("name")
    rm.add_argument("--env", required=True, help="part of the environment path")
    rm.add_argument("--force", action="store_true", help="remove even if other packages require it")
    rm.add_argument("--yes", action="store_true", help="actually uninstall (default is a dry run)")
    return p


def confirm_interpreters(pythons: list[str], trust: bool) -> None:
    """Ask before running interpreters found on disk; they execute arbitrary code."""
    if trust:
        return
    shown = 20
    print(f"Found {len(pythons)} virtual environment(s). pyenvsweep will run each one's Python "
          "to read its packages, which executes code from those folders:")
    for p in pythons[:shown]:
        print(f"  {p}")
    if len(pythons) > shown:
        print(f"  ... and {len(pythons) - shown} more")
    no_prompt = ("Not running discovered interpreters without a prompt. "
                 "Pass --trust to allow it, or narrow the search with --root.")
    if not sys.stdin.isatty():
        sys.exit(no_prompt)
    try:
        answer = input("Run them? [y/N] ")
    except EOFError:  # Windows reports NUL as a tty
        sys.exit(no_prompt)
    if answer.strip().lower() not in ("y", "yes"):
        sys.exit("Aborted.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    envs = scan(args.root or [Path.home()], include_base=not args.no_base,
                confirm=lambda pythons: confirm_interpreters(pythons, args.trust))
    if not envs:
        sys.exit("No Python environments found.")
    handlers = {"envs": cmd_envs, "packages": cmd_packages, "prune": cmd_prune, "remove": cmd_remove}
    return handlers[args.cmd](envs, args) or 0
