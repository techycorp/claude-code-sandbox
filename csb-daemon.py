#!/usr/bin/env python3
import json
import os
import socketserver
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from daemon_logic import is_allowed, is_blocked, load_allowed, load_workspace_map, translate_cwd

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 9876


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request = json.loads(self.rfile.readline().decode().strip())
            args = request.get("args", [])
            cwd = request.get("cwd")

            if not args:
                self._send("error", "empty command\n")
                self._exit(1)
                return

            if args[0] not in ("podman", "docker"):
                self._send("stderr", "[csb] BLOCKED: only podman/docker commands are permitted via the host proxy\n")
                self._exit(1)
                return

            if is_blocked(args):
                self._send("stderr", f"[csb] BLOCKED: {' '.join(args)}\n      env exposure is not permitted\n")
                self._exit(1)
                return

            allowed = load_allowed()
            if not is_allowed(args, allowed):
                self._send("stderr", f"[csb] NOT ALLOWED: {' '.join(args)}\n      Add to allowed_commands in config.toml to permit this.\n")
                self._exit(1)
                return

            host_cwd = None
            if cwd:
                workspace_map = load_workspace_map()
                host_cwd = translate_cwd(cwd, workspace_map)
                if not host_cwd:
                    self._send("stderr", f"[csb] cannot resolve container path '{cwd}' to host path\n")
                    self._exit(1)
                    return

            proc = subprocess.run(args, capture_output=True, text=True, cwd=host_cwd)

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
