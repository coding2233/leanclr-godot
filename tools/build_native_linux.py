"""Build the LeanCLR Linux native runtime and calli bridge static libraries."""

from __future__ import annotations

import argparse
from pathlib import Path

from linux_common import ROOT, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leanclr-source", type=Path, default=ROOT / "extern/leanclr")
    parser.add_argument("--calli", type=Path, default=ROOT / "build/m1/calli")
    parser.add_argument("--build", type=Path, default=ROOT / "build/m1/runtime-linux")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()

    source = args.leanclr_source.resolve()
    calli = args.calli.resolve()
    build = args.build.resolve()
    if not (calli / "calli_bridges.cpp").is_file():
        raise FileNotFoundError(f"calli bridge sources are missing: {calli}")

    run(["cmake", "-S", ROOT / "native/m1", "-B", build, "-G", "Ninja",
         "-DCMAKE_BUILD_TYPE=Release",
         f"-DLEANCLR_SOURCE_DIR={source}"], log=ROOT / "build/m1/native-configure.log")
    run(["cmake", "--build", build, "--parallel", str(args.jobs)],
        log=ROOT / "build/m1/native-build.log")

    calli_lib = build / "libleanclr-godot-calli.a"
    runtime_lib = build / "runtime/libleanclr.a"
    for path in (calli_lib, runtime_lib):
        if not path.is_file():
            raise FileNotFoundError(f"native library was not produced: {path}")
    print("NATIVE_LINUX_OK", build)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
