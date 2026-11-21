"""Package prebuilt LeanCLR release assets for GitHub Release and the slim image."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tarfile
import zipfile

from linux_common import ROOT, read_json, sha256, write_json


def add_tree(tar: tarfile.TarFile, source: Path, arcname: str) -> None:
    for path in sorted(source.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        member = tar.gettarinfo(str(path), arcname + "/" + path.relative_to(source).as_posix())
        if path.is_file():
            with path.open("rb") as handle:
                tar.addfile(member, handle)
        else:
            tar.addfile(member)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leanclr", type=Path, required=True,
                        help="Extracted bundle stage directory (contains exporter/, templates/, managed/, ...)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", default="v4.7.2")
    args = parser.parse_args()

    leanclr = args.leanclr.resolve()
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # The runtime publisher scripts and generic source are not part of the
    # Docker build stage; add them to the distributable bundle.
    tools_source = ROOT / "tools"
    tools_destination = leanclr / "tools"
    if tools_destination.exists():
        shutil.rmtree(tools_destination)
    shutil.copytree(tools_source, tools_destination,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(ROOT / "publish", leanclr / "publish")
    (leanclr / "publish").chmod(0o755)
    (leanclr / "managed").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "managed/m1/Bootstrap.cs", leanclr / "managed/Bootstrap.cs")
    shutil.copyfile(ROOT / "dependencies.json", leanclr / "dependencies.json")

    profile = read_json(leanclr / "profile.json")
    bundle = {
        "schema": 1,
        "version": args.version,
        "targets": profile.get("targets", {}),
        "godot_commit": profile.get("godot_commit"),
        "leanclr_commit": profile.get("leanclr_commit"),
        "corelib_version": profile.get("corelib_version"),
        "godotsharp_sha256": profile.get("godotsharp_sha256"),
        "calli_sha256": profile.get("calli_sha256"),
    }
    write_json(leanclr / "bundle.json", bundle)
    write_json(out / "manifest.json", bundle)

    archive = out / f"leanclr-web-bundle-{args.version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        add_tree(tar, leanclr, "leanclr")

    editor = out / "godot-leanclr-editor-linux-x86_64.tar.gz"
    with tarfile.open(editor, "w:gz") as tar:
        add_tree(tar, leanclr / "exporter", "godot-leanclr-editor-linux-x86_64")

    shutil.copyfile(leanclr / "templates/web/web_nothreads_release.zip", out / "web_nothreads_release.zip")
    publication = out / f"leanclr-publication-{args.version}.zip"
    with zipfile.ZipFile(publication, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("managed", "licenses"):
            for path in sorted((leanclr / name).rglob("*")):
                if path.is_file():
                    zf.write(path, f"{name}/{path.relative_to(leanclr / name).as_posix()}")
        zf.write(leanclr / "profile.json", "profile.json")
        zf.write(leanclr / "dependencies.json", "dependencies.json")

    lines = []
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            lines.append(f"{sha256(path)}  {path.name}")
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("BUNDLE_OK", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
