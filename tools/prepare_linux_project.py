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


def retarget_reference(reference: Path, destination: Path) -> Path:
    source = destination / "source"
    shutil.copytree(reference.parent, source, ignore=shutil.ignore_patterns(
        ".git", ".godot", "bin", "obj", ".vs", "__pycache__"))
    project = source / reference.name
    text = project.read_text(encoding="utf-8")
    text = re.sub(r"<TargetFramework>[^<]*</TargetFramework>",
                  "<TargetFramework>net10.0</TargetFramework>", text, count=1)
    text = re.sub(r"<TargetFrameworks>[^<]*</TargetFrameworks>",
                  "<TargetFramework>net10.0</TargetFramework>", text, count=1)
    if "<TargetFramework>" not in text:
        text = text.replace("<PropertyGroup>",
                            "<PropertyGroup><TargetFramework>net10.0</TargetFramework>", 1)
    text = text.replace(
        "</Project>",
        '<ItemGroup><FrameworkReference Update="Microsoft.NETCore.App" TargetingPackVersion="10.0.8" /></ItemGroup>\n</Project>')
    project.write_text(text, encoding="utf-8")
    return project


def build_references(csproj: Path, work: Path) -> list[dict]:
    entries = []
    local_nupkgs = "/opt/leanclr/exporter/GodotSharp/Tools/nupkgs"
    for index, item in enumerate(project_items(csproj, "ProjectReference")):
        reference = (csproj.parent / item["include"].replace("\\", "/")).resolve()
        if not reference.is_file():
            raise FileNotFoundError(f"project reference is missing: {reference}")
        destination = work / "deps" / f"{index:02d}-{reference.stem}"
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        try:
            # Retarget a copy so the project's own assets file is never forced
            # to a target framework it was not restored for.
            project = retarget_reference(reference, destination)
            dotnet_build(project, output=destination,
                         log=work / f"reference-{reference.stem}.log",
                         properties={"RestoreAdditionalProjectSources": local_nupkgs})
        except RuntimeError:
            shutil.rmtree(destination)
            destination.mkdir(parents=True)
            project = reference
            dotnet_build(project, output=destination,
                         log=work / f"reference-{reference.stem}-original.log",
                         properties={"RestoreAdditionalProjectSources": local_nupkgs})
        for dll in sorted(destination.glob("*.dll")):
            entries.append({"dll": dll, "project": project})
    return entries


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


def managed_info_command(work: Path, managed_info: Path, *arguments: Path | str) -> list[str]:
    runtimeconfig = work / "ManagedInfo.runtimeconfig.json"
    if not runtimeconfig.is_file():
        runtimeconfig.write_text(json.dumps({
            "runtimeOptions": {
                "tfm": "net10.0",
                "framework": {"name": "Microsoft.NETCore.App", "version": "10.0.0"},
                "rollForward": "LatestMinor",
            }
        }, indent=2) + "\n", encoding="utf-8")
    return ["dotnet", "exec", "--runtimeconfig", str(runtimeconfig), str(managed_info),
            *map(str, arguments)]


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
    parser.add_argument("--target", choices=["web", "linux"], default="web")
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
    target = args.target
    target_info = profile.get("targets", {}).get(target)
    if target_info is None:
        raise RuntimeError(f"template profile does not provide target {target}")
    if sha256(godotsharp) != profile.get("godotsharp_sha256"):
        raise RuntimeError("GodotSharp does not match the baked template profile")

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    restore_property = {
        "RestoreAdditionalProjectSources": "/opt/leanclr/exporter/GodotSharp/Tools/nupkgs",
    }
    game = work / "game"
    game.mkdir(parents=True)
    csproj, assembly = find_main_project(project)
    sources = collect_sources(project, game)
    dep_entries = build_references(csproj, work)
    dep_dlls = [
        entry["dll"] for entry in dep_entries
        if entry["dll"].stem not in {"GodotSharp", "GodotSharpEditor"}
    ]
    print("PUBLICATION_REFERENCES",
          [{"dll": str(entry["dll"]), "project": str(entry["project"])} for entry in dep_entries],
          flush=True)
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
  <ItemGroup><FrameworkReference Update="Microsoft.NETCore.App" TargetingPackVersion="10.0.8" /></ItemGroup>
</Project>''', encoding="utf-8")
    dotnet_build(game / f"{assembly}.csproj", log=work / "game-build.log",
                 properties=restore_property)
    game_dll = game / f"bin/Release/net10.0/{assembly}.dll"
    if not game_dll.is_file():
        raise RuntimeError("project publication assembly was not produced")

    bootstrap = work / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(generic / "Bootstrap.cs", bootstrap / "Bootstrap.cs")
    scripts = json.loads(run(managed_info_command(work, args.managed_info, "--scripts", game_dll)).stdout)
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
  <ItemGroup><FrameworkReference Update="Microsoft.NETCore.App" TargetingPackVersion="10.0.8" /></ItemGroup>
</Project>''', encoding="utf-8")
    dotnet_build(bootstrap / "Bootstrap.csproj", log=work / "bootstrap-build.log",
                 properties=restore_property)
    bootstrap_dll = bootstrap / "bin/Release/net10.0/LeanClr.Bootstrap.dll"
    if not bootstrap_dll.is_file():
        raise RuntimeError("LeanClr.Bootstrap.dll was not produced")

    roots = [game_dll, bootstrap_dll, godotsharp, *dep_dlls]
    closure = json.loads(run(managed_info_command(work, args.managed_info, bcl, *roots)).stdout)
    corelib = next((item for item in closure if item["name"] == "System.Private.CoreLib"), None)
    if corelib is None:
        raise RuntimeError("CoreLib was not resolved")
    corelib_hash = dependencies["corelib"]["wasm_sha256" if target == "web" else "native_sha256"]
    if corelib["sha256"] != corelib_hash:
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
        "phase": target_info["phase"],
        "runtime_ready": True,
        "target": target_info["manifest_target"],
        "godot_commit": dependencies["godot"]["commit"],
        "leanclr_commit": dependencies["leanclr"]["commit"],
        "profile": f"{target}-leanclr",
        "pointer_bits": target_info["pointer_bits"],
        "real_bits": target_info["real_bits"],
        "calli_sha256": profile["calli_sha256"],
        "files": files,
    }
    write_json(out / "manifest.json", manifest)
    write_json(work / "publication.json", {
        "project": str(project),
        "assembly": assembly,
        "sources": sources,
        "target": target,
        "references": [str(path) for path in dep_dlls],
        "assemblies": closure,
        "payload": str(out),
        "manifest": manifest,
    })
    print(json.dumps({"payload": str(out), "game": str(game_dll), "manifest": str(out / "manifest.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
