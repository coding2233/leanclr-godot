"""Build the LeanCLR portable native runtime used by the Web template."""

from __future__ import annotations

import argparse
from pathlib import Path

from linux_common import ROOT, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leanclr-source", type=Path, default=ROOT / "extern/leanclr")
    parser.add_argument("--build", type=Path, default=ROOT / "build/m1/runtime-web")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    source = args.leanclr_source.resolve()
    build = args.build.resolve()
    run(["emcmake", "cmake", "-S", ROOT / "native/m1", "-B", build, "-G", "Ninja",
         "-DCMAKE_BUILD_TYPE=Release",
         f"-DLEANCLR_SOURCE_DIR={source}"], log=ROOT / "build/m1/native-web-configure.log")
    run(["cmake", "--build", build, "--parallel", str(args.jobs)],
        log=ROOT / "build/m1/native-web-build.log")
    for path in (build / "libleanclr-godot-calli.a", build / "runtime/libleanclr.a"):
        if not path.is_file():
            raise FileNotFoundError(f"native library was not produced: {path}")
    print("NATIVE_WEB_OK", build)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
