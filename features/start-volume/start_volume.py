"""start-volume: cap the volume at power-on, with limits chosen at build time.

Stock restores the volume left at shutdown, up to 60 on either output: settings_load_eeprom
only clamps g_volume (0x31) and g_volume_hp (0x52) to 0..60, and nothing on the power-on path
lowers them. After a loud session the amp comes back loud.

Other builds list "start-volume" in INCLUDES and link HOOK and emit(a) through
features.fixes(INCLUDES) (tools/patch/features.py; README, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

DISABLED = None                       # no cap for that output: it starts at the last volume, as stock

# ---- the config: two independent limits, each a volume step 0..60 or DISABLED ---------------------
SPEAKER_LIMIT = 25
HEADPHONE_LIMIT = 20

# post_power_on's `lcall audio_chips_init` becomes `lcall sv_limit`
HOOK = (0x5596, bytes([0x12, 0x50, 0xD1]), 0x12, "sv_limit")
XDATA = []                            # XDATA the fix uses: none (stock RAM 0x31, 0x52 only)


VOLUME_MAX = 60                       # the volume keys stop here (0x0D58)


def _checked(name, limit):
    if limit is DISABLED or (type(limit) is int and 0 <= limit <= VOLUME_MAX):
        return limit
    raise SystemExit("start-volume: %s must be a volume step 0..%d or DISABLED, not %r" % (name, VOLUME_MAX, limit))


def _cap(a, limit, ram, what, done):
    """`ram` = min(`ram`, limit); nothing for a disabled limit. Volumes are 0..60, so the
    compare is unsigned: limit - volume borrows only when the volume is above the limit."""
    if limit is DISABLED:
        a.comment("%s: no limit, starts at the last volume as stock" % what)
        return
    S(a, """
mov A,#0x%02X               ; %s limit %d
clr C
subb A,0x%02X               ; limit - volume
jnc %s                      ; volume <= limit: keep it
mov 0x%02X,#0x%02X
""" % (limit, what, limit, ram, done, ram, limit))


def emit(a, speaker=SPEAKER_LIMIT, headphone=HEADPHONE_LIMIT):
    speaker, headphone = _checked("SPEAKER_LIMIT", speaker), _checked("HEADPHONE_LIMIT", headphone)
    S(a, """
; sv_limit: replaces post_power_on's `lcall audio_chips_init` (0x5596). Cold power-up and the
; wake from standby both come through here with the outputs muted, before the first volume
; write (volume_apply at 0x510A). Cap g_volume (speakers) and g_volume_hp (headphones) at
; their limits, whichever output is active, then go on into audio_chips_init, which returns
; to 0x5599: the stack depth is as stock. The capped value is what stock then shows, applies
; and saves; the volume keys are not touched.
sv_limit:
""")
    _cap(a, speaker, 0x31, "g_volume, speakers", "sv_hp")
    S(a, "sv_hp:")
    _cap(a, headphone, 0x52, "g_volume_hp, headphones", "sv_go")
    S(a, """
sv_go:
ljmp 0x50D1                 ; audio_chips_init
""")
