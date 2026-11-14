# Fix: volume keys without a signal leave the audio hardware alone

On Optical or Coaxial with nothing playing, the first volume key pops. This fix makes a
volume key in that state change only the number and the display. The standalone image is
stock plus the fix; the RESET page shows `v1.4 tbenr vp1`.

## Status

On the amp inside the theme images since 2026-10-02 (first in a house-numerals branch build,
sha256 `d39d321c…`): the pop on the first volume key on Optical without a signal is gone. The
standalone image has not been flashed. See `docs/status.md`.

The pop itself was confirmed on the amp the same day, on stock code:

- Source to Optical with nothing connected, then a volume key: the first key pops, later
  keys do not.
- Rolling the source round and back to Optical arms it again.
- Optical, a volume key (pop), Source to Coaxial, a volume key: no pop. The emulator
  predicted that one, because the pins are still where the first key left them.

## What stock does

- Without lock on Optical or Coaxial (receiver lock pin P4.2 high), Timer0 keeps the
  re-mute request 0x21.4 up (`t0_remute_no_lock`, 0x3E92) and the main loop mutes by
  register: NJW1194 mute code, DAC register 0x090003 = 0xA3. The mute pins are not
  touched. After playing, or after Source reached the input from one that was playing,
  P2.2, P2.5 and P2.7 are still in the playing state.
- All four volume handlers (`key_volume_up` 0x0D03, `key_volume_up2` 0x0D83,
  `key_volume_down4` 0x0E2A, `key_volume_down` 0x0ED2) start with the same head. On input 2
  or 3 it is, at 0x0D0F in the first:

  ```
  0D0F: jb 0x22.1, 0x0D22     ; mute key on -> unmute_now
  0D12: jb P4.2, 0x0D17       ; no lock -> the pins
  0D15: sjmp 0x0D22           ; lock -> unmute_now
  0D17: clr P2.5 / setb P2.7 / setb P2.2
  0D1D: sjmp 0x0D25
  0D22: lcall unmute_now      ; 0x5A5E: clr 0x22.1, pins by output, NJW1194 volume, DAC unmute
  ```

- The shared tail (`vol_key_tail`, 0x0F48) then writes the new volume to the NJW1194
  (`lcall volume_apply` at 0x0F4A). Without lock the main loop mutes it again one tick
  later, so the chip is open for up to 10 ms with the DAC muted.

So without lock the first volume key moves pins: on speakers P2.7 and P2.2 go high, on
headphones P2.5 goes low. Later keys find them there. Any input that unmutes puts them
back, which arms the next first key. With the mute key on, the head takes `unmute_now`
instead: P2.2 goes low and the DAC is unmuted for a tick, with no signal.

Which of the three makes the sound is not known: P2.2 (speaker amplifier mute), P2.7
(speaker/headphone switch), or the NJW1194 opening for a tick while the amplifier's mute
has not acted yet. Roles of the pins are inferred (`docs/bus-map.md`). The fix removes all
three.

## The patch

Two parts, 24 bytes of new code.

**The four heads**, patched in place (7 bytes each, the same bytes in all four):

```
0D0F: jnb P4.2, 0x0D22      ; lock -> unmute_now, as stock with or without the mute key
0D12: clr 0x22.1            ; no lock: a volume key still ends the mute key's mute
0D14: sjmp 0x0D25           ; past unmute_now
```

The nine bytes after it (the rest of the old branch and the pin writes) are no longer
reached and stay as they are.

**The tail's volume write**: `lcall volume_apply` (0x0F4A) becomes `lcall vp_apply`.

```
vp_apply:    mov A,0x47 ; add A,#0xFE ; jz vp_digital ; dec A ; jnz vp_go
vp_digital:  jnb P4.2,vp_go
             setb 0x21.4 ; mov 0x43,#0x00 ; mov 0x44,#0x64 ; ret
vp_go:       ljmp 0x4DDC                  ; volume_apply, returns to the tail
```

