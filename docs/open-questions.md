# Open questions

Things still worth investigating to complete the picture of what the MCU code can do.
`docs/probing-plan.md` has the plan for finding out on the amp: a read-only probe build
first (`features/probe`; pr1 flashed on 2026-10-05, no dump captured yet), single writes after it.

- **HDMI auto-switch feasibility.** The ARC receiver's signal-present line reaches the
  MCU through expander pin 0x1C and is already polled for the status display. The first
  probe dumps of 2026-10-05 read it high on Optical and on HDMI with the TV in standby
  and on, while the screen said "Digital Input" throughout, with a brief "Disconnected" as
  the TV woke: the line is the ARC link, which the TV keeps up in standby, not audio
  activity. An auto-switch on it would switch to HDMI whenever the TV is plugged in. An
  activity signal exists: with HDMI selected, the receiver's register 0x7D read 0x00 with
  the TV in standby, 0x10 with the TV on and muted, 0x50 with ARC audio arriving, and
  nothing else in the dump moved; and on Optical it read 0x00 with the TV muted and 0x60
  with the TV playing; but by the PCM9211 datasheet 0x7D samples the pin levels of its AUX
  output port, toggling clock and data lines, and the seventh dump read the bit 0 with ARC
  playing: those matches were chance, and no ARC activity indicator exists on Optical
  (`docs/bus-map.md`, "Hardware read-back"). What does exist: the HDMI receiver's S/PDIF
  output is wired to the receiver's RXIN3, and on USB and AUX the firmware parks the DIR
  there, so register 0x39 reports lock and rate when ARC audio arrives, with no write. An
  auto-switch from USB or AUX is therefore a read-only poll. Better, and settled by probe
  pr3 on 2026-10-05 (`docs/bus-map.md`, "Layer 3, item 1"): the receiver's sample-rate
  calculator, pointed at the HDMI receiver's I2S port with one register write outside the
  audio path, reports 44.1 kHz from Optical whenever the TV is awake (muted or playing) and
  no result when the TV is in standby. "TV on" is readable from any input; an auto-switch to
  HDMI can poll it every tick at under 1 ms of main-loop time, with the target restored
  before stock's own read of the result register on Bluetooth, and left alone on HDMI.
  Built as `features/auto-switch` stage 1 (the HDMI activation, a 1 s hold-off, no switch
  away from a playing input); the TV wake confirmed on the amp on 2026-10-05. Bluetooth
  stays out: its module is off on the other inputs, and keeping it on would let phones
  reconnect on their own.
- **Pin roles on the board.** `docs/bus-map.md` lists every expander and MCU pin the
  firmware drives or reads, with roles inferred from when they change. Matching them to
  the silkscreen nets (MUTE_AMP, MUTE_PRE, MUTE_HP, DIR_RST, DAC_MCK_SEL, relays) needs a
  board photo or a meter. Still needed before touching power sequencing.
- **Clock generator.** The chip at I2C 0xC0 (Si5351 register layout): which part, which
  crystal, and what its output clocks. Its status register read 0x71 on the amp: by the
  Si5351 datasheet, crystal present and PLL A unlocked. Either the part reports status
  differently or the output it is programmed for is not what runs the audio.
- **DAC bits stock never sets.** Register 0x090000 bit 0 and bit 1, the PCM volume
  registers 0x090001/0x090002 and the path controls 0x090003/0x090004: check each against
  the CS43131 datasheet before a patch uses it (digital volume, de-emphasis).
- **PCM9211 confirmation.** Verify the receiver identity (register 0x38/0x39 semantics
  match the datasheet) and whether the ARC receiver's output also passes through it.
- **HDMI ARC receiver part number.** Still unreadable in photos; a close-up of the QFP-48
  next to the HDMI socket would settle it and its status-pin behaviour.
- **Backlight drive.** What P0.6 connects to (transistor, resistor, or driver enable).
  Determines whether software PWM dimming is viable; listen for audio buzz in any test.
