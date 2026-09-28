#!/usr/bin/env python3
"""Run the emulator tests in parallel and print each one's full output.

    python3 tools/run_tests.py                 every features/*/emu_test.py
    python3 tools/run_tests.py fast-lcd        only the named features
    python3 tools/run_tests.py --core          also tools/emu/test_core.py (C core
                                               against the Python reference)

The tests only read the images and write their own build/ renders, so they can run
at once. Each output is printed whole when its test finishes, then a summary. Exit
status 1 if any test fails. EMU8051=py in the environment runs them on the Python
reference emulator instead of the C core.
"""
import argparse
import glob
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(name, cmd):
    t = time.time()
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return name, p.returncode, p.stdout + p.stderr, time.time() - t


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("features", nargs="*", help="feature folders to test (default: all)")
    ap.add_argument("--core", action="store_true", help="also run tools/emu/test_core.py")
    args = ap.parse_args()

    tests = []
    for path in sorted(glob.glob(os.path.join(ROOT, "features", "*", "emu_test.py"))):
        name = os.path.basename(os.path.dirname(path))
        if not args.features or name in args.features:
            tests.append((name, [sys.executable, path]))
    missing = set(args.features) - {n for n, _ in tests}
    if missing:
        sys.exit("no emu_test.py in features/%s" % ", features/".join(sorted(missing)))
    if args.core:
        tests.append(("emu core", [sys.executable, os.path.join(ROOT, "tools", "emu", "test_core.py")]))

    if os.environ.get("EMU8051") != "py":         # build the C core once, before the tests start
        sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
        try:
            import cemu8051  # noqa: F401
        except Exception as ex:
            print("C core unavailable (%s); the tests fall back to the Python reference" % ex)

    t0 = time.time()
    results = {}
    with ThreadPoolExecutor(len(tests)) as pool:
        for f in as_completed([pool.submit(run, n, c) for n, c in tests]):
            name, code, out, secs = f.result()
            results[name] = (code, secs)
            print("=" * 78)
            print("%s  (exit %d, %.1f s)" % (name, code, secs))
            print("=" * 78)
            print(out.rstrip() + "\n", flush=True)

    print("Summary (%.1f s wall)" % (time.time() - t0))
    for name, _ in tests:
        code, secs = results[name]
        print("  %-16s %s  %6.1f s" % (name, "PASS" if code == 0 else "FAIL", secs))
    sys.exit(0 if all(c == 0 for c, _ in results.values()) else 1)


if __name__ == "__main__":
    main()
