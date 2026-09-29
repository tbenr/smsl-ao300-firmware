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
  * XDATA: the ranges declared (XDATA = [...]) by everything in the image must not overlap,
    and the image's own code may only point DPTR into what it and its fixes declare;
  * assumptions: for every fix in the image, stock code it jumps into (and everything that
    code reaches) must not have been changed by another layer, nor its RAM written by another
    layer's code, unless REVIEWED records that someone checked it. A review is pinned to a
    hash of what it covered, so it is asked again when that changes;
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
import refs  # noqa: E402
from asm51 import Asm  # noqa: E402


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


def code_ranges(name):
    """Instruction ranges of a feature's own code in its image: from its assembler when the build
    has assemble(), else by recursive descent from its hooks (never by decoding data)."""
    own = fg.own_code(name)
    if own:
        return own[0].code_ranges()
    img, base_img = read(name), read(fg.base(name))
    entries = set()
    for addr in changed(name):
        for at in (addr - 1, addr):
            if img[at] in (0x02, 0x12):
                t = (img[at + 1] << 8) | img[at + 2]
                if len(base_img) <= t < len(img):
                    entries.add(t)
    seen, _ = refs.d51.disasm(img, sorted(entries))
    return [(pc, pc + ln) for pc, (ln, _, _) in sorted(seen.items()) if len(base_img) <= pc < len(img)]


def own_refs(name, skip=()):
    """What a feature's own code touches, leaving out the address ranges in skip."""
    img, r = read(name), refs.Refs()
    for s, e in code_ranges(name):
        if not any(a <= s < b for a, b in skip):
            r.scan(img, s, e)
    return r


def fix_code(fx):
    """A fix assembled on its own: (refs of it, its length, the labels it defines)."""
    org = 0x8000
    a = Asm(org)
    fg.fix(fx).emit(a)
    code = a.resolve()
    img = bytes(org) + code
    r = refs.Refs()
    for s, e in a.code_ranges():
        r.scan(img, s, e)
    r.code = {t for t in r.code if not org <= t < org + len(code)}      # its own branches
    return r, len(code), set(a.labels)


def fix_region(name, fx):
    """Where an included fix's code sits in an image: [start, end)."""
    own = fg.own_code(name)
    _, length, labels = fix_code(fx)
    start = own[1][fg.fix(fx).HOOK[3]]
    return start, start + length


def check_xdata(name):
    """Declared XDATA of everything in the image must not overlap; the image's own code must stay in
    what it and its fixes declare."""
    errors = []
    owners = []
    for n in fg.chain_features(name):
        owners += [(n, a, b, w) for a, b, w in fg.xdata(n)]
        for fx in fg.includes(n):
            owners += [("%s (in %s)" % (fx, n), a, b, w) for a, b, w in fg.xdata(fx)]
    for i, (n1, a1, b1, _) in enumerate(owners):
        for n2, a2, b2, _ in owners[i + 1:]:
            if max(a1, a2) < min(b1, b2):
                errors.append("XDATA 0x%04X..0x%04X is declared by both %s and %s"
                              % (max(a1, a2), min(b1, b2) - 1, n1, n2))
    allowed = [(a, b) for a, b, _ in fg.xdata(name)]
    for fx in fg.includes(name):
        allowed += [(a, b) for a, b, _ in fg.xdata(fx)]
    used = own_refs(name).xdata
    bad = [x for x in used if not any(a <= x < b for a, b in allowed)]
    if bad:
        errors.append("its code uses %d XDATA addresses in 0x%04X..0x%04X (first at code 0x%04X) outside "
                      "the XDATA declared for %s" % (len(bad), min(bad), max(bad), min(used[x][0] for x in bad), name))
    return errors


def reviewed(name):
    """REVIEWED entries of an image and the images it stacks on: {(fix, feature): (hash, note)}."""
    out = {}
    for n in reversed(fg.chain_features(name)):
        out.update(getattr(fg.load(n), "REVIEWED", {}))
    return out


