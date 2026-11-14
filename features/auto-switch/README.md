# auto-switch, stage 1: to HDMI when the TV comes on

The first stage of the auto-switch from `docs/probing-plan.md`, on what the probe dumps of
2026-10-05 settled. Built, emulator-verified and flashed on 2026-10-05. The TV wake works on
the amp: from Optical with nothing playing, the amp went to HDMI about a second after the TV
came out of standby (user confirmed, 2026-10-05, as1). as2 enables HDMI only: the amp is not
discoverable while another input is selected (the firmware holds the module's enable,
expander P0_0, low off the Bluetooth input; `docs/bus-map.md`), and keeping the module on so
that phones could connect from any input is not wanted, since devices would reconnect on
their own. That stays an option for the stage 3 menu, off by default. as3 (2026-10-16) is as2
rebuilt on direct-select v3 (the idempotent power commands 0x16/0x17), and as4 (2026-11-14)
as3 on direct-select v4 (an input command in standby powers on, on that input); nothing else
changed, neither is flashed.

## What it does

With the amp on and showing the home screen, from any input:

- **The TV comes on**: the amp switches to HDMI. "Comes on" is the TV's ARC stream starting,
  which the TV does when it wakes, muted or not; a TV that is already on when the amp powers
  up does not count, nor does unmuting.
- **A phone connects over Bluetooth** would switch the amp to Bluetooth if Bluetooth were in
  `ENABLED`; it is not (see above). The module's connection line is still read, for the
  "is Bluetooth playing" check when Bluetooth is the selected input.

A switch happens only after the source has been seen on for one second (`HOLD`, ten
readings 100 ms apart), only when the source is not the selected input, and only when the
selected input is silent: no lock on Optical or Coaxial, no USB activity, no phone on
Bluetooth, no stream on HDMI, always on AUX. An activation that finds the selected input
playing is dropped; so is one that arrives while a menu is open. There is no switching back
when a source goes quiet. The switch itself is direct-select's: the input, the OSD timer,
then stock's input_apply, so it looks and sounds like a Source press.

`ENABLED` in `auto_switch.py` lists the sources that may trigger a switch (HDMI by default),
`HOLD` the hold-off. Stage 3 moves these into a menu and the EEPROM.

## Supported combinations

An activation is a source starting; the amp switches to it only while the selected input is
silent. Rows are the source that starts, columns what the switch needs from the selected
input. "Stage" refers to `docs/probing-plan.md`.

| Source that starts | Sensed how | Switch from USB | from Optical | from Coaxial | from Bluetooth | from HDMI | from AUX | Status |
|---|---|---|---|---|---|---|---|---|
| HDMI (TV wakes) | rate calculator on the HDMI I2S port | yes | yes | yes | yes | n/a | yes | **stage 1, built**; confirmed on the amp from Optical, the others emulator-only |
| Bluetooth (phone connects) | module connection line, expander P0_5 | sensed | sensed | sensed | n/a | sensed | sensed | sensed, **disabled**: the module is off unless Bluetooth is selected, so nothing can connect; a stage 3 option could keep it on |
| USB (host starts playing) | rate calculator on the XMOS I2S port, untested | n/a | possible | possible | possible | possible | possible | not built; the USB dumps are deferred |
| Optical (stream starts) | the S/PDIF receiver moved onto it, lock read | possible | n/a | only while Coaxial is silent | only while Bluetooth is silent | possible | possible | stage 2, not built |
| Coaxial (stream starts) | the same | possible | only while Optical is silent | n/a | only while Bluetooth is silent | possible | possible | stage 2, not built |
| AUX (analogue) | nothing to sense | no | no | no | no | no | no | not possible |

"Silent" for the selected input: USB, no activity on P4.5; Optical and Coaxial, no lock on
P4.2; Bluetooth, no phone on P0_5; HDMI, no rate on the receiver's main port, i.e. the TV
off; AUX, always. An activation that finds the selected input playing is dropped, and so is
one that arrives while a menu is open; the amp never switches back on its own when a source
goes quiet.

## How it senses

- **HDMI**: the receiver's sample-rate calculator (PCM9211 register 0x37 selects the port,
  0x38 holds the result), pointed at the HDMI receiver's I2S input. A rate code of 44.1, 48,
  88.2, 96, 176.4 or 192 kHz with the "calculating" bit clear means the TV is awake; the
  idle codes the calculator returns on a port without a stream, which wander, do not. On
  HDMI itself stock points the calculator at the main port, which carries the same stream,
  so nothing is written there.
- **Bluetooth**: the module's connection line, expander input P0_5.

Once per 10 ms tick, after stock's signal monitor, paced on stock's format-poll countdown
(10 ticks; AUX, where it does not run, keeps its own): at 9 the target is set to the HDMI
port, at 5 the expander is read, at 2 the result is read and the target put back on the
DIR, then the evaluation runs. Stock reads the result register itself only on Bluetooth, at
countdown 0, to hold its mute while the module has no stream; the restore at 2 keeps that
read on the DIR. Cost: three bus transfers per 100 ms, about 1 ms of main-loop time.

The only register written is the calculator target, a measurement block outside the audio
path, with the values 2 and 0.

## Hook and state

read_key is untouched. The hook is main_tick_tasks' `lcall signal_monitor` (0x3438), on the
tick path only; `as_tick` calls the monitor first. State is seven bytes of XDATA at
0x01D0..0x01D6 (phase for AUX, the two raw readings, two hold counters, the active bits, the
armed counter), outside house-numerals' range, so the fix can be included there if space
allows (about 210 bytes of code plus the rate table).

## Tests (`emu_test.py`)

- the image differs from stock only in the hooks, the fixes' patches and the version pointer;
- the tick hook on the bare CPU, every input and countdown phase: exactly the intended
  transfers, nothing on HDMI but the read, nothing in standby, the signal monitor called;
- all 256 commands through read_key and dispatch_key against stock plus the same fixes:
  identical, the feature is not in the key path;
- whole firmware on the EEPROM and I2C models, with the TV, the phone and the lock pins
  driven by the test: the switch to HDMI from a silent Optical one hold-off after the TV
  comes on, with the same audio events as direct-select's HDMI command; none while Optical
  plays; from Bluetooth, with every stock read of the result register on the DIR; the switch
  to Bluetooth when a phone connects and none when it leaves; no switch for a TV already on
  at power-on; none in a menu; from HDMI with the TV off to Bluetooth; nothing in standby.

`--in <feature>` runs the hook test and the main scenarios on any image that includes it.

## On the amp

Flash `build/flash_autoswitch.bin` (sha in `KNOWN_IMAGES`). The dump facility of the probe is
not in this image. Try: Optical selected with nothing playing, TV in standby; wake the TV; the
amp should go to HDMI about a second after the TV's ARC link comes up. Then, from Optical
with nothing playing, connect a phone.
