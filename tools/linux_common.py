"""Shared helpers for the Linux LeanCLR image build and project publication."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command, *, cwd=None, env=None, log=None, check=True):
    command = [str(part) for part in command]
    merged = dict(os.environ)
    if env:
        merged.update(env)
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=cwd, env=merged, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(log).write_text(result.stdout, encoding="utf-8")
    if result.stdout:
        sys.stdout.write(result.stdout)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def sha256(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def copy_tree(source, destination, *, ignore=None):
    source = Path(source)
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=ignore)


def find_first(paths, description):
    for path in paths:
        if Path(path).is_file():
            return Path(path)
    raise FileNotFoundError(f"missing {description}: " + ", ".join(map(str, paths)))


def dotnet_build(project, *, output=None, configuration="Release", properties=None, log=None):
    command = ["dotnet", "build", str(project), "-c", configuration, "--nologo"]
    if output:
        command += ["-o", str(output)]
    for key, value in (properties or {}).items():
        command.append(f"-p:{key}={value}")
    return run(command, log=log)