def assumptions(name):
    """For every fix in the image: stock code it relies on, or RAM it uses, that another feature in
    the image changed. {(fix, feature): (hash, [finding lines])}."""
    img = read(name)
    stock = read(fg.STOCK)
    found = {}
    for n in fg.chain_features(name):
        for fx in fg.includes(n):
            r, _, _ = fix_code(fx)
            hook = fg.fix(fx).HOOK
            reach = set()
            for t in sorted(r.code):
                if t < len(stock):
                    reach |= refs.reach(stock, t)
            for other in fg.contains(name):
                if other in fg.chain(fx) or fg.is_fix(other):
                    continue
                lines, key = [], []
                code_hits = changed(other) & reach
                if other == n:
                    code_hits -= set(range(hook[0], hook[0] + 3))
                if code_hits:
                    lines.append("relies on stock code that %s changed: %s (reached from %s)"
                                 % (other, ranges(code_hits), ", ".join("0x%04X" % t for t in sorted(r.code))))
                    key += [(a, img[a]) for a in sorted(code_hits)]
                skip = [fix_region(other, g) for g in fg.includes(other)]
                w = own_refs(other, skip).writes()
                ram_hits = sorted(set(r.ram) & w)
                if ram_hits:
                    lines.append("uses RAM that %s's code writes: %s"
                                 % (other, ", ".join("0x%02X" % x for x in ram_hits)))
                    key += [("ram", x) for x in ram_hits]
                if lines:
                    found[(fx, other)] = (sha(repr(key).encode())[:8], lines)
    return found


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
    errors += check_xdata(name)
    done = reviewed(name)
    found = assumptions(name)
    for key in getattr(fg.load(name), "REVIEWED", {}):
        if key not in found:
            notes.append("REVIEWED %s vs %s matches nothing any more: remove it" % key)
    for (fx, other), (h, lines) in sorted(found.items()):
        entry = done.get((fx, other))
        if entry and entry[0] == h:
            notes.append("%s vs %s reviewed" % (fx, other))
            continue
        errors.append("%s %s" % (fx, lines[0]) + "".join("\n      and " + ln for ln in lines[1:]))
        errors.append("  %s it, then add to REVIEWED in %s:  (\"%s\", \"%s\"): (\"%s\", \"<why it is fine>\"),"
                      % ("these changed since the review; re-check" if entry else "check", name, fx, other, h))
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
    """The feature tree: ── builds on (BASE), + links in a fix (INCLUDES)."""
    rows = []                                   # (tree column, details)
    stock = read(fg.STOCK)
    rows.append(("stock", "%s…" % sha(stock)[:8] if stock else "missing: original/extracted/flash.bin"))
    included_by = {}
    for n in fg.names():
        for fx in fg.includes(n):
            included_by.setdefault(fx, []).append(n)

    def walk(name, prefix):
        kids = fg.children(name)
        for i, k in enumerate(kids):
            last = i == len(kids) - 1
            m, img = fg.load(k), read(k)
            desc = ["%-18r" % getattr(m, "VERSION_TEXT", "?")]
            if img:
                desc.append("0x%04X..0x%04X  %s… %s" % (code_start(k), len(img) - 1, sha(img)[:8],
                                                       "known" if sha(img) in known else "NEW"))
            else:
                desc.append("not built")
            if fg.is_fix(k):
                desc.append("[fix, hook 0x%04X; included by %s]"
                            % (fg.fix(k).HOOK[0], ", ".join(included_by.get(k, [])) or "none yet"))
            rows.append(("%s%s %s" % (prefix, "└──" if last else "├──", k), "  ".join(desc)))
            inner = prefix + ("    " if last else "│   ")
            for fx in fg.includes(k):
                rows.append(("%s  + %s" % (inner, fx), "fix linked into %s" % k))
            walk(k, inner)
    walk(fg.STOCK, "")
    width = max(len(t) for t, _ in rows) + 2
    lines = [t.ljust(width) + d for t, d in rows]
    lines.append("")
    lines.append("── builds on (BASE)    + links in a fix (INCLUDES)")
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
        (print if errors else say)("%-16s %s  %s" % (name, "ok     " if not errors else "PROBLEM", "; ".join(notes)))
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
