# Fix: an input chosen in the menu is switched as the Source key switches it

Stock switches an input chosen in the menu by another path than the Source key: it turns
one supply off for 3 s and sets every audio chip up again, with the speaker path open, and
the amp pops. With this fix the menu's choice does what the Source key does. The standalone
image is stock plus the fix; the RESET page shows `v1.4 tbenr mi1`.

## Status

Verified on the amp on 2026-10-02, as part of house-numerals hn15: no pop on an input change
any more, through the menu, the Source key or direct-select. Emulator-verified (all tests
pass, including "fix-menu-input in house-numerals"). The standalone image itself has not been
flashed.

The pop was heard on the amp the same day on an input change through the menu (hn14; stock
code). Whether it came at the key or 3 to 4 s later was not noted.

## What stock does

Enter on the menu's INPUT list (0x11F8) stores the input and calls `input_menu_select`
(0x588B). A second caller at 0x1489 reaches it for key code 0x0F on the same page.

```
588B: mov 0x59,R7
588D: lcall reset_timer_37      ; settings save armed
5890: clr 0x22.4
5892: lcall audio_apply_mute    ; NJW1194 mute code, DAC mute; P2.2 is not set
5895: clr P4.0                  ; one of the two supply enables
5897: mov 0x41,#0x01 / mov 0x42,#0x2C   ; 300 main ticks
589D: mov 0x45,#0x01 ...        ; page, refresh countdown, ui_clear_screen, list state
```

When 0x41:0x42 runs out, the main loop (0x3375) sets P4.0 high, waits, and runs
`expander_init` and `audio_chips_init`: the resets on P4.3 and P2.1, the clock generator,
the receiver, the DAC reset on P3.4, `input_set_hw`, tone, filter, volume, and the unmute.

The Source key instead runs `input_step` and `input_apply` (0x5628, 0x5640): mute by
register, format poll in 10 ticks, unmute countdown 200 ticks, `input_set_hw`. direct-select
calls `input_apply` too. Neither touches P4.0.

What goes wrong on the menu's path, from the emulator (hn14, times from the Enter key):

| Time | Event |
|---|---|
| 0.00 s | NJW1194 and DAC muted by register, P4.0 low; P2.2 stays low (speakers not muted) |
| 0.47 s | on inputs 1 to 5 the format poll unmutes the NJW1194 and the DAC again |
| 3.07 s | P4.0 high |
| 3.08 to 3.18 s | P4.3 and P2.1 low (resets) |
| 3.20 to 3.71 s | P3.4 low (DAC reset) |
| 3.83 s | P2.2 high, for 75 ms |
| 3.90 s | unmute |

- It runs for every choice, the current input included, so it is not about jumping over
  inputs.
- The second `expander_init` leaves expander P0_4 low (output register 0x02 = 0x00). The
  power-on code sets it high afterwards; this path does not. P0_4's role is inferred (the
  Bluetooth module's clear-pairings line).
- What P4.0 powers is not known, nor why SMSL cycles it here.

## The patch

One hook, 23 bytes of new code: `input_menu_select`'s `lcall audio_apply_mute` (0x5892)
becomes `ljmp mi_switch`.

```
mi_switch:  lcall 0x58D3                      ; audio_apply_mute
            mov 0x4B,#0x00 ; mov 0x4C,#0x0A   ; format poll in 10 ticks, as input_step
            mov 0x43,#0x00 ; mov 0x44,#0xC8   ; unmute countdown 200 ticks, as input_apply
            mov R7,0x47
            lcall 0x24D6                      ; input_set_hw
            ljmp 0x589D                       ; input_menu_select's tail
```

- The eight bytes at 0x5895..0x589C (`clr P4.0` and the countdown) are no longer reached.
  0x41:0x42 stays 0, so the main loop's re-init never runs. P4.0 is only switched by
  power-on and standby.
- The menu's own handling is stock's: the settings save, the page, the list state, the
  clear. Only the hardware part differs.
- A jump in and a jump back, so `input_set_hw` runs one call below the key handler, as on
  the Source key's path.
- The current input chosen again is switched again (2 s mute, `input_set_hw`). Stock ran
  its whole cycle there. The Source key and direct-select never re-apply the current input.
- No new variables.

## Dependencies

None. It is a fix on stock like the others. direct-select calls the stock `input_apply`, this
calls the stock `input_set_hw`; neither changes what the other uses, and either can be in an
image without the other.

## What cannot be checked in the emulator

Whether a chip on the P4.0 supply needs that power cycle. Against it: the Source key and
direct-select switch every input without it, direct-select to any input from any other, and
both work on the amp. For all 30 input pairs, with a signal on every input, the stock menu
path and this one end with the same MCU pins, NJW1194 words and I2C registers, apart from
P0_4 (now left high, as after power-on) and the DAC on AUX (stock resets it; AUX does not
use it).

## Including it in another build

`fix_menu_input.py` holds the fix on its own (`HOOK`, `emit(a)`, `XDATA = []`);
`build_patch.py` here is only its standalone image. A build lists it in `INCLUDES` (README,
"Feature graph"), as house-numerals does since hn15. `tools/build.py` checks that the hook is
installed, and `run_tests.py` runs "fix-menu-input in <that image>": this test's
`integration()` on the including image.

## Tests (`emu_test.py`)

- **Image diff.** Only 0x5892..0x5894 and the version pointer change. The code sits at
  0x9650, a slot no other feature uses.
- **Hook.** `input_menu_select` run from its entry for every input, with `audio_apply_mute`
  and `input_set_hw` recorded instead of run. Stock: mute, P4.0 low, countdown 300, no
  `input_set_hw`. Patch: mute, `input_set_hw(input)`, unmute countdown 200, format poll 10,
  P4.0 high, 0x41:0x42 untouched. Page, list state, save timer, all other RAM, XDATA, SP and
  the screen match stock.
- **Sweep.** All 256 NEC commands through `read_key` and `dispatch_key` on the INPUT page
  with the cursor on each row (from USB and from Bluetooth), on the home, volume, menu and
  OUTPUT pages and in standby; and all 256 key codes through `dispatch_key` on the INPUT
  page, for keys that do not come from the remote. What does not reach `input_menu_select`
  is identical to stock, clock for clock. What reaches it (NEC 0x04, key code 0x0F) differs
  only as above.
- **Full firmware.** Boot from reset on `Amp` with the real timer ISRs, the I2C slave model,
  an EEPROM model, and a signal on every input.
  - Stock, USB to AUX and AUX to USB through the menu: P4.0 low at the key and high 3 to
    4 s later, then the P2.1 reset, the expander reset and the clock generator table; P2.2
    low until after P4.0 is back; P0_4 left low.
  - Patch, all 30 input pairs through the menu: P4.0 and P2.1 never change, no expander
    reset, no clock generator write, P0_4 stays high, the amp plays again within 3.5 s
    (stock: 4.2 to 5.8 s). Pins, NJW1194 words and I2C registers end as in the stock run of
    the same pair, apart from P0_4 and the DAC on AUX. The home screen afterwards is
    stock's.
  - Source key, Vol+, and an Output change in the menu: identical to stock, clock for clock.
- **Integration** (`--in <feature>`). On that image alone: four pairs and the current input
  chosen again (no P4.0 or P2.1 change, no chip re-setup, P0_4 high, playing within 3.5 s,
  home page afterwards), and the six pairs the Source key can do: after the menu's Enter the
  amp sees the same audio events, I2C writes, pin changes and end state as after the Source
  key.
