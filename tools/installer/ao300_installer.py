#!/usr/bin/env python3
"""The AO300 custom firmware installer: from the vendor updater to a flashed amp, one step at a time.

    ./install.sh                      (the entry point: venv, dependencies, then this)
    python3 tools/installer/ao300_installer.py [options]

Steps: find and check the stock firmware in original/, choose a UI theme and the build-time
configs (the volume caps), build the image, then flash it through tools/flash/flash_ao300.py
on the serial port it finds. Every answer can be given up front, so the same script runs
unattended (the tests and tools/release.py's self-test do that):

    --theme NAME                      house-numerals or phosphor-panel
    --set FEATURE.OPTION=VALUE        a build-time config (repeatable), e.g. start-volume.SPEAKER_LIMIT=30
    --out DIR                         where the image goes (default build/out)
    --build-only                      stop after the build
    --action flash|identify|recover   skip the menu
    --action exe                      write a Windows updater (.exe) next to the image instead
    --port DEVICE_OR_URL              skip the port detection

How the build is trusted: the theme is built with its defaults first (the reference, whose
sha256 must be registered in the flasher's KNOWN_IMAGES; this happens before the questions,
since a theme's build module may read its base image when it loads), then with the chosen
configs. The
second image must be the first with only the configs' own bytes changed
(features.config_diff, the build-time config promise). Nothing here knows a default, an
option name or an environment variable: they all come from the features' CONFIG declarations.
"""
import argparse
import datetime
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for sub in (("tools", "patch"), ("tools", "pe"), ("tools",)):
    sys.path.insert(0, os.path.join(ROOT, *sub))
import features  # noqa: E402
import build  # noqa: E402  (tools/build.py: known_images, variant)
import ports  # noqa: E402
import stock  # noqa: E402

THEMES = [
    ("house-numerals", "House Numerals: the input name and a large volume number in clean typefaces, "
                       "with a sliding volume page"),
    ("phosphor-panel", "Phosphor Panel: a VFD look, dot-matrix name, lamps and seven-segment digits "
                       "with afterglow"),
]
STOCK_DIR = os.path.join(ROOT, "original")
EXTRACTED = os.path.join(STOCK_DIR, "extracted")
DEFAULT_OUT = os.path.join(ROOT, "build", "out")
FLASHER = os.path.join(ROOT, "tools", "flash", "flash_ao300.py")
BUILD = os.path.join(ROOT, "tools", "build.py")

AMP_STEPS = {
    "flash": "When the flasher says \"Waiting for the bootloader\": put the amp in STANDBY, then press\n"
             "SOURCE on the remote. (Or unplug the amp's mains and plug it back in.)",
    "identify": "When the flasher says \"Waiting for the bootloader\": put the amp in STANDBY, then press\n"
                "SOURCE on the remote. Nothing is written; the amp restarts as it was.",
    "recover": "Unplug the amp's mains. When the flasher says \"Waiting for the bootloader\", plug it\n"
               "back in: a cold power-up always enters the bootloader, even with no firmware.",
}


def interactive():
    return sys.stdin.isatty()


def ask(prompt, default=None):
    """One line from the user; EOF or 'q' quits the installer."""
    try:
        answer = input(prompt).strip()
    except EOFError:
        sys.exit("\nNo answer (no terminal?). Give the answers as options; see --help.")
    if answer.lower() == "q":
        sys.exit("Quit. Nothing was sent to the amp.")
    return answer or default


def menu(title, items, default=None):
    """items: [(label, value)]; returns the chosen value."""
    print("\n" + title)
    for i, (label, _) in enumerate(items, 1):
        print("  %d) %s" % (i, label))
    while True:
        answer = ask("Choice [%s]: " % (default or "1-%d" % len(items)), default)
        if answer and answer.isdigit() and 1 <= int(answer) <= len(items):
            return items[int(answer) - 1][1]
        print("Type a number from 1 to %d (q quits)." % len(items))


def bundle_version():
    path = os.path.join(ROOT, "VERSION")
    return open(path).read().strip() if os.path.isfile(path) else "development checkout"


# ---- step 1: the stock firmware --------------------------------------------------------------------

