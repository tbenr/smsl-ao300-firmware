"""The stock firmware for the installer: find the vendor updater or an extracted image in a
folder, unpack it, and install it as <extracted>/flash.bin after checking its sha256. Also the
way back: a copy of the vendor updater carrying a custom image, for flashing from Windows.

The build (tools/patch/features.py) reads the stock image from original/extracted/flash.bin.
Only firmware v1.4 (sha256 features.STOCK_SHA) is supported: every patch address refers to it.
"""
import hashlib
import os

import features
import stc_release

UPDATER_NAME = "SMSL_AO300_UPDATE_VER0A5_EN.EXE"


class NotStock(Exception):
    """The file is not the stock v1.4 image."""


def sha256_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def find(folder):
    """Vendor updaters (*.exe, any name) and flash images (*.bin) directly in the folder, sorted."""
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, n) for n in os.listdir(folder)
                  if n.lower().endswith((".exe", ".bin")) and os.path.isfile(os.path.join(folder, n)))


def is_installed(extracted):
    path = os.path.join(extracted, "flash.bin")
    return os.path.isfile(path) and sha256_file(path) == features.STOCK_SHA


def image_of(path):
    """The flash image inside a vendor updater, or the file itself for a .bin."""
    if path.lower().endswith(".exe"):
        table, blob = stc_release.load(path)
        recs, _ = stc_release.records(stc_release.decrypt(table, blob))
        for typ, data in recs:
            if typ == 0xFF:
                return data
        raise NotStock("%s: no flash image record in the updater" % path)
    return open(path, "rb").read()


def install(path, extracted):
    """Unpack or copy `path` to <extracted>/flash.bin; NotStock when it is not firmware v1.4."""
    data = image_of(path)
    h = hashlib.sha256(data).hexdigest()
    if h != features.STOCK_SHA:
        raise NotStock("%s is not the stock v1.4 firmware: sha256 %s, expected %s. Only v1.4 (%s) is supported."
                       % (os.path.basename(path), h[:16], features.STOCK_SHA[:16], UPDATER_NAME))
    os.makedirs(extracted, exist_ok=True)
    out = os.path.join(extracted, "flash.bin")
    open(out, "wb").write(data)
    return out


def updater(folder):
    """The vendor updater in the folder: the first .exe that carries the stock v1.4 image, or None
    (a user may have supplied only a flash.bin)."""
    for path in find(folder):
        if path.lower().endswith(".exe"):
            try:
                if hashlib.sha256(image_of(path)).hexdigest() == features.STOCK_SHA:
                    return path
            except (NotStock, Exception):                    # pefile raises its own on a non-PE file
                pass
    return None


def rebuild_updater(vendor_exe, image_path, out_exe):
    """A Windows updater carrying the image: a copy of the vendor's .exe with its firmware record
    replaced (stc_release.rebuild_exe). The vendor file is only read. The result is unpacked
    again and must give back the image byte for byte."""
    image = open(image_path, "rb").read()
    table, blob = stc_release.load(vendor_exe)
    recs, trailer = stc_release.records(stc_release.decrypt(table, blob))
    recs = [(typ, image if typ == 0xFF else data) for typ, data in recs]
    os.makedirs(os.path.dirname(os.path.abspath(out_exe)), exist_ok=True)
    stc_release.rebuild_exe(vendor_exe, stc_release.encrypt(table, stc_release.build(recs, trailer)), out_exe)
    if image_of(out_exe) != image:
        os.remove(out_exe)
        raise NotStock("the rebuilt updater does not unpack to the image again; nothing was kept")
    return out_exe
