#!/usr/bin/env python3
"""Build the feature images in dependency order and check what they patch.

    python3 tools/build.py                   every feature, bases first
    python3 tools/build.py house-numerals    that feature and the images it builds on
    python3 tools/build.py --graph           print the graph from the images already built

Each features/<name>/build_patch.py declares BASE (the image it stacks on) and INCLUDES
(fix features linked into it); see tools/patch/features.py. After building, for every image:

  * its sha is looked up in KNOWN_IMAGES (tools/flash/flash_ao300.py); a new one is reported;
  * the config promise: an image with build-time configs (CONFIG, tools/patch/features.py) is built
    once more with every option at a non-default value; it must keep its size and move only the
    declared bytes. Config variables set in the environment are ignored: build.py builds defaults;
  * the bytes it changes in its base must not overlap bytes an ancestor changed (two features
    hooking the same site), apart from the version pointer every image repoints;
  * every fix in INCLUDES must have its hook installed, jumping into this image's own code,
    and its in-place patches (PATCHES) applied;
  * XDATA: the ranges declared (XDATA = [...]) by everything in the image must not overlap;
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


def clean_env():
    """The environment without any AO300_* variable: the config variables (features.env_name) and
    AO300_BUILD_OUT, so a build here is the default build. (Not computed from the declarations:
    loading every build_patch.py would read images that are not built yet.)"""
    return {k: v for k, v in os.environ.items() if not k.startswith("AO300_")}


def build(name):
    """The default build of a feature: its own build_patch.py, with every config variable unset."""
    env = clean_env()
    p = subprocess.run([sys.executable, os.path.join(fg.FEATURES, name, "build_patch.py")],
                       cwd=ROOT, env=env, capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).rstrip()


def variant(name, values):
    """Build a feature's image with configs set: values = {(feature, option): value}. The image
    comes back as bytes; the feature's build/ output and listing are untouched (AO300_BUILD_OUT,
    honoured by uikit.build_image). Raises SystemExit when the build fails."""
    env = clean_env()
    for (f, o), v in values.items():
        env[fg.env_name(f, o)] = str(v)
    out = fg.image(name) + ".variant"
    env["AO300_BUILD_OUT"] = out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        p = subprocess.run([sys.executable, os.path.join(fg.FEATURES, name, "build_patch.py")],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        if p.returncode or not os.path.isfile(out):
            raise SystemExit("variant build of %s failed:\n%s" % (name, (p.stdout + p.stderr).rstrip()))
        return open(out, "rb").read()
    finally:
        if os.path.exists(out):
            os.remove(out)


def config_check(name):
    """The config promise (features.py) on an image: with every option at a non-default value the
    image keeps its size and moves only the declared bytes. (errors, notes); ([], []) without configs."""
    opts = fg.configs(name)
    if not opts:
        return [], []
    values, changes = {}, {}
    for f, o, opt in opts:
        v = opt.hi if opt.default != opt.hi else opt.lo
        values[(f, o)] = v
        changes[(f, o)] = (opt.default, v, opt)
    notes = ["configs " + " ".join("%s.%s=%d" % (f, o, opt.default) for f, o, opt in opts)]
    try:
        img = variant(name, values)
    except SystemExit as ex:
        return ["CONFIG variant build failed: %s" % ex], notes
    return ["CONFIG promise broken: " + e for e in fg.config_diff(read(name), img, changes)], notes


def changed(name):
    """Bytes this feature changed in its base image (within the base's length)."""
    a, b = read(fg.base(name)), read(name)
    return {i for i in range(len(a)) if a[i] != b[i]} - set(fg.VERSION_PTR_BYTES)


def check_xdata(name):
    """The XDATA declared by everything in the image (its chain and their fixes) must not overlap."""
    errors, owners = [], []
    for n in fg.chain_features(name):
        owners += [(n, a, b) for a, b, _ in fg.xdata(n)]
        for fx in fg.includes(n):
            owners += [("%s (in %s)" % (fx, n), a, b) for a, b, _ in fg.xdata(fx)]
    for i, (n1, a1, b1) in enumerate(owners):
        for n2, a2, b2 in owners[i + 1:]:
            if max(a1, a2) < min(b1, b2):
                errors.append("XDATA 0x%04X..0x%04X is declared by both %s and %s"
                              % (max(a1, a2), min(b1, b2) - 1, n1, n2))
    return errors


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
    for fx in fg.includes(name):
        mod = fg.fix(fx)
        if hasattr(mod, "HOOK"):
            addr, orig, op, _ = mod.HOOK
            target = (img[addr + 1] << 8) | img[addr + 2]
            if img[addr] != op or not (len(base_img) <= target < len(img)):
                errors.append("INCLUDES %s, but its hook at 0x%04X is %s (want %02x into this image's code, "
                              "0x%04X..0x%04X)" % (fx, addr, img[addr:addr + 3].hex(" "), op, len(base_img), len(img) - 1))
        for addr, orig, new, note in getattr(mod, "PATCHES", []):
            if img[addr:addr + len(new)] != new:
                errors.append("INCLUDES %s, but its patch at 0x%04X (%s) is not applied" % (fx, addr, note))
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
                mod = fg.fix(k)
                sites = (["hook 0x%04X" % mod.HOOK[0]] if hasattr(mod, "HOOK") else []) + \
                        ["patch 0x%04X" % p[0] for p in getattr(mod, "PATCHES", [])]
                desc.append("[fix, %s; included by %s]"
                            % (", ".join(sites), ", ".join(included_by.get(k, [])) or "none yet"))
            rows.append(("%s%s %s" % (prefix, "└──" if last else "├──", k), "  ".join(desc)))
            inner = prefix + ("    " if last else "│   ")
            own = [(o, opt) for f, o, opt in fg.configs(k) if f == k]
            if own:
                rows.append(("%s  = config" % inner, ", ".join("%s %d..%d (default %d)" % (o, opt.lo, opt.hi, opt.default)
                                                               for o, opt in own)))
            for fx in fg.includes(k):
                rows.append(("%s  + %s" % (inner, fx), "fix linked into %s" % k))
            walk(k, inner)
    walk(fg.STOCK, "")
    width = max(len(t) for t, _ in rows) + 2
    lines = [t.ljust(width) + d for t, d in rows]
    lines.append("")
    lines.append("── builds on (BASE)    + links in a fix (INCLUDES)    = build-time configs (CONFIG)")
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
        sys.exit("original/extracted/flash.bin is missing or not the stock v1.4 image (see docs/development.md, Workflow)")
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
        cerr, cnotes = config_check(name)
        errors += cerr
        notes += cnotes
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
