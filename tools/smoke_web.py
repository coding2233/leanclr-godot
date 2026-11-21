"""Run an exported LeanCLR Web build in headless Chromium."""

from __future__ import annotations

import argparse
from functools import partial
import http.server
from pathlib import Path
import sys
import threading
import time

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--query", default="?smoke")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--expected", default="NODE2D_SMOKE_OK instances=1 frames=4 x=8 speed=120")
    args = parser.parse_args()

    directory = args.directory.resolve()
    index = directory / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"Web export is missing: {index}")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *unused):
            pass

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(Handler, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    messages: list[str] = []
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--enable-unsafe-swiftshader", "--disable-background-networking"])
            page = browser.new_page(viewport={"width": 960, "height": 640})
            page.on("console", lambda message: (
                messages.append(message.text),
                errors.append(message.text) if any(
                    marker in message.text for marker in (
                        "LEANCLR_GODOT_FATAL",
                        "LEANCLR_PUBLICATION_REJECTED",
                        "M0_DOTNET_FAIL")) else None))
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/index.html{args.query}",
                      wait_until="domcontentloaded")
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline and not errors:
                if any("LEANCLR_GODOT_READY backend=LeanCLR" in line for line in messages) and \
                        any(args.expected in line for line in messages):
                    break
                page.wait_for_timeout(100)
            page.wait_for_timeout(500)
            browser.close()
    finally:
        server.shutdown()
    for line in messages:
        print(line)
    if errors:
        raise RuntimeError("Web runtime errors: " + "\n".join(errors))
    if not any("LEANCLR_GODOT_READY backend=LeanCLR" in line for line in messages):
        raise RuntimeError("LeanCLR backend did not initialize in the Web build")
    if not any(args.expected in line for line in messages):
        raise RuntimeError("expected Web smoke output was not observed")
    print("WEB_RUNTIME_OK", args.expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
