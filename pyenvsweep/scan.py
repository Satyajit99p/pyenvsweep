"""Find Python environments on disk and read the distributions installed in each."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

PRUNE_DIRS = {"node_modules", ".git", "__pycache__"}

# Runs inside each interpreter, so it reads that environment's own site-packages.
INSPECT = r'''
import json, re, sys, importlib.metadata as md
from pathlib import Path
packages = {}
for d in md.distributions():
    name = d.metadata["Name"]
    if not name:
        continue
    key = re.sub(r"[-_.]+", "-", name).lower()
    if key in packages:
        continue
    size = 0
    for f in d.files or []:
        try:
            size += Path(d.locate_file(f)).stat().st_size
        except OSError:
            pass
    packages[key] = {
        "name": name,
        "version": d.version,
        "size": size,
        "requires": list(d.requires or []),
        "location": str(d.locate_file("")),
        # pip writes a REQUESTED file only for packages installed directly,
        # not for their dependencies.
        "requested": d.read_text("REQUESTED") is not None,
    }
print(json.dumps({
    "python": sys.executable,
    "prefix": sys.prefix,
    "is_base": sys.prefix == sys.base_prefix,
    "packages": list(packages.values()),
}))
'''


def norm(name: str) -> str:
    """PEP 503 name normalisation: 'Foo_Bar.baz' -> 'foo-bar-baz'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def req_name(requirement: str) -> str | None:
    """Return the normalised package name from a Requires-Dist string."""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return norm(m.group(1)) if m else None


@dataclass
class Package:
    name: str
    version: str
    size: int
    location: str
    requires: list[str] = field(default_factory=list)
    requested: bool = False  # installed directly by you, not as a dependency

    @property
    def key(self) -> str:
        return norm(self.name)


@dataclass
class Environment:
    python: str
    prefix: str
    is_base: bool
    packages: list[Package] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(p.size for p in self.packages)


def find_venv_pythons(roots: list[Path]) -> list[str]:
    """Find interpreters of every venv (a folder with pyvenv.cfg) under the roots."""
    exe = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    found: set[str] = set()
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
            if "pyvenv.cfg" in filenames:
                # Do not resolve(): on some installs the venv interpreter is a
                # link, and resolving it would point at the global Python.
                found.add(str(Path(dirpath) / exe))
                dirnames[:] = []  # a venv's own folders are not searched
    return sorted(p for p in found if Path(p).exists())


def _inspect(python: str) -> dict | None:
    try:
        r = subprocess.run([python, "-c", INSPECT], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except ValueError:
        return None


def scan(roots: list[Path], include_base: bool = True,
         confirm: Callable[[list[str]], None] | None = None) -> list[Environment]:
    """Inspect every venv under the roots (and optionally the global Python).

    `confirm` is called with the discovered interpreters before any is run, and
    may abort (e.g. via sys.exit) to stop the scan.
    """
    pythons = find_venv_pythons(roots)
    if pythons and confirm:
        confirm(pythons)
    if include_base:
        pythons.append(sys.executable)
    envs: list[Environment] = []
    seen: set[str] = set()
    for python in pythons:
        data = _inspect(python)
        if data is None or data["prefix"] in seen:
            continue
        seen.add(data["prefix"])
        envs.append(Environment(
            python=data["python"],
            prefix=data["prefix"],
            is_base=data["is_base"],
            packages=[Package(**p) for p in data["packages"]],
        ))
    envs.sort(key=lambda e: -e.size)
    return envs