- **UART1 message values.** A message is two bytes and a 0xFF terminator: format class,
  then rate index 1..12 (`uart1_isr`, `xmos_format_take` 0x408B). The meaning of each class
  and index is in the jump tables after 0x408B and still to be tabulated.
- **Key handlers, resolved in the emulator.** 0x1047 (key 0x1C, NEC 0x09) is the mute
  toggle (it goes home first; it runs on page 1 only: in a menu `dispatch_key` turns the key
  into "home" at 0x0C23, and on the volume page `read_key` does at 0x3DD6, so there the key
  closes the page without muting; house-numerals hn14 changes both, see its README), 0x10BE (key 0x14, NEC 0x08) toggles Dimmer, 0x106D (key 0x0A, NEC 0x0E) is "BT
  Reconnect", 0x10E1 (four-press combo 0x38) is "BT list clear", 0x0F62 (key 0x59) steps
  the EQ. None is a hidden service function.
- **Pop on an input change through the menu.** Heard on the amp on 2026-10-02 (the `d39d321c…`
  build; stock code). `input_menu_select` (0x588B), unlike the Source key, mutes by register only, sets
  P4.0 low for 3 s and then runs `expander_init` and `audio_chips_init` again (main loop,
  0x3375, countdown 0x41:0x42). The speaker mute pin P2.2 stays low until the very end of
  that, and on the digital inputs the format poll opens the NJW1194 and the DAC again about
  0.5 s after Enter, so the supply returns and the chips are reset with the path open. What
  P4.0 powers, which of these moments is the pop, and why SMSL cycles the supply here are not
  known. The path also leaves expander P0_4 (inferred: the Bluetooth module's clear-pairings
  line) low afterwards; whether that matters on the amp is untested (`docs/bus-map.md`).
  `features/fix-menu-input` takes the whole cycle out; if an input ever needs it, that is where
  it will show.
- **Pop at power-off.** A small pop on the Power key, heard on the amp on 2026-10-02 (hn16), the
  same at volume 0 and with the mute key on; the mute key itself is silent. With mute on, the
  only pins power-off moves are the supply enables: P4.4 low, then P0.0 and P4.0 low 100 ms
  later; P2.7 stays low, so the speakers stay connected. So the pop comes with the supplies
  going. Whether stock pops too is not known. One difference from stock: fast-lcd's quick
  clear shortens the time from the amp mute (P2.2) to P4.4 low from 150 ms to 11 ms, which
  cannot be the whole cause, since the pop is there when the amp was muted long before.
  Tried on the amp the same day: with Output on Headphones (P2.7, P2.5 and P2.2 high) the
  speakers pop at power-off just the same, and the switch to Headphones itself is silent. So
  P2.7 does not take the speakers off the amplifier, and no pin the MCU drives is known to.
  What is left is the order and spacing of the supply enables, which should not be changed
  before the supplies are identified on the board. A build that holds P0.0 and P4.0 for 2 s
  after P4.4 would at least tell which step pops; the amp is in that state for 5 s at every
  power-on (`docs/bus-map.md` has the order).
- **Which part makes the volume-key pop.** On Optical or Coaxial without lock, stock's first
  volume key sets P2.7 and P2.2 and opens the NJW1194 for a tick (`features/fix-volume-pop`
  removes all three). Which of them is audible is not known; it would tell P2.7's and
  P2.2's roles apart. A test build that does one at a time would answer it.
- **Volume key during the unmute countdown.** On Optical and Coaxial with lock, every volume
  key runs `unmute_now` (0x5A5E) first. Pressed while the unmute countdown 0x43:0x44 still
  runs (the last 2 s of a power-on, the 1 s after a stream locks), it unmutes at once, up to
  1.9 s early in the emulator, right after the DAC setup. On USB, Bluetooth and AUX the key
  only writes the volume and the mute holds. Stock behaviour, not reported as audible, and
  not changed by fix-volume-pop.
