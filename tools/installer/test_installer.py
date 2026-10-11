#!/usr/bin/env python3
"""Tests for the release installer and the build-time config support in features.py.

No serial port is touched. Run: python3 tools/installer/test_installer.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
sys.path.insert(0, HERE)
import features  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "pe"))
import build  # noqa: E402  (tools/build.py)
import ports  # noqa: E402
import stock  # noqa: E402
import ao300_installer as inst  # noqa: E402


class OptionTest(unittest.TestCase):
    def test_check_accepts_the_range_and_rejects_the_rest(self):
        opt = features.Option(default=25, lo=0, hi=60, bytes=2, help="cap")
        self.assertEqual(opt.check(0), 0)
        self.assertEqual(opt.check(60), 60)
        for bad in (61, -1, "30", "x", 25.0, True, None):
            with self.assertRaises(SystemExit):
                opt.check(bad)

    def test_env_name(self):
        self.assertEqual(features.env_name("start-volume", "SPEAKER_LIMIT"), "AO300_START_VOLUME_SPEAKER_LIMIT")

    def test_setting_default_env_and_bad_env(self):
        name = features.env_name("start-volume", "SPEAKER_LIMIT")
        saved = os.environ.pop(name, None)
        try:
            self.assertEqual(features.setting("start-volume", "SPEAKER_LIMIT"), 25)
            os.environ[name] = "30"
            self.assertEqual(features.setting("start-volume", "SPEAKER_LIMIT"), 30)
            os.environ[name] = "61"
            with self.assertRaises(SystemExit) as cm:
                features.setting("start-volume", "SPEAKER_LIMIT")
            self.assertIn(name, str(cm.exception))
        finally:
            os.environ.pop(name, None)
            if saved is not None:
                os.environ[name] = saved

    def test_configs_of_an_image_lists_the_included_fix(self):
        got = features.configs("phosphor-panel")
        keys = [(f, o) for f, o, _ in got]
        self.assertIn(("start-volume", "SPEAKER_LIMIT"), keys)
        self.assertIn(("start-volume", "HEADPHONE_LIMIT"), keys)
        self.assertEqual(features.configs("fast-lcd"), [])


class ConfigDiffTest(unittest.TestCase):
    OPT = features.Option(default=25, lo=0, hi=60, bytes=2, help="cap")

    def changes(self, **kw):
        return {("start-volume", k): v for k, v in kw.items()}

    def test_clean_four_byte_diff(self):
        ref = bytes([0x74, 25, 0xC3, 0x95, 0x31, 0x50, 0x03, 0x75, 0x31, 25,
                     0x74, 20, 0xC3, 0x95, 0x52, 0x50, 0x03, 0x75, 0x52, 20, 0x02])
        new = bytes([0x74, 30, 0xC3, 0x95, 0x31, 0x50, 0x03, 0x75, 0x31, 30,
                     0x74, 60, 0xC3, 0x95, 0x52, 0x50, 0x03, 0x75, 0x52, 60, 0x02])
        ch = {("start-volume", "SPEAKER_LIMIT"): (25, 30, self.OPT),
              ("start-volume", "HEADPHONE_LIMIT"): (20, 60, self.OPT)}
        self.assertEqual(features.config_diff(ref, new, ch), [])

    def test_no_change_is_clean(self):
        ref = bytes(range(40))
        ch = {("start-volume", "SPEAKER_LIMIT"): (25, 25, self.OPT)}
        self.assertEqual(features.config_diff(ref, ref, ch), [])

    def test_length_change_is_a_problem(self):
        ref = bytes(40)
        ch = {("start-volume", "SPEAKER_LIMIT"): (25, 30, self.OPT)}
        self.assertTrue(features.config_diff(ref, ref + b"\0", ch))

    def test_stray_byte_is_a_problem(self):
        ref = bytes([25, 0, 25, 0, 7])
        new = bytes([30, 0, 30, 0, 8])
        ch = {("start-volume", "SPEAKER_LIMIT"): (25, 30, self.OPT)}
        problems = features.config_diff(ref, new, ch)
        self.assertTrue(any("0x0004" in p for p in problems), problems)

    def test_wrong_count_is_a_problem(self):
        ref = bytes([25, 0, 25, 0, 25])
        new = bytes([30, 0, 30, 0, 30])
        ch = {("start-volume", "SPEAKER_LIMIT"): (25, 30, self.OPT)}
        problems = features.config_diff(ref, new, ch)
        self.assertTrue(any("3" in p and "2" in p for p in problems), problems)

    def test_byte_that_is_not_old_to_new_is_a_problem(self):
        ref = bytes([25, 0, 25, 0])
        new = bytes([30, 0, 31, 0])
        ch = {("start-volume", "SPEAKER_LIMIT"): (25, 30, self.OPT)}
        self.assertTrue(features.config_diff(ref, new, ch))


@unittest.skipUnless(os.path.isfile(features.STOCK_IMAGE), "needs the stock image")
class BuildConfigCheckTest(unittest.TestCase):
    """tools/build.py checks the config promise on every image that contains a CONFIG feature."""

    def test_variants_of_start_volume_keep_the_promise(self):
        errors, notes = build.config_check("start-volume")
        self.assertEqual(errors, [])
        self.assertTrue(any("SPEAKER_LIMIT" in n for n in notes), notes)

    def test_an_image_without_configs_has_nothing_to_check(self):
        self.assertEqual(build.config_check("fast-lcd"), ([], []))

    def test_variant_build_leaves_the_default_image_alone(self):
        before = open(features.image("start-volume"), "rb").read()
        build.config_check("start-volume")
        self.assertEqual(open(features.image("start-volume"), "rb").read(), before)
        self.assertFalse(os.path.exists(features.image("start-volume") + ".variant"))


class FakePort:
    def __init__(self, device, vid=None, pid=None, description="n/a", manufacturer=None):
        self.device, self.vid, self.pid, self.description, self.manufacturer = device, vid, pid, description, manufacturer


class PortsTest(unittest.TestCase):
    def test_only_usb_ports_are_candidates(self):
        found = ports.candidates([FakePort("/dev/cu.Bluetooth-Incoming-Port"),
                                  FakePort("/dev/cu.usbserial-10", 0x1A86, 0x7523, "USB Serial"),
                                  FakePort("/dev/cu.debug-console")])
        self.assertEqual([p.device for p in found], ["/dev/cu.usbserial-10"])

    def test_tty_twin_of_a_cu_port_is_dropped_on_macos(self):
        found = ports.candidates([FakePort("/dev/tty.usbserial-10", 0x1A86, 0x7523),
                                  FakePort("/dev/cu.usbserial-10", 0x1A86, 0x7523)])
        self.assertEqual([p.device for p in found], ["/dev/cu.usbserial-10"])

    def test_known_adapters_get_a_name(self):
        self.assertIn("CH340", ports.label(FakePort("/dev/ttyUSB0", 0x1A86, 0x7523)))
        self.assertIn("CP210", ports.label(FakePort("/dev/ttyUSB0", 0x10C4, 0xEA60)))
        self.assertIn("FTDI", ports.label(FakePort("/dev/ttyUSB0", 0x0403, 0x6001)))
        self.assertIn("1234:ABCD", ports.label(FakePort("/dev/ttyUSB1", 0x1234, 0xABCD, "Thing")))

    def test_the_only_known_adapter_among_several_ports_is_suggested(self):
        found = ports.candidates([FakePort("/dev/ttyACM0", 0x2341, 0x0043, "Arduino Uno"),
                                  FakePort("/dev/ttyUSB0", 0x1A86, 0x7523, "USB Serial")])
        self.assertEqual(ports.suggested(found).device, "/dev/ttyUSB0")

    def test_no_suggestion_with_two_known_adapters_or_none(self):
        two = ports.candidates([FakePort("/dev/ttyUSB0", 0x1A86, 0x7523), FakePort("/dev/ttyUSB1", 0x10C4, 0xEA60)])
        self.assertIsNone(ports.suggested(two))
        unknown = ports.candidates([FakePort("/dev/ttyACM0", 0x2341, 0x0043), FakePort("/dev/ttyACM1", 0x2341, 0x0043)])
        self.assertIsNone(ports.suggested(unknown))
        self.assertIsNone(ports.suggested([]))

    def test_a_single_port_is_suggested_even_when_unknown(self):
        one = ports.candidates([FakePort("/dev/ttyACM0", 0x2341, 0x0043)])
        self.assertEqual(ports.suggested(one).device, "/dev/ttyACM0")

    def test_url_or_path_typed_by_the_user_is_accepted(self):
        self.assertTrue(ports.looks_like_port("rfc2217://host:4000"))
        self.assertTrue(ports.looks_like_port("/dev/ttyUSB0"))
        self.assertFalse(ports.looks_like_port("yes"))
        self.assertFalse(ports.looks_like_port(""))


class StockTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def test_empty_folder_finds_nothing(self):
        self.assertEqual(stock.find(self.dir), [])

    def test_wrong_bin_is_refused_with_its_sha(self):
        path = os.path.join(self.dir, "flash.bin")
        open(path, "wb").write(b"\x02\x44\x9f" + bytes(100))
        self.assertEqual([os.path.basename(p) for p in stock.find(self.dir)], ["flash.bin"])
        with self.assertRaises(stock.NotStock) as cm:
            stock.install(path, os.path.join(self.dir, "extracted"))
        self.assertIn("sha256", str(cm.exception))

    @unittest.skipUnless(os.path.isfile(features.STOCK_IMAGE), "needs the stock image")
    def test_real_flash_bin_is_installed(self):
        import shutil
        src = os.path.join(self.dir, "flash.bin")
        shutil.copy(features.STOCK_IMAGE, src)
        out = stock.install(src, os.path.join(self.dir, "extracted"))
        self.assertEqual(out, os.path.join(self.dir, "extracted", "flash.bin"))
        self.assertEqual(stock.sha256_file(out), features.STOCK_SHA)
        self.assertTrue(stock.is_installed(os.path.join(self.dir, "extracted")))

    @unittest.skipUnless(os.path.isfile(os.path.join(ROOT, "original", "SMSL_AO300_UPDATE_VER0A5_EN.exe")),
                         "needs the vendor updater")
    def test_vendor_exe_is_unpacked(self):
        import shutil
        exe = os.path.join(self.dir, "Updater.EXE")      # any name, any case
        shutil.copy(os.path.join(ROOT, "original", "SMSL_AO300_UPDATE_VER0A5_EN.exe"), exe)
        self.assertEqual(stock.find(self.dir), [exe])
        out = stock.install(exe, os.path.join(self.dir, "extracted"))
        self.assertEqual(stock.sha256_file(out), features.STOCK_SHA)


class ParseSetTest(unittest.TestCase):
    def test_values_are_matched_to_the_declared_options(self):
        got = inst.parse_set(["start-volume.SPEAKER_LIMIT=30", "start-volume.HEADPHONE_LIMIT=60"],
                             features.configs("phosphor-panel"))
        self.assertEqual(got, {("start-volume", "SPEAKER_LIMIT"): 30, ("start-volume", "HEADPHONE_LIMIT"): 60})

    def test_unknown_option_and_bad_value_stop(self):
        opts = features.configs("phosphor-panel")
        with self.assertRaises(SystemExit):
            inst.parse_set(["start-volume.NOPE=1"], opts)
        with self.assertRaises(SystemExit):
            inst.parse_set(["start-volume.SPEAKER_LIMIT=61"], opts)
        with self.assertRaises(SystemExit):
            inst.parse_set(["SPEAKER_LIMIT=30"], opts)


class FlasherArgvTest(unittest.TestCase):
    """The menu choice is the confirmation: flash and recover run the flasher with -y."""

    def test_flash_and_recover_skip_the_typed_confirmation(self):
        argv = inst.flasher_argv("flash", "/dev/ttyUSB0", "/x/image.bin")
        self.assertEqual(argv[-4:], ["/dev/ttyUSB0", "flash", "/x/image.bin", "-y"])
        self.assertEqual(inst.flasher_argv("recover", "rfc2217://h:4000", "/x/stock.bin")[-3:], ["recover", "/x/stock.bin", "-y"])

    def test_identify_takes_no_image(self):
        self.assertEqual(inst.flasher_argv("identify", "/dev/ttyUSB0")[-2:], ["/dev/ttyUSB0", "identify"])


@unittest.skipUnless(os.path.isfile(features.STOCK_IMAGE), "needs the stock image")
class EndToEndBuildTest(unittest.TestCase):
    """The installer, unattended, builds a user's image for both themes: the registered reference
    image with only the four limit bytes changed, and a text file naming its sha."""

    def setUp(self):
        import tempfile
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.out)

    def run_installer(self, *args):
        import subprocess
        p = subprocess.run([sys.executable, os.path.join(HERE, "ao300_installer.py"), "--build-only", "--out", self.out]
                           + list(args), cwd=ROOT, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def check_theme(self, theme):
        code, out = self.run_installer("--theme", theme, "--set", "start-volume.SPEAKER_LIMIT=30",
                                       "--set", "start-volume.HEADPHONE_LIMIT=60")
        self.assertEqual(code, 0, out)
        bins = [n for n in os.listdir(self.out) if n.endswith(".bin")]
        self.assertEqual(len(bins), 1, os.listdir(self.out))
        self.assertIn(theme, bins[0])
        self.assertIn("30", bins[0])
        self.assertIn("60", bins[0])
        img = open(os.path.join(self.out, bins[0]), "rb").read()
        ref = open(features.image(theme), "rb").read()
        self.assertEqual(len(img), len(ref))
        diff = [(i, ref[i], img[i]) for i in range(len(ref)) if ref[i] != img[i]]
        self.assertEqual(sorted(set((a, b) for _, a, b in diff)), [(20, 60), (25, 30)])
        self.assertEqual(len(diff), 4)
        txt = open(os.path.join(self.out, bins[0][:-4] + ".txt")).read()
        self.assertIn(stock.sha256_file(os.path.join(self.out, bins[0])), txt)
        self.assertIn("SPEAKER_LIMIT", txt)
        self.assertIn("30", txt)

    def test_phosphor_panel(self):
        self.check_theme("phosphor-panel")

    def test_house_numerals(self):
        self.check_theme("house-numerals")

    def test_default_values_rebuild_the_registered_image(self):
        code, out = self.run_installer("--theme", "phosphor-panel")
        self.assertEqual(code, 0, out)
        bins = [n for n in os.listdir(self.out) if n.endswith(".bin")]
        self.assertEqual(open(os.path.join(self.out, bins[0]), "rb").read(), open(features.image("phosphor-panel"), "rb").read())

    def test_unknown_theme_stops(self):
        code, out = self.run_installer("--theme", "probe")
        self.assertNotEqual(code, 0)
        self.assertIn("probe", out)


@unittest.skipUnless(os.path.isfile(features.STOCK_IMAGE), "needs the stock image")
class ReleaseTest(unittest.TestCase):
    """tools/release.py: a zip with the installer and what the two themes need, and no firmware."""

    def setUp(self):
        import tempfile
        self.dist = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dist)

    def test_release_zip_contents(self):
        import subprocess
        import zipfile
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "--dist", self.dist, "--no-selftest"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        zips = [n for n in os.listdir(self.dist) if n.endswith(".zip")]
        self.assertEqual(len(zips), 1, os.listdir(self.dist))
        self.assertTrue(zips[0].startswith("ao300-custom-"))
        names = zipfile.ZipFile(os.path.join(self.dist, zips[0])).namelist()
        top = zips[0][:-4] + "/"
        self.assertTrue(all(n.startswith(top) for n in names), names[:5])
        rel = [n[len(top):] for n in names]
        for want in ("install.sh", "README.md", "requirements.txt", "VERSION", "original/README.txt",
                     "tools/installer/ao300_installer.py", "tools/installer/ports.py", "tools/installer/stock.py",
                     "tools/patch/features.py", "tools/patch/uikit.py", "tools/patch/asm51.py", "tools/patch/pfont.py",
                     "tools/pe/stc_release.py", "tools/flash/flash_ao300.py", "tools/build.py",
                     "tools/fonts/raster/disp52.json", "features/fast-lcd/build_patch.py",
                     "features/house-numerals/build_patch.py", "features/house-numerals/layout.json",
                     "features/phosphor-panel/build_patch.py", "features/start-volume/start_volume.py",
                     "features/direct-select/direct_select.py", "features/fix-volume-pop/fix_volume_pop.py",
                     "features/strings/strings.py", "features/fix-auto-off/fix_auto_off.py",
                     "features/fix-menu-input/fix_menu_input.py"):
            self.assertIn(want, rel, want)
        for bad in rel:
            self.assertFalse(bad.endswith((".bin", ".exe", ".hex", ".asm", "emu_test.py", "test_installer.py", "uikit_test.py")), bad)
            self.assertNotIn("/build/", bad)
            self.assertNotIn("extracted", bad)
            self.assertNotIn("probe", bad)
            self.assertNotIn("auto-switch", bad)
        info = zipfile.ZipFile(os.path.join(self.dist, zips[0])).getinfo(top + "install.sh")
        self.assertTrue(info.external_attr >> 16 & 0o111, "install.sh must be executable")

    def test_release_refuses_firmware_in_the_whitelist(self):
        import subprocess
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release.py"), "--dist", self.dist, "--no-selftest",
                            "--also", "original/extracted/flash.bin"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("firmware", (p.stdout + p.stderr).lower())
        self.assertEqual([n for n in os.listdir(self.dist) if n.endswith(".zip")], [])


if __name__ == "__main__":
    unittest.main()
