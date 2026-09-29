#!/usr/bin/env python3
"""Build the feature images in dependency order and check what they patch.

    python3 tools/build.py                   every feature, bases first
    python3 tools/build.py house-numerals    that feature and the images it builds on
    python3 tools/build.py --graph           print the graph from the images already built

Each features/<name>/build_patch.py declares BASE (the image it stacks on) and INCLUDES
(fix features linked into it); see tools/patch/features.py. After building, for every image:

  * its sha is looked up in KNOWN_IMAGES (tools/flash/flash_ao300.py); a new one is reported;
  * the bytes it changes in its base must not overlap bytes an ancestor changed (two features
    hooking the same site), apart from the version pointer every image repoints;
  * every fix in INCLUDES must have its hook installed, jumping into this image's own code;
  * code areas of features that are not in one chain should not overlap either, so each
    address keeps one name in tools/disasm/SmslAo300Labels.java (warning only).

Exit status 1 if a build or a check fails.
"""
import argparse
import ast
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
import features as fg  # noqa: E402


def known_images():
    """KNOWN_IMAGES from the flasher, read as a literal (importing it needs stcgal)."""
    tree = ast.parse(open(os.path.join(ROOT, "tools", "flash", "flash_ao300.py")).read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "KNOWN_IMAGES" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def read(name):
    path = fg.image(name)
    return open(path, "rb").read() if os.path.isfile(path) else None


def sha(data):
    return hashlib.sha256(data).hexdigest()


def code_start(name):
    m = fg.load(name)
    return getattr(m, "CODE_ADDR", getattr(m, "PATCH_ADDR", None))


def ranges(addrs):
    out = []
    for x in sorted(addrs):
        if out and x == out[-1][1] + 1:
            out[-1][1] = x
        else:
            out.append([x, x])
    return ", ".join("0x%04X" % a if a == b else "0x%04X..0x%04X" % (a, b) for a, b in out)


def build(name):
    p = subprocess.run([sys.executable, os.path.join(fg.FEATURES, name, "build_patch.py")],
                       cwd=ROOT, capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).rstrip()


def changed(name):
    """Bytes this feature changed in its base image (within the base's length)."""
    a, b = read(fg.base(name)), read(name)
    return {i for i in range(len(a)) if a[i] != b[i]} - set(fg.VERSION_PTR_BYTES)


def check(name, known):
    """Problems (errors) with a built image, and notes about it."""
    errors, notes = [], []
    img, base_img = read(name), read(fg.base(name))
    h = sha(img)
    if h in known:
        notes.append("known image")
    else:
        notes.append("NEW sha %s: add it to KNOWN_IMAGES once its tests pass" % h)
    mine = changed(name)
    for anc in fg.chain(name)[1:-1]:
        both = mine & changed(anc)
        if both:
            errors.append("re-patches bytes %s already changed: %s" % (anc, ranges(both)))
    for fx in fg.includes(name):
        addr, orig, op, _ = fg.fix(fx).HOOK
        target = (img[addr + 1] << 8) | img[addr + 2]
        if img[addr] != op or not (len(base_img) <= target < len(img)):
            errors.append("INCLUDES %s, but its hook at 0x%04X is %s (want %02x into this image's code, "
                          "0x%04X..0x%04X)" % (fx, addr, img[addr:addr + 3].hex(" "), op, len(base_img), len(img) - 1))
    return errors, notes


def overlaps(built):
    """Warnings: code areas of two features outside one chain that share addresses."""
    area = {n: (code_start(n), len(read(n))) for n in built}
    out = []
    for i, a in enumerate(built):
        for b in built[i + 1:]:
            if a in fg.chain(b) or b in fg.chain(a):
                continue
            lo, hi = max(area[a][0], area[b][0]), min(area[a][1], area[b][1])
            if lo < hi:
                out.append("%s and %s both use 0x%04X..0x%04X: give one of them another CODE_ADDR"
                           % (a, b, lo, hi - 1))
    return out


def graph(known):
    """The feature tree, one line per image."""
    lines = []
    stock = read(fg.STOCK)
    lines.append("stock  %s" % ("%s…" % sha(stock)[:8] if stock else "missing: original/extracted/flash.bin"))

    def walk(name, prefix):
        kids = fg.children(name)
        for i, k in enumerate(kids):
            last = i == len(kids) - 1
            m, img = fg.load(k), read(k)
            desc = ["%r" % getattr(m, "VERSION_TEXT", "?")]
            if img:
                desc.append("code 0x%04X..0x%04X" % (code_start(k), len(img) - 1))
                desc.append("%s… %s" % (sha(img)[:8], "known" if sha(img) in known else "NEW"))
            else:
                desc.append("not built")
            if fg.is_fix(k):
                desc.append("fix, hook 0x%04X" % fg.fix(k).HOOK[0])
            if fg.includes(k):
                desc.append("includes " + ", ".join(fg.includes(k)))
            lines.append("%s%s %s  %s" % (prefix, "└──" if last else "├──", k, "  ".join(desc)))
            walk(k, prefix + ("    " if last else "│   "))
    walk(fg.STOCK, "")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("features", nargs="*", help="features to build, with their bases (default: all)")
    ap.add_argument("--graph", action="store_true", help="only print the graph of the images already built")
    ap.add_argument("-q", "--quiet", action="store_true", help="print only problems")
    args = ap.parse_args()
    known = known_images()
    if args.graph:
        print(graph(known))
        return

    say = (lambda *a: None) if args.quiet else print
    if sha(read(fg.STOCK) or b"") != fg.STOCK_SHA:
        sys.exit("original/extracted/flash.bin is missing or not the stock v1.4 image (see README, Workflow)")
    failed, built, problems = set(), [], 0
    for name in fg.order(args.features or None):
        blocked = [c for c in fg.chain(name)[1:] if c in failed]
        if blocked:
            print("%-16s SKIPPED  (base %s failed)" % (name, blocked[0]))
            failed.add(name)
            continue
        pinned, actual = fg.load(name).BASE_SHA, sha(read(fg.base(name)))
        if pinned != actual:
            failed.add(name)
            problems += 1
            print("%-16s STALE PIN\n    it pins %s at %s…, which now builds as %s…. Re-check %s against the new "
                  "base (its tests, its image diff), then update its BASE_SHA."
                  % (name, fg.base(name), pinned[:8], actual[:8], name))
            continue
        ok, out = build(name)
        if not ok:
            failed.add(name)
            problems += 1
            print("%-16s FAILED\n%s" % (name, "\n".join("    " + ln for ln in out.splitlines()[-6:])))
            continue
        built.append(name)
        errors, notes = check(name, known)
        problems += len(errors)
        say("%-16s %s  %s" % (name, "ok     " if not errors else "PROBLEM", "; ".join(notes)))
        for e in errors:
            print("    " + e)
    for w in overlaps(built):
        print("warning: " + w)
    if not args.quiet:
        print()
        print(graph(known))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