- On Optical and Coaxial without lock the volume is not written; the NJW1194 keeps its
  mute code. The number changes in RAM and on the screen as stock, and the settings save
  is armed as stock.
- The unmute that follows the signal writes the volume from RAM, as it always did
  (`audio_apply_mute`, 0x58EB). Nothing is lost by skipping the write.
- The skip also raises the re-mute request with its 100-tick countdown, which is what
  Timer0 does when it sees no lock. The head, the tail and Timer0 each sample P4.2 on
  their own. If only the tail saw it high, the volume would otherwise stay unwritten
  until the next key. With the request up, the main loop mutes and the unmute writes it.
- With lock, and on the other four inputs, the keys do exactly what stock does.
- It uses A and the carry, which `volume_apply` sets itself, and no new variables.

## What it does not change

A volume key pressed with lock while the unmute countdown still runs (after power-on,
after the stream starts) ends the mute early, through `unmute_now`. That is stock
behaviour, seen in the emulator, and not reported as audible. It is listed in the main
`docs/open-questions.md`.

## Including it in another build

`fix_volume_pop.py` holds the fix on its own (`HOOK`, `PATCHES`, `emit(a)`, `XDATA = []`);
`build_patch.py` here is only its standalone image. A build lists it in `INCLUDES` (`docs/development.md`,
"Feature graph"), as house-numerals does since hn16. `tools/build.py` checks that the hook
is installed and the four patches applied, and `run_tests.py` runs "fix-volume-pop in <that
image>": this test's `integration()` on the including image.

## Tests (`emu_test.py`)

- **Image diff.** Only the four heads (six bytes each differ), 0x0F4B, 0x0F4C and the
  version pointer change. The code sits at 0x96D6, a slot no other feature uses.
- **Handlers.** Each of the four handlers run from its entry, with `unmute_now` and
  `volume_apply` recorded instead of run, for every input, lock, mute flag, output and
  page (384 cases against stock). On Optical and Coaxial without lock: no call, P2 as it
  was, the mute flag cleared, the re-mute request and countdown armed; volume, page,
  timers and screen as stock. Everywhere else: stock in every byte of RAM, XDATA, P2 and
  the screen. The same run shows what stock does there (the pins, or `unmute_now`).
- **IR sweep.** All 256 NEC commands through `read_key` and `dispatch_key` against stock:
  USB, Optical and Coaxial, with and without lock, mute key on and off, on the home and
  volume pages, plus standby and two menu pages. Only a volume key without lock differs,
  and only as above.
- **Full firmware, stock and patch.** Both boot from reset on `Amp` with the real timer
  ISRs, the I2C slave model and an EEPROM model, so a cold power-up turns the amp on by
  itself.
  - Source to Optical or Coaxial with nothing connected, on speakers and on headphones.
    Stock: the first Vol+ sets P2.7 and P2.2 (P2.5 low on headphones) and sends the
    NJW1194 the volume. Patch: four keys change no pin, the NJW1194 only gets its mute
    code and the DAC its mute value; the page shows the new number. Then the signal
    arrives: both unmute at the new volume, with the same chip state, pins and screen.
  - The signal drops while playing on Optical, then two Vol-: nothing on the patch.
  - Mute key on without a signal, then Vol+: the flag clears, the hardware stays muted;
    the signal then unmutes at the new volume. Stock releases P2.2 and unmutes the DAC.
  - Lock low at the key's head and high at its tail: the new volume still reaches the
    NJW1194. This fails without the re-mute request in `vp_apply`.
  - USB, Optical and Coaxial with lock, Bluetooth and AUX, on both outputs, through
    Vol+, Vol+, Vol-, mute, Vol+: the same audio events as stock in the same order, each
    within two main ticks, and the same I2C writes, volume, EEPROM and screen.
- **Integration** (`--in <feature>`). On that image alone: Optical on speakers and Coaxial
  on headphones without a signal, the signal drop on both outputs, and the mute key case.
