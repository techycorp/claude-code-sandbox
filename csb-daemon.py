#!/usr/bin/env python3
import base64
import json
import os
import platform
import shutil
import socketserver
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from daemon_logic import is_allowed, load_allowed, translate_cwd

MACOS = platform.system() == "Darwin"
DEFAULT_COLIMA_SOCKET = Path.home() / ".colima" / "default" / "docker.sock"


def docker_env():
    env = os.environ.copy()
    if MACOS and DEFAULT_COLIMA_SOCKET.exists():
        env["DOCKER_HOST"] = f"unix://{DEFAULT_COLIMA_SOCKET}"
    return env

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 9876


def read_clipboard_png():
    """Pull image data off the host's clipboard as PNG, or None if it holds no image.

    Run on the host (not the sandbox container, which has no clipboard access
    at all — no pasteboard on macOS, and even on Linux the container has no X11/
    Wayland session of its own).
    """
    if MACOS:
        return _read_clipboard_png_macos()
    return _read_clipboard_png_linux()


def _read_clipboard_png_macos():
    """Mirrors the osascript invocation Claude Code's own macOS clipboard-paste code uses."""
    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        proc = subprocess.run(
            [
                "osascript",
                "-e", "set png_data to (the clipboard as «class PNGf»)",
                "-e", f'set fp to open for access POSIX file "{tmp_path}" with write permission',
                "-e", "write png_data to fp",
                "-e", "close access fp",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            return None
        data = Path(tmp_path).read_bytes()
        return data or None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _read_clipboard_png_linux():
    """Reads PNG image data from the host's X11/Wayland clipboard, same priority
    order Claude Code's own Linux clipboard code uses: wl-paste under Wayland,
    else xclip under X11."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
        proc = subprocess.run(
            ["wl-paste", "--type", "image/png"],
            capture_output=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
        return None

    if os.environ.get("DISPLAY") and shutil.which("xclip"):
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
        return None

    return None


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline().decode().strip()
            if not line:
                return
            request = json.loads(line)

            if request.get("op") == "clipboard_png":
                data = read_clipboard_png()
                if data is None:
                    self._exit(1)
                else:
                    self._send("png_b64", base64.b64encode(data).decode())
                    self._exit(0)
                return

            args = request.get("args", [])
            cwd = request.get("cwd")

            if not args:
                self._send("error", "empty command\n")
                self._exit(1)
                return

            if args[0] != "docker":
                self._send("stderr", "[csb] BLOCKED: only docker commands are permitted via the host proxy\n")
                self._exit(1)
                return

            allowed = load_allowed()
            if not is_allowed(args, allowed):
                self._send("stderr", f"[csb] NOT ALLOWED: {' '.join(args)}\n      Add to allowed_commands in config.toml to permit this.\n")
                self._exit(1)
                return

            host_cwd = translate_cwd(cwd)

            proc = subprocess.run(args, capture_output=True, text=True, cwd=host_cwd, env=docker_env())

            if proc.stdout:
                self._send("stdout", proc.stdout)
            if proc.stderr:
                self._send("stderr", proc.stderr)
            self._exit(proc.returncode)

        except Exception as e:
            self._send("error", f"[csb-daemon] error: {e}\n")
            self._exit(1)

    def _send(self, type_, data):
        self.wfile.write((json.dumps({"type": type_, "data": data}) + "\n").encode())
        self.wfile.flush()

    def _exit(self, code):
        self.wfile.write((json.dumps({"type": "exit", "code": code}) + "\n").encode())
        self.wfile.flush()


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True


def main():
    print(f"[csb-daemon] listening on {PROXY_HOST}:{PROXY_PORT}", flush=True)
    with Server((PROXY_HOST, PROXY_PORT), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
