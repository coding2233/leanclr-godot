"""Build the LeanCLR Web (wasm32, no threads) export template."""

from __future__ import annotations

import argparse
import shlex
import shutil
from pathlib import Path

from linux_common import ROOT, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot-source", type=Path, default=ROOT / "extern/godot")
    parser.add_argument("--runtime-dir", type=Path, default=ROOT / "build/m1/runtime-web")
    parser.add_argument("--leanclr-source", type=Path, default=ROOT / "extern/leanclr")
    parser.add_argument("--out", type=Path, default=ROOT / "build/m1/templates/web")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    godot = args.godot_source.resolve()
    runtime = args.runtime_dir.resolve()
    leanclr = args.leanclr_source.resolve()
    out = args.out.resolve()
    for path in (runtime / "libleanclr-godot-calli.a", runtime / "runtime/libleanclr.a"):
        if not path.is_file():
            raise FileNotFoundError(f"native library is missing: {path}")

    run(["python3", ROOT / "tools/prepare_portable_backend.py"],
        log=ROOT / "build/portable-backend.log")
    environment = {
        "LEANCLR_GODOT_RUNTIME": str(runtime),
        "LEANCLR_GODOT_SOURCE": str(leanclr),
    }
    scons = shlex.join(["scons", "-C", str(godot), "platform=web", "target=template_release", "arch=wasm32",
                        "module_mono_enabled=yes", "modules_enabled_by_default=no",
                        "module_gdscript_enabled=yes", "module_freetype_enabled=yes",
                        "module_svg_enabled=yes", "module_text_server_fb_enabled=yes",
                        "module_godot_physics_2d_enabled=yes", "threads=no", "dlink_enabled=no",
                        "initial_memory=128", "debug_symbols=no", "optimize=none", "use_lto=no",
                        "extra_suffix=leanclr_m3", f"-j{args.jobs}"])
    run(["bash", "-lc", "source /opt/emsdk/emsdk_env.sh >/dev/null; exec " + scons],
        env=environment, log=ROOT / "build/m1/template-web-build.log")

    candidates = sorted((godot / "bin").glob("godot.web.template_release.*leanclr_m3*.zip"))
    template = next((path for path in candidates if path.is_file()), None)
    if template is None:
        raise FileNotFoundError("LeanCLR Web template was not produced")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "web_nothreads_release.zip"
    shutil.copyfile(template, target)
    print("TEMPLATE_WEB_OK", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
