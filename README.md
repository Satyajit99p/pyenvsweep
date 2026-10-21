# pyenvsweep

List, audit and remove packages across all Python environments on your machine.

Over time every project gets its own virtual environment, and each one carries its own copy of numpy, pandas, torch and friends. `pyenvsweep` finds all of them, shows where the space went, and helps you clean up leftover dependencies. It never removes anything unless you add `--yes`.

## Features

- Finds every virtual environment (any folder containing `pyvenv.cfg`) under the folders you choose, plus your global Python.
- Shows each environment's size and package count.
- Shows which packages are installed in more than one environment.
- Detects leftover dependencies: packages installed only to support something you have since uninstalled.
- Uninstalls one package or all leftovers, using each environment's own `pip`.
- Dry run by default, with protection for `pip`, `setuptools` and `wheel`.

## Requirements

- Python 3.9 or newer
- No third-party dependencies
- `pip` inside each environment you want to remove packages from

## Installation

```powershell
git clone https://github.com/Satyajit99p/pyenvsweep.git
cd pyenvsweep
pip install -e .
```

Or run it without installing, from the project folder:

```powershell
python -m pyenvsweep <command>
```

## Usage

```
pyenvsweep [--root PATH] [--no-base] [--trust] <command> [options]
```

### Global options

Global options go **before** the command name.

| Option | Description |
|---|---|
| `--root PATH` | Folder to search for virtual environments. Repeatable. Defaults to your home folder, which can be slow, so a narrower path is better. |
| `--no-base` | Skip the global Python. |
| `--trust` | Do not ask before running discovered interpreters. Required when running non-interactively (scripts, cron, CI). |

### Commands

| Command | Description |
|---|---|
| `envs` | List every environment with its size, package count, type and path. |
| `packages` | List packages across all environments, or in one environment with `--env`. |
| `prune` | Find leftover dependencies and optionally uninstall them. |
| `remove NAME` | Uninstall one package from one environment. |

`--env TEXT` takes part of an environment's path (case-insensitive). It must match exactly one environment. Otherwise the tool lists the matches and exits.

## Examples

### See what you have

```console
$ pyenvsweep --root D:\projects envs
#  size       packages  type    path
-  ---------  --------  ------  ---------------------------------------
1  1820.4 MB  142       venv    D:\projects\python projects\churn modelling\venv
2  610.2 MB   58        venv    D:\projects\ATS parser\venv
3  95.7 MB    21        venv    D:\projects\Job Scraper\.venv

Total: 2526.3 MB across 3 environments
```

(Sizes and paths above are illustrative.)

### Find packages that are installed several times

```powershell
pyenvsweep --root D:\projects packages --duplicates
```

Lists only packages present in more than one environment, with the versions in use, how many environments have each, and the total size. It ends with how much space the extra copies take.

Duplicates across environments are normal, because each environment needs its own copy. Use this to decide which environments are worth keeping, not as a list of things to delete.

### Inspect one environment

```powershell
pyenvsweep --root D:\projects packages --env "churn modelling"
```

Lists that environment's packages, largest first, with version, size and install location.

### Clean up leftover dependencies

Start with a dry run. This is the default and removes nothing:

```powershell
pyenvsweep --root D:\projects prune --env "ATS parser"
```

The output has two lists:

1. **Installed by you and used by nothing else.** Shown for review only. These are never removed automatically.
2. **Leftover dependencies.** Packages installed as a dependency of something that is gone, listed in uninstall order.

If the second list looks right, run it for real:

```powershell
pyenvsweep --root D:\projects prune --env "ATS parser" --yes
```

Protect a package the tool wrongly flagged, for example one you import but never declared as a dependency:

```powershell
pyenvsweep --root D:\projects prune --env "ATS parser" --keep requests --keep pyyaml --yes
```

Only look at the first round of orphans, without following the chain:

```powershell
pyenvsweep --root D:\projects prune --env "ATS parser" --no-cascade
```

### Remove a single package

```powershell
pyenvsweep --root D:\projects remove numpy --env "Job Scraper"          # dry run
pyenvsweep --root D:\projects remove numpy --env "Job Scraper" --yes    # uninstall
```

If other installed packages require it, the tool refuses and names them. `--force` overrides that, but can leave the environment broken.

### Run without prompts

```powershell
pyenvsweep --root D:\projects --trust envs
```

## Safety

- **Dry run by default.** `prune` and `remove` only uninstall when you pass `--yes`.
- **Interpreters are executed.** To read an environment's packages, `pyenvsweep` runs that environment's `python`, which runs code from that folder. It lists what it found and asks first. Point `--root` only at folders you trust, and only use `--trust` once you have reviewed them.
- **Uninstalls cannot be undone.** Before using `--yes`, save a snapshot of the environment:
  ```powershell
  D:\path\to\venv\Scripts\python.exe -m pip freeze > backup.txt
  ```
  Restore later with `pip install -r backup.txt`.
- **Protected packages.** `pip`, `setuptools`, `wheel` and `pyenvsweep` are never offered for removal.
- **Global Python.** The tool warns before changing it, but does not stop you. Removing packages there can break other tools.

## How it decides what is a leftover

A package is a leftover dependency when **both** are true:

1. pip did not record it as installed directly (it has no `REQUESTED` marker in its metadata), so it arrived as a dependency.
2. No installed package lists it as a requirement. Requirements behind optional extras count, so a package used only by an extra is not flagged.

This relies on pip's metadata. Environments managed by other tools (conda, Poetry, system packages) or packages installed with `--no-deps` may not have the marker, so always read the dry-run output before using `--yes`.

## Limitations

- Packages that your code imports but that are not declared as a dependency of anything may be flagged. Use `--keep`.
- Sizes only count files listed in each package's metadata, so they are approximate.
- Environments created by `uv` often contain no `pip`, so uninstalls there report `FAILED`. Use `uv pip uninstall --python <path-to-python> NAME` instead.
- Scanning is sequential. A large `--root`, or the default home folder, can take a while.