- **A key lost to the settings save (stock race).** Found in the emulator on 2026-10-02, not
  yet looked for on the amp. `settings_save_eeprom` (0x492B) starts with `lcall ir_cmd_clear`
  (0x5DA1: `g_ir_cmd` 0x6A = 0) and leaves the new-command bit 0x20.4 alone. It runs from the
  main loop (0x3446) when the save countdown 0x37:0x38 runs out, 50 main ticks after a setting
  change such as a volume step. A command whose last bit `nec_decode` takes in that one
  main-loop pass, after `read_key` tested 0x20.4 (0x3DA4) and before the clear, keeps its bit
  and loses its code: the next pass looks up command 0, which is 0xFF in the table at 0x9398.
  On the volume page `read_key` turns that into key 0x15 at 0x3DD6, so the page closes and the
  volume does not step; on the other pages 0xFF is no key and the press does nothing (read from
  the listing, not run). Shown with whole NEC frames sent through the INT0 handler, on the
  stock image as on hn16. On hn16 a second Vol+ whose last edge comes 0 to 760 clocks into the
  save's tick goes home; 20 clocks before the tick or 800 into it, the volume steps (stock: the
  same at 100-clock steps). Nothing in the decoder's state guards it (`g_ir_state`,
  `g_ir_repeat_cnt`, the release timer 0x34), so `Amp.press`, which sets only 0x6A and the bit,
  shows the same thing. The window is the part of that pass before the save: 32 us when the
  pass is otherwise idle, and 2.9 ms when the 100 ms format poll (inputs 1..5, I2C) falls on
  the same tick, as it does on fast-lcd for a Vol+ 9.0 s after Power. The save comes 0.67 s
  after the Vol+ on stock (the volume page's draw swallows ticks), 0.52 s on fast-lcd and 0.50
  s on hn16. So on the amp it takes a second key about that long after the first, timed to
  within 32 us, or 3 ms on a format-poll tick: rare, and it would look like a remote glitch.
  Not known: why stock clears the command there, whether it has ever happened on the amp, and
  what the erase itself costs. STC's IAP is believed to hold the CPU while it erases and writes
  (milliseconds for a sector erase; not checked against the STC8G manual, and `Amp` does it in
  no time), and `eeprom_write` masks interrupts per byte, so a frame under way then may lose
  edges and be dropped by the decoder. A fix would replace the call at 0x492B with one that
  keeps a pending command.
- **Power-on sequence timing.** The delays in `post_power_on` (0x5585), `audio_chips_init`
  (0x50D1), 0x24D6 and 0x5D66 govern switching speed and the click that SMSL fixed once;
  worth tabulating if faster switching is wanted. (0x5AAB, named here before, has no delay:
  it only rewrites EEPROM sector 0.)
- **Input-name flicker root cause.** See `features/status-line-flicker/NOTES.md`: the code never writes the
  big line during status refreshes, so the transient is at the panel/interface level.
  Candidates: chip-select toggled per byte on the 8-bit bus, or writes landing during
  the panel's own refresh. A logic analyser on P0/P1, or test builds that change the
  byte strobe sequence, would settle it. The redraw-skip workaround sidesteps it.
- **XRAM size.** 2 KB assumed from the part name; confirm before placing buffers above
  0x0400.
- **Audio level metering.** The MCU sees no audio level today. The stock firmware never
  touches the ADC registers (ADC_CONTR 0xBC, ADC_RES/ADC_RESL 0xBD/0xBE, ADCCFG 0xDE),
  and no chip on the audio path reports one: the NJW1194 bus is write-only, the CS43131
  and PCM9211 are only configured or read for ID / sample rate, the MA5332MS has no
  interface, and the XMOS messages carry format only. The one level-like input is the
  binary signal presence per input (0x5232). A meter would need a hardware tap (rectifier
  + RC envelope from an analogue node such as the NJW1194 output) into a spare MCU pin.
  Open: whether the STC8C2K64S2 has an ADC at all (datasheet), and which pins are free
  (see the expander pin map).
