"""Build the private headless Godot exporter used by the Linux publication."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from linux_common import ROOT, run

TEMPLATE = "godot.linuxbsd.editor.x86_64.leanclr_m0.mono"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot-source", type=Path, default=ROOT / "extern/godot")
    parser.add_argument("--editor-dir", type=Path, default=Path("/opt/godot"))
    parser.add_argument("--out", type=Path, default=ROOT / "build/m1/exporter")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    godot = args.godot_source.resolve()
    editor_dir = args.editor_dir.resolve()
    out = args.out.resolve()
    godotsharp_source = editor_dir / "GodotSharp"
    if not (godotsharp_source / "Api/Debug/GodotSharp.dll").is_file():
        raise FileNotFoundError(f"official editor GodotSharp is missing: {godotsharp_source}")

    run(["python3", ROOT / "tools/prepare_m0_exporter.py"], log=ROOT / "build/m0/prepare-exporter.log")
    run(["scons", "-C", godot, "platform=linuxbsd", "target=editor", "arch=x86_64",
         "module_mono_enabled=yes", "modules_enabled_by_default=no",
         "module_gdscript_enabled=yes", "module_freetype_enabled=yes",
         "module_regex_enabled=yes", "module_svg_enabled=yes",
         "module_text_server_fb_enabled=yes", "vulkan=no", "opengl3=no",
         "accesskit=no", "debug_symbols=no", "optimize=none", "use_lto=no",
         f"extra_suffix=leanclr_m0", f"-j{args.jobs}"],
        log=ROOT / "build/m0/exporter-build.log")

    bin_dir = godot / "bin"
    shutil.copytree(godotsharp_source, bin_dir / "GodotSharp", dirs_exist_ok=True)
    (bin_dir / "._sc_").touch()
    run(["python3", "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); import build_assemblies; build_assemblies.generate_sdk_package_versions()",
         godot / "modules/mono/build_scripts"],
        log=ROOT / "build/m0/generate-sdk-metadata.log")
    run(["dotnet", "build", godot / "modules/mono/editor/GodotTools/GodotTools/GodotTools.csproj",
         "-c", "Debug", "--nologo",
         f"-p:GodotOutputDataDir={bin_dir / 'GodotSharp'}",
         f"-p:GodotApiAssembliesDir={bin_dir / 'GodotSharp/Api/Debug'}"],
        log=ROOT / "build/m0/godot-tools-build.log")

    candidates = sorted(bin_dir.glob("godot.linuxbsd.editor.*leanclr_m0*"))
    exporter = next((path for path in candidates if path.is_file() and not path.name.endswith(".log")), None)
    if exporter is None:
        raise FileNotFoundError(f"private exporter was not produced in {bin_dir}")

    if out.exists():
        shutil.rmtree(out)
    (out / "GodotSharp").parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exporter, out / exporter.name)
    (out / exporter.name).chmod(0o755)
    shutil.copytree(bin_dir / "GodotSharp", out / "GodotSharp")
    print("EXPORTER_LINUX_OK", out / exporter.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
