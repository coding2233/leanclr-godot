"""Export a Godot project with the baked LeanCLR Web template."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from linux_common import run

IGNORED = {".godot", ".git", ".nuget", "bin", "obj", "out", "build"}


def ignore(directory, names):
    return {name for name in names if name in IGNORED}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--exporter", type=Path, required=True)
    parser.add_argument("--official-editor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=["web", "linux"], default="web")
    args = parser.parse_args()

    project = args.project.resolve()
    work = args.work.resolve()
    payload = args.payload.resolve()
    template = args.template.resolve()
    exporter = args.exporter.resolve()
    official = args.official_editor.resolve()
    output = args.output.resolve()
    for path in (project / "project.godot", template, exporter, official, payload / "manifest.json"):
        if not path.is_file():
            raise FileNotFoundError(f"missing export input: {path}")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"export output is not empty: {output}")

    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    stage = work / "project"
    shutil.copytree(project, stage, ignore=ignore)

    # The C# export plugin expects the project's development .NET metadata.
    # Build it once in the source project so the Web exporter can pass its
    # solution/assembly checks; the shipped runtime still comes from the
    # LeanCLR payload and Web template.
    built = run([official, "--headless", "--editor", "--path", project,
                 "--build-solutions", "--quit"],
                log=work / "editor-build.log", check=False)
    if built.returncode != 0:
        print("editor solution build failed; continuing with existing metadata", flush=True)
    mono = project / ".godot/mono"
    if mono.is_dir():
        shutil.copytree(mono, stage / ".godot/mono", dirs_exist_ok=True)

    imported = run([official, "--headless", "--editor", "--path", stage, "--import"],
                   log=work / "import.log", check=False)
    if imported.returncode != 0:
        print("official editor import failed; retrying with the private exporter", flush=True)
        run([exporter, "--headless", "--editor", "--path", stage, "--import"],
            log=work / "import-exporter.log")

    output.mkdir(parents=True, exist_ok=True)
    if args.target == "web":
        preset_name = "LeanCLR Web"
        platform = "Web"
        artifact = output / "index.html"
        options = f'''custom_template/debug="{template.as_posix()}"
custom_template/release="{template.as_posix()}"
binary_format/architecture="wasm32"
variant/thread_support=false
variant/extensions_support=false
html/export_icon=false
progressive_web_app/enabled=false
dotnet/include_scripts_content=false'''
        marker = "LEANCLR_EXPORT_PAYLOAD_OK target=wasm"
    else:
        preset_name = "LeanCLR Linux"
        platform = "Linux"
        artifact = output / "leanclr-game.x86_64"
        options = f'''custom_template/debug="{template.as_posix()}"
custom_template/release="{template.as_posix()}"
binary_format/architecture="x86_64"
binary_format/embed_pck=false
dotnet/include_scripts_content=false'''
        marker = "LEANCLR_EXPORT_PAYLOAD_OK target=linux"
    (stage / "export_presets.cfg").write_text(f'''[preset.0]
name="{preset_name}"
platform="{platform}"
runnable=true
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="{artifact.as_posix()}"

[preset.0.options]
{options}
''', encoding="utf-8")

    result = run([exporter, "--headless", "--path", stage,
                  "--export-release", preset_name, artifact],
                 env={"GODOT_LEANCLR_M0_STAGE": str(payload)},
                 log=work / "export.log", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"LeanCLR {platform} export failed ({result.returncode}); see {work / 'export.log'}")
    if marker not in result.stdout:
        raise RuntimeError(f"export did not accept the LeanCLR {platform} payload")
    if not artifact.is_file():
        raise FileNotFoundError(f"export artifact is missing: {artifact}")
    if args.target == "web":
        html = artifact.read_text(encoding="utf-8")
        anchor = "const engine = new Engine(GODOT_CONFIG);"
        if html.count(anchor) != 1:
            raise RuntimeError("unexpected Godot Web HTML shell")
        html = html.replace(anchor,
            "if (new URLSearchParams(location.search).has('smoke')) GODOT_CONFIG.args.push('--audio-driver', 'Dummy', '--', '--m0-smoke');\n" + anchor)
        artifact.write_text(html, encoding="utf-8")
        print("EXPORT_WEB_OK", artifact)
    else:
        print("EXPORT_LINUX_OK", artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
