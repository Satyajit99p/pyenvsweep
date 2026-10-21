"""Dependency analysis: duplicates, orphans and uninstalling."""
from __future__ import annotations

import subprocess
from collections import defaultdict

from .scan import Environment, Package, norm, req_name

# Never offered for removal: pip and friends are needed to manage the env itself.
PROTECTED = {"pip", "setuptools", "wheel", "pyenvsweep"}


def group_by_name(envs: list[Environment]) -> dict[str, list[tuple[Environment, Package]]]:
    groups: dict[str, list[tuple[Environment, Package]]] = defaultdict(list)
    for env in envs:
        for pkg in env.packages:
            groups[pkg.key].append((env, pkg))
    return groups


def duplicates(envs: list[Environment]) -> list[tuple[str, list, int]]:
    """Packages installed in more than one environment.

    Returns (name, [(env, pkg), ...], extra_bytes) sorted by extra_bytes.
    extra_bytes is everything beyond the largest copy.
    """
    out = []
    for key, items in group_by_name(envs).items():
        if len(items) > 1:
            sizes = [p.size for _, p in items]
            out.append((key, items, sum(sizes) - max(sizes)))
    return sorted(out, key=lambda t: -t[2])


def required_by(env: Environment, key: str) -> list[str]:
    """Names of installed packages in this env that list `key` as a requirement."""
    return [p.name for p in env.packages
            if p.key != key and any(req_name(r) == key for r in p.requires)]


def required_names(packages: list[Package]) -> set[str]:
    """Every package name that some package in `packages` requires.

    Requirements are counted even when they sit behind an extra marker, so a
    package used only by an optional extra is not treated as unused.
    """
    needed = set()
    for pkg in packages:
        for r in pkg.requires:
            name = req_name(r)
            if name and name != pkg.key:
                needed.add(name)
    return needed


def requested_unused(env: Environment, keep: list[str] | tuple = ()) -> list[Package]:
    """Packages you installed directly that nothing else requires.

    These are shown for review but never removed automatically, because the
    install was your choice.
    """
    protected = PROTECTED | {norm(k) for k in keep}
    needed = required_names(env.packages)
    return [p for p in env.packages
            if p.requested and p.key not in needed and p.key not in protected]


def prune_plan(env: Environment, keep: list[str] | tuple = (), cascade: bool = True) -> list[Package]:
    """Packages to remove, in uninstall order.

    Only leftover dependencies are candidates: packages pip installed as a
    dependency (not requested) that no installed package requires any more.
    Requirements are always counted across every installed package, including
    the ones you requested, so a dependency of a package you keep is never
    flagged.

    With cascade, removing a leftover can leave its own dependencies orphaned,
    so the plan repeats until nothing new is found.
    """
    protected = PROTECTED | {norm(k) for k in keep}
    remaining = list(env.packages)
    plan: list[Package] = []
    while True:
        needed = required_names(remaining)
        found = [p for p in remaining
                 if not p.requested and p.key not in needed and p.key not in protected]
        if not found:
            break
        plan.extend(found)
        if not cascade:
            break
        gone = {p.key for p in found}
        remaining = [p for p in remaining if p.key not in gone]
    return plan


def uninstall(env: Environment, name: str) -> bool:
    """Uninstall with the environment's own pip. Returns True on success."""
    result = subprocess.run([env.python, "-m", "pip", "uninstall", "-y", name])
    return result.returncode == 0
