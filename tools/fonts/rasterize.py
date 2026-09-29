#!/usr/bin/env python3
"""The font bench: a local server for the pages that make fonts and layouts for the themes.

    python3 tools/fonts/rasterize.py [PORT]      (default 8767; listens on 127.0.0.1 only)

then open one of
    http://127.0.0.1:PORT/tools/fonts/raster.html              every font in specs.json
    http://127.0.0.1:PORT/tools/fonts/raster.html?only=num84   only those
    http://127.0.0.1:PORT/features/house-numerals/sizing.html  House Numerals' home layout

It serves the repository read-only, plus two kinds of save:
    POST /tools/fonts/save?id=ID              raster/ID.json; a "spec" key in the body is added to
                                              (or replaces its entry in) specs.json
    POST /features/NAME/save-layout           features/NAME/layout.json (NAME must exist)
Builds read those files; nothing is built here.
"""
import http.server
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def write_raster(rid, data):
    path = os.path.join(HERE, "raster", rid + ".json")
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
    return path


def upsert_spec(spec):
    path = os.path.join(HERE, "specs.json")
    cfg = json.load(open(path))
    specs = [s for s in cfg["specs"] if s["id"] != spec["id"]] + [spec]
    cfg["specs"] = sorted(specs, key=lambda s: (re.sub(r"\d+$", "", s["id"]), int(re.search(r"\d+$", s["id"]).group())))
    with open(path, "w") as f:
        f.write("{\n")
        f.write('  "_": %s,\n' % json.dumps(cfg["_"]))
        f.write('  "specs": [\n')
        f.write(",\n".join("    " + json.dumps(s, ensure_ascii=False) for s in cfg["specs"]))
        f.write("\n  ]\n}\n")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def reply(self, code, text):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(text.encode())

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        m = re.fullmatch(r"/tools/fonts/save\?id=([a-z]+[0-9]+)", self.path)
        if m:
            data = json.loads(body)
            spec = data.pop("spec", None)
            if spec is not None:
                if spec.get("id") != m.group(1):
                    return self.reply(400, "the spec's id is not the raster's")
                upsert_spec(spec)
            path = write_raster(m.group(1), data)
            print("wrote", os.path.relpath(path, ROOT), flush=True)
            return self.reply(200, "saved")
        m = re.fullmatch(r"/features/([a-z0-9-]+)/save-layout", self.path)
        if m and os.path.isdir(os.path.join(ROOT, "features", m.group(1))):
            data = json.loads(body)
            path = os.path.join(ROOT, "features", m.group(1), "layout.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            print("wrote", os.path.relpath(path, ROOT), flush=True)
            return self.reply(200, "saved")
        self.reply(404, "no such save")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
    print("font bench on http://127.0.0.1:%d/" % port)
    print("  fonts:  http://127.0.0.1:%d/tools/fonts/raster.html" % port)
    print("  layout: http://127.0.0.1:%d/features/house-numerals/sizing.html" % port, flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
