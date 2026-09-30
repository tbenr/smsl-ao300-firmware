# Fix: Auto OFF after power-on

A stock bug, fixed by SMSL in the AO300 PRO V1.2 and ported here. With Dimmer set to
Auto OFF, the display should go dark a few seconds after the last key. After a cold
power-up it stays lit until the first key press. The standalone image is stock plus the
fix; the RESET page shows `v1.4 tbenr aof3` (aof1 and aof2 were the same fix on direct-select).

## Status

Verified on the amp on 2026-09-29, as part of house-numerals hn7 (included since hn6.1): with
Dimmer on Auto OFF the display goes dark after a cold power-up. The standalone image itself has
not been flashed.

## The bug

- The screen-off countdown is `g_screen_off` (RAM 0x2F:0x30), counted in main ticks.
  `main_tick_tasks` decrements it at 0x33DB through `countdown16_dec` (0x5A78), but only
  while `g_dimmer_mode` (0x29) is 2. When it reaches 0, `clr P0.6` turns the backlight off.
- `countdown16_dec` does nothing while the counter is 0. The counter only moves after
  something arms it: every key in `dispatch_key` (0x0BBD) and the Dimmer menu (0x124A,
  0x14CD) set it to 500.
- `post_power_on` (0x5585) never arms it. After a cold power-up the counter is 0, so the
  backlight stays on. Standby → on is different: the remote's Power key that entered
  standby went through `dispatch_key` and armed the counter, which froze in standby.
- The PRO's post-power-on routine (0x4F2E in that image) ends with the same arming code as
  its key dispatcher: `if dimmer == 2: countdown = (dimmer - 1) * 500`. In the PRO the
  dimmer is RAM 0x2A and the countdown 0x31:0x32.

## The fix

One hook: the `ljmp ui_clear_screen` (0x55B9) that ends `post_power_on` now jumps to
`fx_auto_off` instead:

```
fx_auto_off:  mov A,0x29 ; cjne A,#2,done ; mov 0x2F,#0x01 ; mov 0x30,#0xF4
done:         ljmp 0x5D42                    ; the stock tail call
```

That is 14 bytes. It arms before the jump, so the stack depth stays as in stock. The
countdown is only read in the main loop, so arming before the screen clear rather than
after (as the PRO does) makes no difference. There are no new variables.

## Including it in another build

`fix_auto_off.py` holds the fix on its own. `build_patch.py` here is only its standalone
image. A build includes it through the feature graph (README, "Feature graph"):

```python
INCLUDES = ["fix-auto-off"]
HOOKS = [...] + [f.HOOK for f in features.fixes(INCLUDES)]   # (0x55B9, 02 5D 42, ljmp, "fx_auto_off")
...
for f in features.fixes(INCLUDES):                           # in assemble(), anywhere in the code
    f.emit(a)
```

`tools/build.py` checks that the hook is installed. That build's tests should expect the
two hook bytes 0x55BA/0x55BB in their image diff. `run_tests.py` then also runs "fix-auto-off
in <that image>": this test's `integration()` on the including image. Tried with
house-numerals: off 5.10 s after power-on, 4.99 s after a key.

The fix ends with `ljmp 0x5D42`. In house-numerals that address is hooked (`hn_cancel`), and
the clear it leads to is fast-lcd's. That is fine: stock's own jump lands there too. The
integration test is what confirms it.

## Tests (`emu_test.py`)

- **Hook.** `post_power_on`'s tail with dimmer 0..3 and two preset counter values: the
  counter becomes 0x01F4 only with dimmer 2. Every other RAM byte, SP and the screen match
  stock.
- **IR sweep.** All 256 NEC commands through 0x5D10, with dimmer 1 and 2, in standby and on
  pages 0..3, match stock.
- **Image diff.** Only 0x55BA, 0x55BB and the version pointer change. The code sits at
  0x9680, a slot no other feature uses.
- **Full firmware, base and fix side by side.** Both boot from reset on `Amp`, which runs
  the real Timer0 ISR and `timer3_isr`. Without Timer3 the encoder key 0x2D stays 0 and
  `read_key` feeds key 0 on every idle pass, which keeps re-arming the countdown (the test
  used to add Timer3 itself; `Amp` does it since 2026-09-29). Dimmer is seeded into the
  EEPROM read at offset 0x020B.
  - Auto OFF, cold power-up: the fix turns the backlight off 5.98 s after `post_power_on`,
    while stock is still lit 15 s after Power.
  - Vol+ afterwards: both light up and go off after 5.66 s.
  - Standby then Power: both go off within one main tick of each other (40.28 s and
    40.29 s).
  - Always ON: both images produce the same 339 audio and backlight events.

500 main ticks come to about 6 s instead of 5 because main-loop passes miss some 10 ms
ticks. The amp may differ slightly.