def ensure_stock():
    if stock.is_installed(EXTRACTED):
        print("Stock firmware v1.4: already extracted (%s)." % os.path.relpath(os.path.join(EXTRACTED, "flash.bin"), ROOT))
        return
    while True:
        found = stock.find(STOCK_DIR)
        if not found:
            print("\nThe stock firmware is needed first: every change is a patch on it, and it is not\n"
                  "included here. Download the vendor updater\n\n    %s\n\nfrom SMSL's support pages "
                  "(the AO300 firmware v1.4 update) and put it in\n\n    %s\n" % (stock.UPDATER_NAME, STOCK_DIR))
            if not interactive():
                sys.exit("No updater in %s." % STOCK_DIR)
            ask("Press Enter when the file is there (q quits): ")
            continue
        for path in found:
            try:
                out = stock.install(path, EXTRACTED)
                print("Stock firmware v1.4 found in %s and extracted to %s." % (os.path.basename(path), os.path.relpath(out, ROOT)))
                return
            except (stock.NotStock, Exception) as ex:          # pefile raises its own on a non-PE file
                print("  %s: %s" % (os.path.basename(path), ex))
        if not interactive():
            sys.exit("No usable updater in %s." % STOCK_DIR)
        ask("Replace the file and press Enter (q quits): ")


# ---- step 2 and 3: the theme and its configs -------------------------------------------------------

def choose_theme(name):
    names = [n for n, _ in THEMES]
    if name is not None:
        if name not in names:
            sys.exit("--theme %s: the themes are %s" % (name, ", ".join(names)))
        return name
    return menu("Which look should the amp have?", [(d, n) for n, d in THEMES], "1")


def parse_set(items, options):
    """--set FEATURE.OPTION=VALUE items against the declared options: {(feature, option): value}."""
    declared = {(f, o): opt for f, o, opt in options}
    values = {}
    for item in items:
        key, sep, raw = item.partition("=")
        feature, dot, option = key.partition(".")
        if not sep or not dot or (feature, option) not in declared:
            sys.exit("--set %s: the options of this image are %s" % (item, ", ".join("%s.%s" % k for k in declared) or "none"))
        try:
            value = int(raw.strip())
        except ValueError:
            value = raw
        values[(feature, option)] = declared[(feature, option)].check(value, "--set %s" % key)
    return values


def choose_values(options, preset):
    """Every option of the image: preset, asked, or the default."""
    values = {}
    if interactive() and options and not all(k in preset for k in ((f, o) for f, o, _ in options)):
        print("\nBuild-time settings. Enter keeps the default shown in brackets.")
    for f, o, opt in options:
        key = (f, o)
        if key in preset:
            values[key] = preset[key]
        elif interactive():
            while True:
                raw = ask("  %s, %d..%d [%d]: " % (opt.help, opt.lo, opt.hi, opt.default), str(opt.default))
                try:
                    values[key] = opt.check(int(raw), "%s.%s" % key)
                    break
                except (ValueError, SystemExit):
                    print("    a whole number from %d to %d, please" % (opt.lo, opt.hi))
        else:
            values[key] = opt.default
    return values


# ---- step 4: the build ---------------------------------------------------------------------------------

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def build_reference(theme):
    """The theme with its defaults, through tools/build.py (bases first, every check): (image, description).
    Comes before the questions: a theme's build module may read its base image when it loads."""
    print("\nBuilding %s with its defaults (the reference image)..." % theme)
    p = subprocess.run([sys.executable, BUILD, "-q", theme], cwd=ROOT, capture_output=True, text=True)
    if p.returncode:
        sys.exit("The build failed:\n" + (p.stdout + p.stderr).rstrip())
    ref = open(features.image(theme), "rb").read()
    known = build.known_images()
    if sha256(ref) not in known:
        sys.exit("The reference image of %s (sha256 %s) is not registered in KNOWN_IMAGES: this bundle is\n"
                 "inconsistent and must not be flashed." % (theme, sha256(ref)[:16]))
    print("  reference: %s" % known[sha256(ref)])
    return ref, known[sha256(ref)]


