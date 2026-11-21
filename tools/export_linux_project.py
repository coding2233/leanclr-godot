"""Export a Godot project with the baked LeanCLR Linux template."""

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

    # The publication assemblies are separate, but the Godot export plugin and
    # the CSharpScript bridge still expect the project's development .NET
    # metadata. Build the original solution before staging so .godot/mono is
    # available, exactly like opening/building the project in the editor once.
    built = run([official, "--headless", "--editor", "--path", project,
                 "--build-solutions", "--quit"],
                log=work / "editor-build.log", check=False)
    if built.returncode != 0:
        print("editor solution build failed; continuing with existing .godot metadata", flush=True)

    stage = work / "project"
    shutil.copytree(project, stage, ignore=ignore)
    mono = project / ".godot/mono"
    if mono.is_dir():
        shutil.copytree(mono, stage / ".godot/mono", dirs_exist_ok=True)

    imported = run([official, "--headless", "--editor", "--path", stage, "--import"],
                   log=work / "import.log", check=False)
    if imported.returncode != 0:
        print("official editor import failed; retrying with the private exporter", flush=True)
        run([exporter, "--headless", "--editor", "--path", stage, "--import"],
            log=work / "import-exporter.log")

    artifact = output / "leanclr-game.x86_64"
    output.mkdir(parents=True, exist_ok=True)
    (stage / "export_presets.cfg").write_text(f'''[preset.0]
name="LeanCLR Linux"
platform="Linux"
runnable=true
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="{artifact.as_posix()}"

[preset.0.options]
custom_template/debug="{template.as_posix()}"
custom_template/release="{template.as_posix()}"
binary_format/architecture="x86_64"
binary_format/embed_pck=false
dotnet/include_scripts_content=false
''', encoding="utf-8")

    result = run([exporter, "--headless", "--path", stage,
                  "--export-release", "LeanCLR Linux", artifact],
                 env={"GODOT_LEANCLR_M0_STAGE": str(payload)},
                 log=work / "export.log", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"LeanCLR Linux export failed ({result.returncode}); see {work / 'export.log'}")
    if "LEANCLR_EXPORT_PAYLOAD_OK target=linux" not in result.stdout:
        raise RuntimeError("export did not accept the LeanCLR Linux payload")
    if not artifact.is_file():
        raise FileNotFoundError(f"export artifact is missing: {artifact}")
    print("EXPORT_LINUX_OK", artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
