"""Build the LeanCLR Linux exporter, template and generic publication assets."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from linux_common import ROOT, dotnet_build, read_json, run, sha256, write_json


def prepare(args) -> None:
    leanclr = ROOT / "extern/leanclr"
    if not (leanclr / "src/runtime/CMakeLists.txt").is_file():
        raise FileNotFoundError(
            "extern/leanclr is empty; initialize the submodule before building the image")

    run(["python3", ROOT / "tools/prepare_godot.py"], log=ROOT / "build/prepare-godot.log")
    run(["python3", ROOT / "tools/build_exporter_linux.py", "--jobs", str(args.jobs)],
        log=ROOT / "build/exporter.log")

    bcl = Path("/opt/dotnet/packs/win-x64/runtimes/win-x64/lib/net10.0")
    editor = next(Path("/opt/godot").glob("Godot_v*_mono_linux.x86_64"))
    run(["python3", ROOT / "tools/prepare_generic_managed.py", "--bcl", bcl, "--editor", editor],
        log=ROOT / "build/generic-managed.log")
    run(["python3", ROOT / "tools/prepare_m1_backend.py"], log=ROOT / "build/backend.log")

    managed_info_project = ROOT / "tools/managed-info/ManagedInfo.csproj"
    managed_info_output = ROOT / "build/m1/tools"
    dotnet_build(managed_info_project, output=managed_info_output, log=ROOT / "build/managed-info.log")
    if not (managed_info_output / "ManagedInfo.dll").is_file():
        raise FileNotFoundError("ManagedInfo.dll was not produced")


def assemble(args) -> None:
    out = args.out.resolve()
    leanclr = ROOT / "extern/leanclr"
    run(["python3", ROOT / "tools/build_native_linux.py", "--jobs", str(args.jobs)],
        log=ROOT / "build/native.log")
    run(["python3", ROOT / "tools/build_template_linux.py", "--jobs", str(args.jobs)],
        log=ROOT / "build/template.log")

    if out.exists():
        shutil.rmtree(out)
    (out / "templates/linux").mkdir(parents=True)
    (out / "exporter").mkdir(parents=True)
    (out / "managed/analyzers").mkdir(parents=True)
    (out / "licenses").mkdir(parents=True)
    (out / "bcl").mkdir(parents=True)

    bcl_source = Path("/opt/dotnet/packs/win-x64/runtimes/win-x64/lib/net10.0")
    if not (bcl_source / "System.Private.CoreLib.dll").is_file():
        raise FileNotFoundError(f"managed BCL is missing: {bcl_source}")
    shutil.copytree(bcl_source, out / "bcl/win-x64")

    shutil.copyfile(ROOT / "build/m1/templates/linux/linux_release.x86_64",
                    out / "templates/linux/linux_release.x86_64")
    exporter_source = ROOT / "build/m1/exporter"
    for entry in exporter_source.iterdir():
        destination = out / "exporter" / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination)
        else:
            shutil.copyfile(entry, destination)
            destination.chmod(0o755)
    shutil.copyfile(ROOT / "build/m1/managed/GodotSharp.dll", out / "managed/GodotSharp.dll")
    shutil.copyfile(ROOT / "build/m1/managed/analyzers/Godot.SourceGenerators.dll",
                    out / "managed/analyzers/Godot.SourceGenerators.dll")
    shutil.copyfile(ROOT / "build/m1/tools/ManagedInfo.dll", out / "managed/ManagedInfo.dll")
    shutil.copyfile(ROOT / "dependencies.json", out / "dependencies.json")

    godot = ROOT / "extern/godot"
    licenses = {
        "Godot-LICENSE.txt": godot / "LICENSE.txt",
        "Godot-COPYRIGHT.txt": godot / "COPYRIGHT.txt",
        "LeanCLR-LICENSE.txt": leanclr / "LICENSE",
        "DotNET-LICENSE.txt": Path("/usr/lib/dotnet/LICENSE.txt"),
        "DotNET-ThirdPartyNotices.txt": Path("/usr/lib/dotnet/ThirdPartyNotices.txt"),
    }
    for name, source in licenses.items():
        if source.is_file():
            shutil.copyfile(source, out / "licenses" / name)

    profile = read_json(ROOT / "build/m1/profile.json")
    profile["template_sha256"] = sha256(out / "templates/linux/linux_release.x86_64")
    exporter = next((path for path in (out / "exporter").iterdir()
                     if path.is_file() and "leanclr_m0" in path.name), None)
    if exporter is None:
        raise FileNotFoundError("private exporter is missing from the image artifacts")
    profile["exporter"] = "exporter/" + exporter.name
    profile["template"] = "templates/linux/linux_release.x86_64"
    profile["targets"] = {
        "linux": {
            "template": "templates/linux/linux_release.x86_64",
            "bcl": "bcl/win-x64",
            "phase": "M1-linux-demo",
            "manifest_target": "linux",
            "pointer_bits": 64,
            "real_bits": 32,
        },
    }
    write_json(out / "profile.json", profile)
    print("LEANCLR_LINUX_IMAGE_OK", out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("/opt/leanclr"))
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--step", choices=["prepare", "linux", "all"], default="all")
    args = parser.parse_args()

    if args.step in {"prepare", "all"}:
        prepare(args)
    if args.step in {"linux", "all"}:
        assemble(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
