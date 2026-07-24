"""Local desktop launcher for Dhad's web application.

The launcher owns the lifecycle of a loopback-only Uvicorn process and opens
that application in an embedded pywebview window when available. Without the
optional GUI dependency it uses Chromium/Edge application mode, then falls
back to the operating system browser. No user text leaves the local server.
"""

from __future__ import annotations

import argparse
import atexit
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from types import FrameType
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def reserve_loopback_port(host: str = "127.0.0.1") -> int:
    """Return an available TCP port on a loopback interface."""

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def browser_app_command(url: str, *, executable: str | None = None) -> list[str] | None:
    """Build a Chromium/Edge standalone-app command if a browser is available."""

    candidates: list[str] = []
    if executable:
        candidates.append(executable)
    if os.environ.get("DHAD_BROWSER_BINARY"):
        candidates.append(os.environ["DHAD_BROWSER_BINARY"])
    if sys.platform == "darwin":
        candidates.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    elif os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in filter(None, roots):
            candidates.extend(
                [
                    str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                    str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
                ]
            )
    else:
        candidates.extend(
            [
                "google-chrome",
                "google-chrome-stable",
                "microsoft-edge",
                "microsoft-edge-stable",
                "chromium",
                "chromium-browser",
            ]
        )

    resolved: str | None = None
    for candidate in candidates:
        path = shutil.which(candidate) if not Path(candidate).is_absolute() else candidate
        if path and Path(path).is_file():
            resolved = str(path)
            break
    if resolved is None:
        return None
    profile = Path(tempfile.gettempdir()) / "dhad-desktop-browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return [
        resolved,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


class LocalServer:
    """Own a Dhad Uvicorn subprocess and guarantee termination on exit."""

    def __init__(self, host: str, port: int) -> None:
        if host not in _LOOPBACK_HOSTS:
            raise ValueError("The desktop launcher only binds to a loopback host")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self.host = host
        self.port = port
        self.process: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        display_host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{display_host}:{self.port}"

    def start(self, *, timeout: float = 25.0) -> None:
        if self.process is not None:
            raise RuntimeError("Dhad desktop server is already running")
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "dhad.server:app",
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--log-level",
            "warning",
        ]
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + timeout
        health_url = f"{self.base_url}/api/health"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                detail = (self.process.stderr.read() if self.process.stderr else b"").decode(
                    "utf-8", errors="replace"
                )
                raise RuntimeError(f"Dhad server exited during startup: {detail.strip()}")
            try:
                with urlopen(health_url, timeout=0.6) as response:  # noqa: S310 - loopback URL only
                    if response.status == 200:
                        return
            except (URLError, TimeoutError):
                time.sleep(0.12)
        self.stop()
        raise TimeoutError(f"Dhad server did not become ready at {health_url}")

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def __enter__(self) -> LocalServer:
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()


def _run_pywebview(url: str) -> bool:
    try:
        import webview  # type: ignore[import-not-found]
    except ImportError:
        return False
    webview.create_window(
        "ضاد — ذكاء الكتابة العربية",
        url,
        width=1280,
        height=840,
        min_size=(760, 560),
        text_select=True,
    )
    webview.start(private_mode=True)
    return True


def _wait_for_interrupt() -> None:
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dhad-desktop", description="شغّل ضاد كتطبيق سطح مكتب محلي"
    )
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(_LOOPBACK_HOSTS))
    parser.add_argument("--port", type=int, default=0, help="0 لاختيار منفذ محلي متاح")
    parser.add_argument(
        "--backend", choices=("auto", "webview", "chromium", "browser", "server"), default="auto"
    )
    parser.add_argument(
        "--browser-binary", help="مسار Chrome/Edge/Chromium عند استخدام وضع التطبيق"
    )
    args = parser.parse_args(argv)

    port = args.port or reserve_loopback_port(args.host)
    server = LocalServer(args.host, port)
    atexit.register(server.stop)

    def shutdown(_signum: int, _frame: FrameType | None) -> None:
        server.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    server.start()
    url = server.base_url
    try:
        if args.backend in {"auto", "webview"}:
            if _run_pywebview(url):
                return 0
            if args.backend == "webview":
                raise RuntimeError(
                    "pywebview is not installed; install dhad[desktop] or use --backend chromium"
                )

        if args.backend in {"auto", "chromium"}:
            command = browser_app_command(url, executable=args.browser_binary)
            if command is not None:
                browser = subprocess.Popen(command)
                browser.wait()
                return 0
            if args.backend == "chromium":
                raise RuntimeError("No Chrome, Edge, or Chromium executable was found")

        if args.backend == "server":
            print(f"Dhad desktop server is running at {url}")
            _wait_for_interrupt()
            return 0

        webbrowser.open(url, new=1, autoraise=True)
        print(f"Opened Dhad at {url}. Press Ctrl+C to stop the local server.")
        _wait_for_interrupt()
        return 0
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
