#!/usr/bin/env python3
"""Pack the user-facing release bundle: dist/ao300-custom-<version>.zip.

    python3 tools/release.py                 pack, then self-test the bundle
    python3 tools/release.py --no-selftest   pack only
    python3 tools/release.py --dist DIR      write the zip there (default dist/)
    python3 tools/release.py --also PATH     add a file (repeatable; refused if it is firmware)

The bundle is a subset of the repository, every file at its own path: install.sh, README.md,
the user guide docs/install.md, docs/status.md, the README's screenshots, LICENSE, NOTICE.md and
the fonts' licences, requirements.txt, the wizard (tools/installer/), the build tools (tools/patch,
tools/pe/stc_release.py, tools/flash/flash_ao300.py, tools/build.py, tools/fonts/raster) and, for
each theme the wizard offers, the features it stacks on or links in: their build_patch.py, fix
module and data (*.json). Added to it: a VERSION file and an empty original/ folder with a note.
No emu_test.py, no build/ output, no listings, no feature READMEs, and never firmware (*.bin,
*.exe, *.hex): whoever installs it supplies the vendor updater. The script refuses to write
otherwise.

The self-test extracts the zip into a temp folder, copies original/extracted/flash.bin in and
builds both themes there with the wizard's flags (python: this interpreter, which has pefile
and pyserial), so the bundle is proven self-sufficient before it is published.
"""
import argparse
import datetime
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
sys.path.insert(0, os.path.join(ROOT, "tools", "installer"))
import features  # noqa: E402
from ao300_installer import THEMES  # noqa: E402

FIRMWARE = (".bin", ".exe", ".hex")
FORBIDDEN_PARTS = ("build", "extracted", "ghidraPRG", "__pycache__")
FEATURE_FILES = ("*.py", "*.json")
FEATURE_EXCLUDE = ("emu_test.py",)
# What a user reads and runs, at the paths the repository has them: README.md links to the others.
DOCS = ("install.sh", "README.md", "LICENSE", "NOTICE.md", "requirements.txt", "docs/install.md", "docs/status.md")


def version():
    try:
        tag = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        tag = "untracked"
    return "%s-%s" % (tag, datetime.datetime.now().strftime("%Y%m%d"))


def rel(path):
    return os.path.relpath(path, ROOT)


def files():
    """[(source path, path inside the bundle)] from the whitelist."""
    out = [(os.path.join(ROOT, p), p) for p in DOCS]
    for pattern in ("tools/installer/*.py", "tools/patch/*.py", "tools/fonts/raster/*.json",
                    "tools/fonts/licenses/*.txt", "docs/images/*.png"):
        out += [(p, rel(p)) for p in sorted(glob.glob(os.path.join(ROOT, pattern)))
                if not os.path.basename(p).startswith("test_") and not os.path.basename(p).endswith("_test.py")]
    for p in ("tools/pe/stc_release.py", "tools/flash/flash_ao300.py", "tools/build.py"):
        out.append((os.path.join(ROOT, p), p))
    needed = []
    for theme, _ in THEMES:
        for f in features.chain_features(theme) + features.contains(theme):
            if f not in needed:
                needed.append(f)
    for f in needed:
        folder = os.path.join(features.FEATURES, f)
        for pattern in FEATURE_FILES:
            out += [(p, rel(p)) for p in sorted(glob.glob(os.path.join(folder, pattern)))
                    if os.path.basename(p) not in FEATURE_EXCLUDE]
    return out


def refuse(paths):
    """The bundle paths that must never ship: firmware, build output, the extracted image."""
    bad = []
    for _, dst in paths:
        parts = dst.split("/")
        if dst.lower().endswith(FIRMWARE) or any(part in FORBIDDEN_PARTS for part in parts):
            bad.append(dst)
    return bad


def pack(dist, extra=()):
    ver = version()
    top = "ao300-custom-%s" % ver
    paths = files() + [(os.path.join(ROOT, e), e) for e in extra]
    bad = refuse(paths)
    if bad:
        raise SystemExit("refusing to pack firmware or build output into the bundle:\n  " + "\n  ".join(bad))
    for src, _ in paths:
        if not os.path.isfile(src):
            raise SystemExit("missing: %s" % rel(src))
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, top + ".zip")
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for src, dst in paths:
            info = zipfile.ZipInfo.from_file(src, "%s/%s" % (top, dst))
            info.compress_type = zipfile.ZIP_DEFLATED
            if dst == "install.sh":
                info.external_attr = (0o755 << 16)
            z.writestr(info, open(src, "rb").read())
            total += os.path.getsize(src)
        z.writestr("%s/VERSION" % top, ver + "\n")
        z.writestr("%s/original/README.txt" % top,
                   "Put the vendor updater here:\n\n    SMSL_AO300_UPDATE_VER0A5_EN (an .exe; AO300 firmware v1.4, from SMSL's support pages)\n\n"
                   "The installer extracts the stock firmware from it into original/extracted/.\n"
                   "Nothing in this folder is part of the package: the firmware is SMSL's.\n")
    print("wrote %s: %d files, %d bytes before compression" % (rel(out), len(paths) + 2, total))
    return out


def selftest(zip_path):
    """Extract the bundle, add the local stock image, build each theme from inside it: every theme
    in a fresh extraction, so a theme that only builds after another one has been built is caught."""
    stock_src = features.STOCK_IMAGE
    if not os.path.isfile(stock_src):
        raise SystemExit("self-test needs %s" % rel(stock_src))
    for theme, _ in THEMES:
        tmp = tempfile.mkdtemp(prefix="ao300-release-")
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp)
            top = os.path.join(tmp, os.listdir(tmp)[0])
            os.makedirs(os.path.join(top, "original", "extracted"))
            shutil.copy(stock_src, os.path.join(top, "original", "extracted", "flash.bin"))
            installer = os.path.join(top, "tools", "installer", "ao300_installer.py")
            sets = []
            for f, o, opt in features.configs(theme):
                sets += ["--set", "%s.%s=%d" % (f, o, opt.hi if opt.default != opt.hi else opt.lo)]
            p = subprocess.run([sys.executable, installer, "--theme", theme, "--build-only"] + sets,
                               cwd=top, capture_output=True, text=True)
            if p.returncode:
                raise SystemExit("self-test: the bundle could not build %s:\n%s" % (theme, (p.stdout + p.stderr).rstrip()))
            made = [n for n in os.listdir(os.path.join(top, "build", "out")) if n.endswith(".bin") and theme in n]
            if len(made) != 1:
                raise SystemExit("self-test: expected one %s image, got %s" % (theme, made))
            print("self-test: %s built from a fresh extraction of the bundle (%s)" % (theme, made[0]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dist", default=os.path.join(ROOT, "dist"), help="output folder (default dist/)")
    ap.add_argument("--no-selftest", action="store_true", help="pack only")
    ap.add_argument("--also", action="append", default=[], metavar="PATH", help="add a file from the tree (repeatable)")
    args = ap.parse_args()
    out = pack(args.dist, args.also)
    if not args.no_selftest:
        selftest(out)
    print("ok: %s" % rel(out))


if __name__ == "__main__":
    main()