def build_image(theme, ref, ref_desc, values, out_dir):
    """The user's image: the registered reference with only the configs' bytes changed."""
    options = features.configs(theme)
    changes = {(f, o): (opt.default, values[(f, o)], opt) for f, o, opt in options}
    print("Building %s with your settings..." % theme)
    img = build.variant(theme, values)
    problems = features.config_diff(ref, img, changes)
    if problems:
        sys.exit("The image with your settings does not relate to the reference as the configs promise:\n  "
                 + "\n  ".join(problems) + "\nNothing was written. Report this; do not flash the image.")
    moved = sum(1 for a, b in zip(ref, img) if a != b)
    if moved:
        print("  checked: the reference image with %d byte%s changed, all of them your settings" % (moved, "" if moved == 1 else "s"))
    else:
        print("  checked: identical to the reference image (your settings are its defaults)")

    os.makedirs(out_dir, exist_ok=True)
    stem = "ao300-%s" % theme + "".join("-%s-%d" % (o.lower(), values[(f, o)]) for f, o, _ in options)
    bin_path = os.path.join(out_dir, stem + ".bin")
    open(bin_path, "wb").write(img)
    lines = ["AO300 custom firmware image", "", "file:       %s" % os.path.basename(bin_path),
             "sha256:     %s" % sha256(img), "theme:      %s (RESET page shows %r)" % (theme, features.load(theme).VERSION_TEXT),
             "reference:  %s (sha256 %s)" % (ref_desc, sha256(ref)),
             "settings:   " + (", ".join("%s.%s=%d (default %d)" % (f, o, values[(f, o)], opt.default) for f, o, opt in options) or "none"),
             "bundle:     %s" % bundle_version(), "built:      %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), ""]
    open(bin_path[:-4] + ".txt", "w").write("\n".join(lines))
    print("  wrote %s (%d bytes, sha256 %s...)" % (os.path.relpath(bin_path, ROOT), len(img), sha256(img)[:16]))
    if moved:
        print("  The flasher will call this file \"not a registered image\": only the reference's sha256 is\n"
              "  registered, and the check above is what vouches for yours.")
    return bin_path


# ---- step 5: the flasher ---------------------------------------------------------------------------------

def choose_port(preset):
    if preset:
        return preset
    while True:
        found = ports.scan()
        if len(found) == 1:
            print("\nSerial port: %s" % ports.label(found[0]))
            answer = ask("Enter to use it, or type another device path or rfc2217:// URL: ", found[0].device)
        elif found:
            pick = ports.suggested(found)
            items = [(ports.label(p) + ("  <- suggested" if p is pick else ""), p.device) for p in found]
            answer = menu("Which serial port is the amp?", items + [("another device path or rfc2217:// URL", "?")],
                          str(found.index(pick) + 1) if pick else None)
            if answer == "?":
                answer = ask("Device path or URL: ")
        else:
            print("\nNo USB serial port found. Connect the amp's USB-C socket to this computer with a data\n"
                  "cable and power the amp, then press Enter to look again. Or type a device path, or an\n"
                  "rfc2217://host:port URL for an amp connected to another machine.")
            answer = ask("[Enter: look again] ")
            if not answer:
                continue
        if answer and ports.looks_like_port(answer):
            return answer
        print("  that does not look like a device path or URL")


def flasher_argv(action, port, image=None):
    """The flasher's command line. Choosing flash or recover here is the confirmation, so the
    flasher's typed FLASH question is skipped (-y); its chip checks still gate every write."""
    argv = [sys.executable, FLASHER, "-p", port, action]
    if image:
        argv += [image, "-y"]
    return argv


def run_flasher(action, port, image=None):
    print("\n" + AMP_STEPS[action])
    if action in ("flash", "recover"):
        print("The flasher checks that the chip is a factory AO300 before it writes anything.")
    argv = flasher_argv(action, port, image)
    print("\n$ %s\n" % " ".join(os.path.relpath(a, ROOT) if a.startswith(ROOT) else a for a in argv[1:]))
    rc = subprocess.call(argv, cwd=ROOT)
    if rc and sys.platform.startswith("linux") and port.startswith("/dev/") and not os.access(port, os.R_OK | os.W_OK):
        print("\nThe port is not accessible. On Linux, add yourself to the serial group once and log in\n"
              "again:  sudo usermod -aG dialout \"$USER\"   (uucp on Arch). Do not run the installer with sudo.")
    if rc and action == "flash":
        print("\nIf the flasher erased the chip and then failed, the amp has no firmware until an image is\n"
              "written again: choose \"Restore the stock firmware\" or flash again, from a cold power-up.")
    return rc


def make_updater(bin_path):
    """A Windows updater (.exe) next to the image: the vendor's updater carrying the custom image.
    No serial port is involved. Returns 0, or 1 when there is no vendor updater to copy."""
    vendor = stock.updater(STOCK_DIR)
    if vendor is None:
        print("\nA Windows updater is a copy of SMSL's own updater with the firmware swapped, so the\n"
              "vendor file is needed: put %s in\n    %s\nand choose this item again."
              % (stock.UPDATER_NAME, STOCK_DIR))
        return 1
    out = stock.rebuild_updater(vendor, bin_path, bin_path[:-4] + ".exe")
    print("\nWindows updater: %s (%d bytes)" % (os.path.relpath(out, ROOT), os.path.getsize(out)))
    print("Copy it to the Windows PC the amp is connected to and use it like SMSL's updater: start it,\n"
          "click its start button, then put the amp in STANDBY and press SOURCE on the remote.\n"
          "It carries the image built above. It runs none of this installer's chip checks: use it\n"
          "only on an AO300. It contains SMSL's program and firmware code: keep it for your own amp,\n"
          "do not share or publish it.")
    return 0


def flash_menu(bin_path, port_preset):
    items = [("Flash the custom image onto the amp", "flash"),
             ("Check the connection only (reads the chip, writes nothing)", "identify"),
             ("Restore the stock firmware (recovery)", "recover"),
             ("Make a Windows updater (.exe) with the custom image, to flash from a Windows PC", "exe"),
             ("Quit", "quit")]
    while True:
        action = menu("What next?", items, "1")
        if action == "quit":
            return 0
        if action == "exe":
            make_updater(bin_path)
            continue
        port = choose_port(port_preset)
        image = {"flash": bin_path, "recover": os.path.join(EXTRACTED, "flash.bin")}.get(action)
        rc = run_flasher(action, port, image)
        print("\n%s %s." % (action, "done" if rc == 0 else "did not complete (exit %d)" % rc))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 1)[1])
    ap.add_argument("--theme", choices=[n for n, _ in THEMES], metavar="NAME", help="the look: %s" % ", ".join(n for n, _ in THEMES))
    ap.add_argument("--set", action="append", default=[], metavar="FEATURE.OPTION=VALUE", help="a build-time config")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output folder for the image (default build/out)")
    ap.add_argument("--build-only", action="store_true", help="stop after the build")
    ap.add_argument("--action", choices=["flash", "identify", "recover", "exe"],
                    help="skip the menu (exe: write a Windows updater next to the image, no serial port)")
    ap.add_argument("--port", help="serial device or pyserial URL; skips the detection")
    args = ap.parse_args(argv)

    print("SMSL AO300 custom firmware installer (%s)" % bundle_version())
    print("Everything happens on this computer until the flash step, which asks first.\n")
    ensure_stock()
    theme = choose_theme(args.theme)
    ref, ref_desc = build_reference(theme)
    options = features.configs(theme)
    values = choose_values(options, parse_set(args.set, options))
    print("\nSummary: %s, %s" % (theme, ", ".join("%s.%s=%d" % (f, o, values[(f, o)]) for f, o, _ in options) or "no settings"))
    bin_path = build_image(theme, ref, ref_desc, values, args.out)
    if args.build_only:
        return 0
    if args.action == "exe":
        return make_updater(bin_path)
    if args.action:
        image = {"flash": bin_path, "recover": os.path.join(EXTRACTED, "flash.bin")}.get(args.action)
        return run_flasher(args.action, choose_port(args.port), image)
    return flash_menu(bin_path, args.port)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
