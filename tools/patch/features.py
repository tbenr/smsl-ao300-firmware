"""The feature graph: which image each feature builds on, and which fixes it links in.

Every features/<name>/build_patch.py declares two things next to its other constants:

    BASE = "fast-lcd"               # the image it stacks on: another feature, or "stock"
    INCLUDES = ["fix-auto-off"]     # fix features whose code it links into its own image

and takes its input from the graph instead of a hand-written path:

    BASE_IMAGE = features.image(BASE)
    BASE_SHA = "..."                # still pinned: a rebuilt parent must be re-checked

A fix is a feature whose folder also holds <name with _>.py exporting HOOK (a
uikit.build_image hook tuple) and emit(a). Its own build_patch.py is only its standalone
image. tools/build.py walks this graph: it builds in order and checks the result.
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FEATURES = os.path.join(ROOT, "features")
STOCK = "stock"
STOCK_IMAGE = os.path.join(ROOT, "original", "extracted", "flash.bin")
STOCK_SHA = "85e8ac50ffcf47ea159a976edbcd398e81345c0ceb3b1542e97e80a800adb0cc"
VERSION_PTR_BYTES = (0x22CB, 0x22CD)   # repointed by every image (version string address)

_modules = {}


def names():
    """Features that build an image (have a build_patch.py), sorted."""
    return sorted(n for n in os.listdir(FEATURES) if os.path.isfile(os.path.join(FEATURES, n, "build_patch.py")))


def _load(key, path):
    """Import a file as a module, without leaving its sys.path changes behind."""
    if key not in _modules:
        saved = list(sys.path)
        try:
            mod = types.ModuleType(key)
            mod.__file__ = path
            sys.modules[key] = _modules[key] = mod    # registered first: a base cycle fails, not recurses
            # compiled from source every time: a .pyc is only checked by size and whole-second mtime
            exec(compile(open(path).read(), path, "exec"), mod.__dict__)
        except BaseException:
            _modules.pop(key, None)
            raise
        finally:
            sys.path[:] = saved
    return _modules[key]


def load(name):
    """A feature's build_patch module (imported once; importing does not build)."""
    path = os.path.join(FEATURES, name, "build_patch.py")
    if not os.path.isfile(path):
        raise SystemExit("no feature %r (no %s)" % (name, os.path.relpath(path, ROOT)))
    return _load("feature_" + name.replace("-", "_"), path)


def image(name):
    """Path of the image a feature builds; "stock" is the extracted v1.4 image."""
    return STOCK_IMAGE if name == STOCK else load(name).OUT_IMAGE


def is_fix(name):
    return os.path.isfile(os.path.join(FEATURES, name, name.replace("-", "_") + ".py"))


def fix(name):
    """A fix's module (HOOK, emit), for a build that lists it in INCLUDES."""
    if not is_fix(name):
        raise SystemExit("%r is not a fix (no features/%s/%s.py)" % (name, name, name.replace("-", "_")))
    mod = _load("fix_" + name.replace("-", "_"), os.path.join(FEATURES, name, name.replace("-", "_") + ".py"))
    if not (hasattr(mod, "HOOK") and hasattr(mod, "emit")):
        raise SystemExit("fix %r must export HOOK and emit(a)" % name)
    return mod


def fixes(names):
    """The fix modules of an INCLUDES list. A build links them in two places:

        HOOKS += [f.HOOK for f in FIXES]      # uikit.build_image hooks
        for f in FIXES: f.emit(a)             # in assemble(), anywhere in its code
    """
    return [fix(n) for n in names]


def base(name):
    return load(name).BASE


def includes(name):
    return list(getattr(load(name), "INCLUDES", []))


def chain(name):
    """[name, parent, ..., "stock"]."""
    out = [name]
    while out[-1] != STOCK:
        out.append(base(out[-1]))
        if out[-1] in out[:-1]:
            raise SystemExit("base cycle: %s" % " -> ".join(out))
    return out


def order(targets=None):
    """Features in build order (every base before its children): all, or targets and their bases."""
    want = set()
    for n in targets or names():
        want.update(c for c in chain(n) if c != STOCK)
    return sorted(want, key=lambda n: (len(chain(n)), n))     # a base is always shallower


def children(name):
    return [n for n in names() if base(n) == name]
