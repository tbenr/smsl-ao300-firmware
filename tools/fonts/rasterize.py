#!/usr/bin/env python3
"""Serve raster.html and save the glyph coverage it posts to raster/<id>.json.

    python3 tools/fonts/rasterize.py [PORT]      (default 8767)

then open http://127.0.0.1:PORT/raster.html (or raster.html?only=num84,mono11) in a browser.
The page renders every font in specs.json with the browser's text engine, the one the UI mock
uses, and posts each font here. Only needed when specs.json changes: builds read raster/*.json.
"""
import http.server
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def do_POST(self):
        m = re.fullmatch(r"/save\?id=([a-z0-9_]+)", self.path)
        if not m:
            self.send_error(404)
            return
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        path = os.path.join(HERE, "raster", m.group(1) + ".json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:           # one glyph per line: diffs stay readable
            f.write("{\n")
            for k in ("id", "font", "px", "ascent", "descent", "engine", "coverage"):
                f.write("  %s: %s,\n" % (json.dumps(k), json.dumps(data[k])))
            f.write('  "glyphs": {\n')
            items = sorted(data["glyphs"].items())
            for i, (ch, gl) in enumerate(items):
                f.write("    %s: %s%s\n" % (json.dumps(ch), json.dumps(gl, separators=(",", ":")),
                                            "," if i < len(items) - 1 else ""))
            f.write("  }\n}\n")
        print("wrote", path, flush=True)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"saved")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
    print("open http://127.0.0.1:%d/raster.html" % port, flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
