# Fast LCD

The stock UI, unchanged, drawn through the tuned pixel path that the blit-test build
verified on the panel (see Bus timing). Built on top of direct-select. The RESET page shows
`v1.4 tbenr fast2` (fast2 is the same layer rebuilt on direct-select v2, 2026-09-30).

## Status

fast2: emulator-verified, and on the amp inside hn11 since 2026-09-30; not flashed standalone. fast (`v1.4 tbenr fast`, on direct-select v1) was
flashed on the amp on 2026-09-28 and working so far. Longer listening tests are still to
come: power-on, input switching and the display flicker.

## What changes

| Stock routine | Stock | Now |
|---|---|---|
| `lcd_write_pixel` 0x5C7C (every glyph, icon, rectangle) | two calls of `lcd_write_data` 0x567A, each with its own CS pulse and a delay call, about 55 clocks | both bytes inline under one CS pulse, 13 clocks plus the call |
| `lcd_clear_black` 0x51EE (every page change) | 54400 pixel calls, about 147 ms | same window setup, then a same-byte black fill, about 10 ms |

Everything else goes through the stock byte routines as before, delay included:
commands, windows, and the LCD init sequence. Both replacements leave every register
as the stock routines do, and the tests check this.

Two 3-byte hooks: `ljmp` at 0x5C7C and at 0x5202 (the clear's loop, after its window
setup). 108 bytes of code at 0x9700 (placed after the old blit-test's area,
0x9450..0x9632).

## Emulator results

`emu_test.py` runs the direct-select image and this one side by side in lockstep. Both
run the whole firmware from reset, with the real Timer0 ISR and USB carrying a signal.
The tour: Power, Source, Vol+ and back home, Menu, Down, Down, Up, menu timeout,
direct-select HDMI, direct-select USB, Vol− twice, Power off.

| Step | Stock drawing | Fast drawing |
|---|---|---|
| Source (input name) | 90 ms | 60 ms |
| Vol+ (volume page, full clear) | 190 ms | 40 ms |
| Vol− (volume page) | 190 ms | 40 ms |
| direct-select HDMI / USB | 90 / 100 ms | 70 / 70 ms |
| Power off | 160 ms | 20 ms |

These numbers run from the key press until 100 ms pass with no LCD writes. They
include the firmware's own work before it starts drawing.

What the test checks:
- after every step, once both screens are idle, they are pixel-identical, and the page
  and power state agree;
- the audio state goes through the same sequence in both images, in the same order,
  and never reaches a state later than stock. The state is the last value written to
  each NJW1194, DAC and expander register, plus the input, mute and mux pins, recorded
  after every write that changes it. Each audio writer also receives exactly the same
  set of arguments in both images;
- the unmute path runs.

## Risks

- **Panel bus timing: low.** The pixel path uses the 3-clock byte writes that
  blit-test proved on the panel (see Bus timing). Commands and the LCD init are unchanged.
- **Code that relied on slow drawing: checked.** On an input switch the stock firmware
  mutes the NJW1194 and switches the input before it draws, at 0 ms and 5.3 ms in both
  images. It then repeats the mute every tick until its tick-based timer releases it.
  With fast drawing those repeats start earlier (60 ms instead of 83 ms), but they
  rewrite the same values, so the audio chips see no extra state.
- **Main-loop timers: closer to nominal.** Several firmware countdowns (0x23:0x24,
  0x27:0x28, 0x2F:0x30, 0x43:0x44) are decremented by the main loop once per 10 ms tick
  flag. That flag is a single bit, so ticks are lost while stock drawing blocks the
  loop. With fast drawing these timers run closer to their nominal length, and the
  steps they pace come earlier. The emulator tour shows the same 186 audio states in the
  same order, none later than stock. The whole power-on chain (relays and mutes,
  DAC setup, input switch, unmute) moves 0.16 s earlier. The rails therefore get 4.99 s
  instead of 5.15 s before the relay burst. One gap shrinks: during power-on, the DAC
  register sequence after the input switch follows it by 0.14 s instead of 0.41 s. On
  the amp, listen for a pop at power-on and when switching inputs, starting at low
  volume.
- **Backlight: earlier, by design.** P0.6 switches on when the power-on screen has
  been drawn, which is now sooner.
- **Display flicker (see `features/status-line-flicker`): unknown.** It is a panel-side
  transient. Redraws are now shorter, which could make it rarer, more frequent, or leave
  it unchanged.
- **Recovery: unchanged.** The bootloader entry, the standby handler and the reset
  vector are untouched.

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

"Measured" means on the amp, with the blit-test build (`features/blit-test`, removed on
2026-09-29, last present at commit c28c4dc). On the home screen, remote Vol+ ran 10
full-screen fills through the tuned loop and Vol− ran 10 through the stock clear 0x51EE.
Each run then drew 8 colour bars through the same path and showed the milliseconds per
fill: 14–15 tuned against 147 stock, as the emulator predicted (2026-09-28). Neither path
dropped or shifted a byte, which would show as a colour change partway down a bar, so the
stock per-byte delay is not needed on this board. If a later panel ever shows errors, add a NOP between `clr` and `setb` (+42 ns).

## Files

- `build_patch.py` builds `build/flash_fastlcd.bin` and the listing `fast_lcd.asm`.
- `emu_test.py` runs the tests above and writes `build/tour_<step>.png`.
