"""Build publication assemblies and the LeanCLR payload for a mounted Godot project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from linux_common import dotnet_build, read_json, run, sha256, write_json

IGNORED_PARTS = {".godot", ".git", "bin", "obj", "__pycache__"}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def project_items(csproj: Path, item_type: str) -> list[dict[str, str]]:
    tree = ET.parse(csproj)
    items = []
    for element in tree.iter():
        if local_name(element.tag) != item_type:
            continue
        include = element.attrib.get("Include")
        if include:
            items.append({"include": include, "element": element})
    return items


def find_main_project(project: Path) -> tuple[Path, str]:
    config = project / "project.godot"
    if not config.is_file():
        raise FileNotFoundError(f"not a Godot project: {config}")
    match = re.search(r'project/assembly_name\s*=\s*"([^"]+)"', config.read_text(encoding="utf-8"))
    assembly = match.group(1) if match else project.name
    candidate = project / f"{assembly}.csproj"
    if candidate.is_file():
        return candidate, assembly
    projects = sorted(project.glob("*.csproj"))
    if not projects:
        raise FileNotFoundError(f"no C# project found in {project}")
    return projects[0], projects[0].stem


def collect_sources(project: Path, destination: Path) -> int:
    count = 0
    for source in project.rglob("*.cs"):
        relative = source.relative_to(project)
        if IGNORED_PARTS.intersection(relative.parts):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        count += 1
    if count == 0:
        raise RuntimeError(f"no C# sources found in {project}")
    return count


def build_references(csproj: Path, work: Path) -> list[Path]:
    outputs = []
    local_nupkgs = "/opt/godot/GodotSharp/Tools/nupkgs"
    for index, item in enumerate(project_items(csproj, "ProjectReference")):
        reference = (csproj.parent / item["include"].replace("\\", "/")).resolve()
        if not reference.is_file():
            raise FileNotFoundError(f"project reference is missing: {reference}")
        destination = work / "deps" / f"{index:02d}-{reference.stem}"
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        dotnet_build(reference, output=destination, log=work / f"reference-{reference.stem}.log",
                     properties={"TargetFramework": "net10.0",
                                 "RestoreAdditionalProjectSources": local_nupkgs})
        outputs.extend(sorted(destination.glob("*.dll")))
    return outputs


def package_references(csproj: Path) -> list[str]:
    values = []
    for item in project_items(csproj, "PackageReference"):
        include = item["include"]
        if include in {"GodotSharp", "GodotSharpEditor"}:
            continue
        version = item["element"].attrib.get("Version")
        if version:
            values.append(f'<PackageReference Include="{include}" Version="{version}" />')
        else:
            values.append(f'<PackageReference Include="{include}" />')
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--generic", type=Path, required=True)
    parser.add_argument("--managed-info", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--bcl", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    project = args.project.resolve()
    work = args.work.resolve()
    generic = args.generic.resolve()
    profile = read_json(args.profile)
    dependencies = read_json(args.dependencies)
    bcl = args.bcl.resolve()
    out = args.out.resolve()
    if not (bcl / "System.Private.CoreLib.dll").is_file():
        raise FileNotFoundError(f"managed BCL is missing: {bcl}")
    godotsharp = generic / "GodotSharp.dll"
    source_generator = generic / "analyzers/Godot.SourceGenerators.dll"
    if not godotsharp.is_file() or not source_generator.is_file():
        raise FileNotFoundError("generic publication assemblies are missing")
    if profile.get("target") != "linux":
        raise RuntimeError(f"template profile targets {profile.get('target')}, not linux")
    if sha256(godotsharp) != profile.get("godotsharp_sha256"):
        raise RuntimeError("GodotSharp does not match the baked template profile")

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    restore_property = {
        "RestoreAdditionalProjectSources": "/opt/godot/GodotSharp/Tools/nupkgs",
    }
    game = work / "game"
    game.mkdir(parents=True)
    csproj, assembly = find_main_project(project)
    sources = collect_sources(project, game)
    dep_dlls = [
        dll for dll in build_references(csproj, work)
        if dll.stem not in {"GodotSharp", "GodotSharpEditor"}
    ]
    packages = package_references(csproj)

    references = [f'<Reference Include="GodotSharp"><HintPath>{godotsharp.as_posix()}</HintPath></Reference>']
    for dll in dep_dlls:
        references.append(f'<Reference Include="{dll.stem}"><HintPath>{dll.as_posix()}</HintPath></Reference>')
    (game / f"{assembly}.csproj").write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework><AssemblyName>{assembly}</AssemblyName>
    <GodotProjectDir>{game.as_posix()}/</GodotProjectDir><AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="**/*.cs" Exclude="obj/**;bin/**" />
    <Analyzer Include="{source_generator.as_posix()}" />
    <CompilerVisibleProperty Include="GodotProjectDir" />
    <AssemblyMetadata Include="M0Revision" Value="1" />
    {''.join(references)}
    {''.join(packages)}
  </ItemGroup>
</Project>''', encoding="utf-8")
    dotnet_build(game / f"{assembly}.csproj", log=work / "game-build.log",
                 properties=restore_property)
    game_dll = game / f"bin/Release/net10.0/{assembly}.dll"
    if not game_dll.is_file():
        raise RuntimeError("project publication assembly was not produced")

    bootstrap = work / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generic / "Bootstrap.cs", bootstrap / "Bootstrap.cs")
    scripts = json.loads(run(["dotnet", args.managed_info, "--scripts", game_dll]).stdout)
    registration = ["namespace LeanClr { public static partial class Bootstrap { static partial void RegisterScripts() {"]
    for script in scripts:
        factory = "null" if script["abstractType"] else "() => new global::" + script["type"] + "()"
        registration.append(
            f'Godot.Bridge.ScriptManagerBridge.RegisterPublishedScript(typeof(global::{script["type"]}), {json.dumps(script["path"])}, {factory});')
    registration.append("} } }")
    (bootstrap / "Registration.cs").write_text("\n".join(registration), encoding="utf-8")
    bootstrap_references = references + [f'<Reference Include="{assembly}"><HintPath>{game_dll.as_posix()}</HintPath></Reference>']
    (bootstrap / "Bootstrap.csproj").write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework><AssemblyName>LeanClr.Bootstrap</AssemblyName>
    <AllowUnsafeBlocks>true</AllowUnsafeBlocks>
  </PropertyGroup>
  <ItemGroup>
    {''.join(bootstrap_references)}
  </ItemGroup>
</Project>''', encoding="utf-8")
    dotnet_build(bootstrap / "Bootstrap.csproj", log=work / "bootstrap-build.log",
                 properties=restore_property)
    bootstrap_dll = bootstrap / "bin/Release/net10.0/LeanClr.Bootstrap.dll"
    if not bootstrap_dll.is_file():
        raise RuntimeError("LeanClr.Bootstrap.dll was not produced")

    roots = [game_dll, bootstrap_dll, godotsharp, *dep_dlls]
    closure = json.loads(run(["dotnet", args.managed_info, bcl, *roots]).stdout)
    corelib = next((item for item in closure if item["name"] == "System.Private.CoreLib"), None)
    if corelib is None:
        raise RuntimeError("CoreLib was not resolved")
    if corelib["sha256"] != dependencies["corelib"]["native_sha256"]:
        raise RuntimeError(f"unexpected CoreLib {corelib['sha256']}")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files = []
    for item in closure:
        name = item["name"] + ".dll.bytes"
        shutil.copyfile(item["path"], out / name)
        files.append({"path": "res://.leanclr/" + name, "source": name, "sha256": item["sha256"]})
    license_map = {
        "LeanCLR-LICENSE.txt": "LeanCLR-LICENSE.txt",
        "Godot-LICENSE.txt": "Godot-LICENSE.txt",
        "Godot-COPYRIGHT.txt": "Godot-COPYRIGHT.txt",
        "DotNET-LICENSE.txt": "DotNET-LICENSE.txt",
        "DotNET-ThirdPartyNotices.txt": "DotNET-ThirdPartyNotices.txt",
    }
    for target, source in license_map.items():
        path = args.licenses / source
        if not path.is_file():
            continue
        data = path.read_bytes()
        (out / target).write_bytes(data)
        files.append({"path": "res://.leanclr/" + target, "source": target, "sha256": sha256(path)})

    manifest = {
        "phase": "M1-linux-demo",
        "runtime_ready": True,
        "target": "linux",
        "godot_commit": dependencies["godot"]["commit"],
        "leanclr_commit": dependencies["leanclr"]["commit"],
        "profile": "linux-x64-leanclr",
        "pointer_bits": 64,
        "real_bits": 32,
        "calli_sha256": profile["calli_sha256"],
        "files": files,
    }
    write_json(out / "manifest.json", manifest)
    write_json(work / "publication.json", {
        "project": str(project),
        "assembly": assembly,
        "sources": sources,
        "references": [str(path) for path in dep_dlls],
        "assemblies": closure,
        "payload": str(out),
        "manifest": manifest,
    })
    print(json.dumps({"payload": str(out), "game": str(game_dll), "manifest": str(out / "manifest.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
