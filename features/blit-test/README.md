# Tuned blit test

A test build that checks the faster pixel loop from `features/ui-theme`
("Tuned blit") on the real panel, and measures it. It is built on top of
direct-select, so the six input codes keep working. The RESET page shows
`v1.4 tbenr blit`.

| Remote button | Or NEC command (address 0x12 0x34) | Does |
|---|---|---|
| Vol+ (NEC 0x0A) | 0x16 | 10 full-screen fills with the tuned loop, then colour bars through the same loop |
| Vol− (NEC 0x0B) | 0x17 | 10 full-screen fills with the stock clear routine 0x51EE, then colour bars through the stock pixel routine 0x5C7C |

The tests run only when the amp is on and showing the home screen. Everywhere else
(standby, menus, the volume page, the 5 s hold after a test), Vol+ and Vol− keep their
stock function, and 0x16/0x17 are ignored. On the home screen the remote no longer
changes the volume; the front knob still does. Press briefly: holding the button sends
repeat codes, which land on the hold page and change the volume there.

Each run ends on 8 vertical bars, 40 px wide. From left to right they are red, green,
blue, white, yellow, cyan, magenta and grey. Over the bars, a three-digit number shows
the 10 ms ticks the 10 fills took, which is the same as **milliseconds per full-screen
fill**. After 5 s the stock return-home timer redraws the home screen.

| | Emulator (STC8 clock table) | On the amp |
|---|---|---|
| Vol+ / 0x16, tuned | 6.4 clocks/px, 14.5 ms/fill, shows `014` (`015` with the real ISR running) | in line (2026-09-28) |
| Vol− / 0x17, stock | 65 clocks/px, 147 ms/fill, shows `147` | in line (2026-09-28) |

## What to look for

- Both runs should show the same bars. Look for wrong colours, a colour change partway
  down a bar, missing or shifted columns, or a torn edge between bars. A dropped byte
  swaps the high and low bytes of the rest of a bar: red turns dark blue, green turns
  pink. If this happens, the next build adds a NOP to stretch WR.
- The number shows the speed. If the amp shows about 14 and 147, the STC8 timing table
  and the emulator match the chip.

## Files

- `build_patch.py` builds `build/flash_blittest.bin` from
  `features/direct-select/build/flash_patched.bin` and writes the listing `blit_test.asm`.
- `emu_test.py` runs the hook in the full emulator (`tools/emu/emu8051.py`). The
  emulator follows the STC8 clock table and decodes the LCD bus into an ST7789 model.
  The test checks the bars, the digits, the hold, the ignored states, and that all
  other commands, in standby, on home, on the volume page and in a menu,
  behave exactly as in direct-select. It writes
  `build/emu_tuned.png` and `build/emu_stock.png`.

## Mechanism

- Two direct-select branches are repointed. At 0x9405, `jc not_select` (cmd < 0x10) now
  goes to a check for Vol+/Vol− on the home screen. At 0x940A, `jnc not_select`
  (cmd − 0x10 ≥ 6) now goes to the 0x16/0x17 dispatcher at 0x9450. Everything else
  continues to 0x942A as before.
- The stopwatch is RAM 0x3F:0x40. This is the return-home countdown that the Timer0 ISR
  decrements every 10 ms (0x3ED9). The test loads it with 0xFFFF, reads it after the
  fills, and then loads 500 ticks with the page set to 0. When the countdown ends, the
  ISR sets page 1 and the redraw flag. This is the same way the volume page returns home.
- Why page 0: the first build used page 2 (the volume page). On the amp the bars were gone
  within a frame, because `read_key` has a tail at 0x3DD6 that turns any key other than
  Vol±/Power on page 2 into 0x15 ("go home"), and that includes the "no key" the test
  returns. Page 0 is never used after boot. The renderer draws nothing for it, and the
  tail leaves it alone. The hook-only emulator test could not see this, so `emu_test.py`
  now also boots the whole firmware and runs the main loop with the real Timer0 ISR. The
  old build fails that scenario, and the fixed one holds the bars for 5.00 s.
- The digits come from the stock big-digit painter 0x4384 in the theme colour
  (RAM 0x48:0x49), at the volume-page position 130,75.
- Side effects while the test runs: the main loop is blocked for about 0.2 s (tuned)
  or 1.6 s (stock). During the 5 s hold, the volume keys act as they do on the volume
  page.

## Bus timing

The panel is an ST7789-class controller on an 8-bit 8080 bus: data on P1, WR on P0.5
(latched on the rising edge), CS on P0.7, D/C on P0.3. The stock byte routine 0x567A
toggles CS and calls a delay (0x001E) for every byte. The tuned loop sets D/C and CS once
per block and then writes only P1 and a WR pulse. At 24 MHz one clock is 41.7 ns, and
`mov P1` / `clr WR` / `setb WR` takes 3 clocks (STC8 table: bit operations and MOVs are
1 clock).

| 8080 write parameter | ST7789 minimum | Tuned loop |
|---|---|---|
| Write cycle | 66 ns | 125 ns |
| WR low | 15 ns | 42 ns |
| WR high | 15 ns | ≥ 42 ns |
| Data setup before WR rises | 10 ns | ≥ 83 ns |
| Data hold after WR rises | 10 ns | ≥ 42 ns |

| Path | Clocks/px | Full screen |
|---|---|---|
| Stock, two 0x567A calls per pixel (loop at 0x5180) | ≈67 | 147 ms (measured) |
| Fill, unrolled ×8 | 6.4 | ≈15 ms (measured) |
| Same-byte fill (black, white) | 4.4 | ≈10 ms |
| 1-bit glyph expand | ≈15 | ≈34 ms |

On paper every parameter has at least twice the margin, and on the amp neither path
dropped or shifted a byte. So the stock per-byte delay is not needed on this board. If
a later panel ever shows errors, add a NOP between `clr` and `setb` (+42 ns).

To go back to plain direct-select, flash `features/direct-select/build/flash_patched.bin`.
