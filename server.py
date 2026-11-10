#!/usr/bin/env python3
"""
KMSAN Crash Portal — minimal HTTP server, no external dependencies.
Usage: python3 server.py [port]   (default port: 8765)
"""

import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
DATA = BASE / "crashes.json"
STATIC = BASE / "index.html"


def load() -> list:
    if DATA.exists():
        return json.loads(DATA.read_text())
    return []


def save(crashes: list):
    DATA.write_text(json.dumps(crashes, indent=2, ensure_ascii=False))


def import_workdir(workdir: str) -> list:
    """Read crashes from a syzkaller workdir/crashes directory."""
    crashes_dir = Path(workdir) / "crashes"
    if not crashes_dir.is_dir():
        crashes_dir = Path(workdir)  # maybe pointed directly at crashes/
    if not crashes_dir.is_dir():
        raise ValueError(f"Not found: {crashes_dir}")

    imported = []
    for d in sorted(crashes_dir.iterdir()):
        if not d.is_dir():
            continue
        desc_file = d / "description"
        if not desc_file.exists():
            continue
        desc = desc_file.read_text().strip().splitlines()[0]

        # Detect noise
        noise_prefixes = (
            "SYZFAIL:", "SYZFATAL:", "lost connection", "no output from",
            "suppressed report",
        )
        if any(desc.startswith(p) for p in noise_prefixes):
            continue
        if desc.endswith("in corrupted"):
            continue

        # Detect reproducer type
        has_cprog = (d / "repro.cprog").exists()
        has_prog = (d / "repro.prog").exists()
        has_repro0 = any(d.glob("repro[0-9]*"))
        if has_cprog and has_prog:
            repro = "prog+C"
        elif has_prog:
            repro = "prog"
        elif has_cprog:
            repro = "C"
        elif has_repro0:
            repro = "repro0"
        else:
            repro = "none"

        # Read first lines of report0 for the call stack hint
        note = ""
        for rname in ("repro.report", "report0"):
            rfile = d / rname
            if rfile.exists():
                lines = rfile.read_text(errors="replace").splitlines()
                # grab first non-empty lines after the BUG header
                stack = []
                for ln in lines[1:30]:
                    ln = ln.strip()
                    if ln.startswith(("BUG:", "KMSAN:", "WARNING:", "INFO:", "general", "kernel")):
                        continue
                    if ln.startswith(("CPU:", "PID:", "Hardware", "Kernel", "Modules", "Call Trace", "Allocated")):
                        break
                    if ln:
                        stack.append(ln)
                    if len(stack) >= 4:
                        break
                note = " → ".join(stack[:3])
                break

        imported.append({
            "id": str(uuid.uuid4()),
            "hash": d.name,
            "description": desc,
            "subsystem": "",
            "repro": repro,
            "status_510": "?",
            "status_61": "?",
            "status_612": "?",
            "note": note,
            "added": int(time.time()),
        })
    return imported


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs
        print(f"  {self.address_string()} {fmt % args}")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_html(self):
        body = STATIC.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self.send_html()
        elif p == "/api/crashes":
            self.send_json(200, load())
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        body = self.read_body()

        if p == "/api/crashes":
            crash = json.loads(body)
            crash.setdefault("id", str(uuid.uuid4()))
            crash.setdefault("added", int(time.time()))
            crashes = load()
            crashes.append(crash)
            save(crashes)
            self.send_json(201, crash)

        elif p == "/api/import":
            data = json.loads(body)
            workdir = data.get("workdir", "")
            try:
                imported = import_workdir(workdir)
            except Exception as e:
                self.send_json(400, {"error": str(e)})
                return
            crashes = load()
            existing_hashes = {c.get("hash") for c in crashes}
            new_ones = [c for c in imported if c.get("hash") not in existing_hashes]
            crashes.extend(new_ones)
            save(crashes)
            self.send_json(200, {"imported": len(new_ones), "skipped": len(imported) - len(new_ones), "crashes": new_ones})

        else:
            self.send_json(404, {"error": "not found"})

    def do_PUT(self):
        p = urlparse(self.path).path
        parts = p.split("/")
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "crashes":
            cid = parts[3]
            body = json.loads(self.read_body())
            crashes = load()
            for i, c in enumerate(crashes):
                if c["id"] == cid:
                    body["id"] = cid
                    body.setdefault("added", c.get("added", int(time.time())))
                    crashes[i] = body
                    save(crashes)
                    self.send_json(200, body)
                    return
            self.send_json(404, {"error": "not found"})
        else:
            self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        p = urlparse(self.path).path
        parts = p.split("/")
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "crashes":
            cid = parts[3]
            crashes = load()
            new = [c for c in crashes if c["id"] != cid]
            if len(new) == len(crashes):
                self.send_json(404, {"error": "not found"})
                return
            save(new)
            self.send_json(200, {"deleted": cid})
        else:
            self.send_json(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"KMSAN Portal: http://127.0.0.1:{port}/")
    print("Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
