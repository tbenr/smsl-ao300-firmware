// Apply labels for the SMSL AO300 firmware (STC8C2K64S2, 8051).
// Works on the stock image (flash.bin) and on the patched ones; entries for patch
// code are skipped when the image does not reach them.
//
// Keep this file current: whenever a routine, variable or table is identified, add it
// here (see AGENTS.md). Keil stores 16-bit values big-endian: high byte first.
//
// Run inside Ghidra: Window -> Script Manager -> "Manage Script Directories"
// (list icon) -> add the tools/disasm folder -> refresh -> category SMSL -> run.
// @category SMSL

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.ByteDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.SourceType;

public class SmslAo300Labels extends GhidraScript {

    Object[][] codeFuncs = {
        {0x0006, "delay_30"},   {0x000E, "delay_6"},   {0x0016, "delay_30b"},
        {0x001E, "delay_1"},    {0x0BB4, "dispatch_key"},
        {0x0CD2, "key_power_off"},     {0x0CE9, "key_exit_to_home"},
        {0x0D03, "key_volume_up"},     {0x0D83, "key_volume_up2"},    // +2 steps; key codes 0x5A/0x5B (bit 0x40: probably a held key / remote repeat, not confirmed)
        {0x0E2A, "key_volume_down4"},  // -4 steps; key codes 0x5A/0x5B (bit 0x40: probably a held key / remote repeat, not confirmed); 0x0ED2 is the -1 handler
        {0x0ED2, "key_volume_down"},
        {0x0F62, "key_59"},            {0x0F93, "key_source_next"},
        {0x0FC8, "key_source_prev"},   {0x1006, "key_output_toggle"},
        {0x1047, "key_1c"},            // NEC 0x09: goes home (page 1, render), then the mute toggle (0x22.1): NJW1194 mute code, DAC mute, P2.2 high, clr P2.5; reached on pages 1 and 2 only (hooked, features/house-numerals: hn_mute_key shows the volume page instead)
        {0x106D, "key_bt_function"},   // key 0x0A (NEC 0x0E), Bluetooth only: "BT Reconnect" (0x934E), expander pin 0x10 low for 0.3 s
        {0x10BE, "key_toggle_29"},     // key 0x14 (NEC 0x08): Dimmer 1 <-> 2
        {0x10E1, "key_38_combo"},      // bt_list_clear, then home
        {0x10FC, "key_menu_nav"},      // reached by NEC 0x04, which opens the menu (page -> 3) from home
        {0x126F, "key_up"},
        {0x135A, "key_down"},          {0x144E, "key_menu"},          // NEC 0x03 (NEC_MENU in ao300.py); acts only inside a menu, does not open it
        {0x14E3, "key_default"},       {0x2072, "keil_switch_case"},
        {0x202C, "cmp_u32"},           {0x24D6, "input_set_hw"},
        {0x2681, "nec_decode"},        {0x2F46, "settings_load_eeprom"},   // cold boot only (main, 0x53F6): EEPROM 0x0002 -> 0x26 (power-on flag); the record 0x0201..0x020C ->
                                       // 0x31 volume, 0x47 input, 0x2B output, 0x4A, 0x39 EQ, 0x35, 0x2A, 0x4D colour, 0x52 headphone volume, 0x33, 0x29 dimmer, 0x2C filter;
                                       // both volumes only clamped to 0..60 (0x2F56, 0x303A), so stock starts at the last volume (features/start-volume caps it)
        {0x3A53, "small_text_render"}, {0x3DA2, "read_key"},
        {0x3E67, "timer0_isr"},        {0x449F, "main_init"},
        {0x4E2D, "step_with_wrap"},    {0x5040, "timer3_isr"},
        {0x396D, "encoder_scan"},      // timer3_isr (every 0.5 ms): RE_A P5.5 / RE_B P5.4 -> key code, stored in 0x2D (0xFF idle)
        {0x536F, "key_history_combo"}, {0x549F, "int0_isr"},
        {0x55F2, "uart1_isr"},         {0x5628, "input_step"},
        {0x59ED, "uart1_init"},        // SCON 0x50, Timer2 as 1T baud generator (reload 0xFFCC: 115200 at 24 MHz), UART1 on P3.0/P3.1, ES on
        {0x55BC, "standby_power_step"}, // standby loop, after the standby key handler: on power-on clr P0.2, P_SW1 S1_S=01 (UART1 to P3.6/P3.7, the XMOS line), power_on_display; on entering standby setb P0.2, S1_S=00 (UART1 back on the header pins P3.0/P3.1), 0x5B4F
        {0x56E8, "int1_isr"},          {0x588B, "input_menu_select"},
        {0x58AF, "eeprom_write"},
        {0x58D3, "audio_apply_mute"},  // 0x22.4 set: volume_apply(0x31), setb 0x22.5; clear: NJW1194 to the mute code (0x92C5), clr 0x22.5; then DAC reg 9 by 0x22.5 (0x5A0A). 5.2 ms when muting
        {0x5956, "eeprom_read"},       {0x59B2, "standby_key"},
        {0x59D0, "eeprom_erase"},      {0x5A5E, "unmute_now"},        // clr 0x22.1, then falls into mute_state_set with R7 = 1: the volume keys call it while muted
        {0x5AAB, "eeprom_mark_power_on"}, // only this: erase sector 0, 0x0001 = 0x45 (magic), 0x0002 = 1 (power-on flag); standby_key jumps here on Power.
                                       // The power-on work itself is standby_power_step and post_power_on
        {0x5CE8, "iap_idle"},
        {0x5D03, "delay_long"},        {0x5D10, "ir_cmd_to_key"},
        {0x5D42, "ui_clear_screen"},   {0x5D4B, "timer1_isr"},
        {0x5D7D, "reset_timer_37"},    {0x5D8A, "inject_key_08"},
        // UI pages and drawing
        {0x2101, "ui_render_page"},    {0x298B, "big_text_render"},
        {0x2DF8, "small_glyph_paint"}, {0x3F3C, "big_glyph_paint"},
        {0x3F2A, "bignum_digit"},      {0x345C, "glyph_blit_1bpp"},
        {0x42F5, "draw_num_small"},    {0x4384, "draw_num_big"},
        {0x5744, "home_draw_output_icon"}, {0x5916, "home_draw_volume"},
        {0x5936, "volpage_draw_volume"},   {0x5C8B, "home_refresh"},
        {0x5CBC, "ui_clear_small_buf"},    {0x5CCB, "ui_clear_big_buf"},
        {0x4C8F, "big_text_load"},         {0x4D3A, "small_text_load"},
        {0x5119, "lcd_clear_column24"},    {0x49A1, "home_draw_eq_tag"},
        {0x41CA, "home_draw_format_tag"},  {0x4A85, "home_draw_input_name"},
        {0x4F18, "eq_tag_paint"},      // home_draw_eq_tag's only call (0x4A0F): string R3:R2:R1 at 266,10, falls into small_text_at
        {0x4F20, "small_text_at"},     // string R3:R2:R1 (generic pointer) in small glyphs at R4:R5 x, R6:R7 y
        {0x0026, "tag_box_clear"},     // black box from x R4:R5, y R6:R7 (the format tag's, from home_draw_format_tag)
        {0x4B66, "icon_paint"},        // home icon XDATA 6 in colour R2:R3 at R4:R5 x, R6:R7 y
        {0x3881, "eq_show"},           // R7 = EQ: EQ tag, the preset's name (big, y 75) and its text (small, y 135) on page 1
        {0x57C6, "eq_step"},           // key_59 without the refresh flags: next EQ, apply, eq_show
        {0x4BC9, "home_draw_status"},  // the status line for the input (small_text_render, y 135)
        {0x1F7F, "keil_imul"},             {0x2167, "volpage_render"},
        // LCD bus (P1 data, P0.5 WR, P0.7 CS, P0.3 D/C)
        {0x2808, "lcd_init"},          {0x4437, "lcd_set_window"},
        {0x51EE, "lcd_clear_black"},   {0x567A, "lcd_write_data"},
        {0x5A26, "lcd_bus_reset"},     {0x5C7C, "lcd_write_pixel"},
        {0x5C9C, "lcd_write_cmd"},     {0x5CDA, "lcd_bus_low"},
        {0x5D1C, "lcd_bus_idle"},
        // audio chips and I/O
        {0x2302, "expander_read_pin"}, {0x47BA, "expander_init"},
        {0x4D9E, "dac_i2c_write"},     {0x51AD, "expander_write"},
        {0x5232, "signal_present_update"}, {0x54EA, "njw1194_write"},
        {0x4CDF, "i2c_read_reg16"},    // R7 device, R4:R5 register (only R5 is sent), returns R7; 5 tries. Only the expander (0xB0) and the receiver (0x80) are ever read
        {0x4FAD, "i2c_write_reg"},     // R7 device, R4:R5 register (only R5 is sent), R3 data; 5 tries
        {0x4D8A, "dac_write"},         // device 0x62: address bytes R7, R5, R3, then XDATA 3 (control) and XDATA 4 (data); 5 tries (dac_i2c_write is its retry loop)
        {0x5B65, "i2c_start"},         {0x5C08, "i2c_stop"},
        {0x56B9, "i2c_write_byte"},    // R7, MSB first; waits while P4.1 is held low
        {0x5339, "i2c_read_ack"},      // R7 = 1 on ACK (sample at 0x535D), 0 after 255 samples
        {0x5335, "i2c_write_a_ack"},   // i2c_write_byte(A), i2c_read_ack; 0x5334 takes the byte from XDATA @R0, 0x5331 first ands R7 into R2
        {0x579C, "i2c_read_byte"},     // returns R7 (bit sample at 0x57B5); no ACK clock follows
        {0x1A7C, "expander_write_pin"},// R7 pin id (0x10 + port 0 bit, 0x18 + port 1 bit), R5 level; output shadow in XDATA 0x69..
        {0x5089, "clkgen_load"},       // R3:R2:R1 -> 43 entries (16-bit register, value), written to I2C 0xC0 (Si5351 register layout)
        {0x50D1, "audio_chips_init"},  // expander 0x10 low, P4.3 and P2.1 low for 0.1 s, clkgen_load(0x92C6), dir_init, dac_init, input_set_hw, eq_apply, filter_apply, volume_apply
        {0x3B35, "dir_init"},          // PCM9211 (I2C 0x80) setup, 21 writes
        {0x1CE5, "dac_init"},          // P3.4 low for 0.5 s (DAC reset), then the CS43131 setup
        {0x14E4, "dac_hdmi_setup"},    // input 5 only: R7 = format code; DAC PLL registers 0x0300xx
        {0x4ECD, "dac_set_filter"},    // R7 = filter 1..5 -> DAC register 0x090000 = 0x02, 0x42, 0x82, 0xC2, 0xE2
        {0x5BB8, "filter_apply"},      // mute, wait, dac_set_filter
        {0x48B2, "eq_apply"},          // R7 = EQ 1..8 (Direct, Tone, SDB, Bass, Super Bass, Rock, Soft, Clear): tone_write for bass and treble
        {0x4837, "tone_write"},        // R5 = level 0..18 (9 flat), R7 = 0x30 treble / 0x40 bass -> njw1194_write
        {0x5D66, "p43_pulse"},         // P4.3 low for one delay_long; input_set_hw calls it on a switch to USB
        {0x3C14, "bt_list_clear"},     // the RESET page's hold action. Bluetooth: "BT CLEAR......", bt_clear_pulse. Any other input (0x3C2F): "RESETTING......",
                                       // sectors 0 and 0x0200 erased and rewritten with the factory record (volume 20, input 1, ...), then IAP_CONTR = 0x60 (reset).
                                       // "It's not BT!" belongs to bt_clear_or_not_bt (0x568A)
        {0x568A, "bt_clear_or_not_bt"}, // on Bluetooth: bt_clear_pulse, then mute (clr 0x22.4, audio_apply_mute); else the text "It's not BT!" (0x9270). Callers not traced
        {0x5BA4, "bt_clear_pulse"},    // expander pin 0x14 low for about 0.2 s
        {0x5B7A, "expander_outputs_on"},// pin 0x14 high, 0x10 and 0x17 low (power-on)
        {0x408B, "xmos_format_take"},  // buffer valid (0x78 == 0xFF): copy 0x76 -> 0x75 (format class), 0x77 -> 0x73 (rate index 1..12); the only reader of the UART buffer
        {0x5B4F, "standby_enter"},     // lcd_bus_low, P0.0 and P4.0 low, backlight off, mute, P4.4 low
        {0x4DDC, "volume_apply"},      // R7 = volume (0x31): saves it in 0x5B, looks up 0x9289, njw1194_write(R7=0x10); with output 2 (0x2B) it uses g_volume_hp (0x52) instead of R7
        {0x492B, "settings_save_eeprom"}, // erase sector 0x0200, write the 12 bytes 0x0201..0x020C from RAM (see settings_load_eeprom). Called at 0x3446 when the
                                       // countdown 0x37:0x38 (reset_timer_37: 50 main ticks) runs out, so about 0.5 s after a change, and after every power-on (filter_apply arms it)
        {0x5CF6, "clamp_hp_30"},       // R7 = min(R7, 30)
        {0x5275, "output_apply"},      // R7 = output 1 speakers / 2 headphones. On a change (0x5287): save armed, mute, g_volume_hp = clamp_hp_30 (0x5296), volume_apply.
                                       // The only volume cap in stock; nothing caps at power-on
        // menus (pages 3..13). Details in docs/menu-system.md
        {0x2B0D, "menu_list_render"},  // R3:R2:R1 -> list table of 4-byte entries {count, 3-byte string pointer}; R5 = highlighted row; count -> 0x14; rows from y 36, 28 px apart
        {0x46BC, "menu_main_restore"}, // back on the main menu: 0x17 = 0x16, scroll offset 0x19 and row 0x10 recomputed; the item count 10 is an immediate at 0x4723 and 0x472A
        // main loop and timers
        {0x3325, "main_tick_tasks"},   // first, on every pass: 0x21.4 set (re-mute request) -> clear it and 0x22.4, audio_apply_mute
        {0x5585, "post_power_on"},     // run by main_tasks_on when 0x20.3 is set (power-on path 0x55E4); blocks ~1 s, then 0x43:0x44 = 200
                                       // never arms g_screen_off: with Auto OFF the backlight stays on after a cold power-up (fixed in the PRO V1.2; features/fix-auto-off hooks its tail 0x55B9)
        {0x5A62, "mute_state_set"},    // R7=0: clear 0x22.4, P2.2 on; else 0x5B39 by output
        {0x5975, "power_on_display"},  // standby loop's power-on path, after setb 0x20.3: lcd_init, backlight, 0x52B4 (~3 s, probably the logo), expander_init; keys wait
        {0x5B39, "p2_mute_pins_by_output"}, // output 1: P2.5/P2.7/P2.2 low, 2: high
        {0x5A78, "countdown16_dec"},   {0x5B22, "main_tasks_on"},
        {0x5A92, "mute_and_arm_unmute"},    // mute_state_set(0), then 0x43:0x44 = R7 if it is below 20
        {0x5C67, "unmute_countdown_min30"}, // 0x43:0x44 raised to at least 30 ticks
        {0x583F, "bt_hold_mute_poll"},      // BT, from the format poll: reg 0x0038 of I2C device 0x80, low nibble 0 (no stream) keeps 0x43:0x44 >= 50
        {0x4638, "format_poll"},            // every 10 main ticks (0x4B) on inputs 1..5: format_read -> 0x58; if it differs from 0x4E: DAC/filter reconfig, unmute_countdown_min30, 0x23:0x24 = 100, 0x4E = 0x58
        {0x3583, "format_read"},            // R7 = input format code (0xFF: none)
        {0x5463, "signal_monitor"},         // inputs 2/3 or output 2: 0x22.4 from signal_present_update; after a loss, 0x7C:0x7D then clr P2.5
        {0x5A0A, "dac_mute_reg_by_signal"}, // DAC register 9 = 0x01A3 or 0x01A0 by 0x22.5, via 0x4D8A
        {0x5D6E, "dispatch_key_if_any"},
        {0x3FE3, "home_refresh_periodic"},  // main_tick_10ms on page 1 when 0x27:0x28 runs out (10 ticks after a render, then every 50): loads the status line into XDATA 0x50, then 0x4081 home_refresh + small_text_render at y 135
        {0x3CDC, "status_rate_text"},       // R7 = sample-rate code -> XDATA 0x50 ("44.1kHz", "2.8224MHz", ...; else "Connected")
        {0x4F63, "status_bt_text"},         // Bluetooth status line (codec names, "Searching...", "No Connected")
        {0x5B8F, "strlen_generic"},         // R3:R2:R1 generic pointer -> R6:R7 length
        {0x412F, "lcd_fill_rect_slow"},     // rectangle fill through the per-pixel path; the flag path's black x 0..239, y 43..169 takes 125 ms
        {0x5161, "lcd_clear_column32"},     // big_text_render's margins: one 1 x 32 black column at XDATA 0x04:0x05
        // Keil runtime
        {0x1EF5, "keil_cldptr"},       {0x1F91, "keil_ildptr"},
        // patch code, only in the images that carry it
        {0x9400, "ds_select"},         // features/direct-select standalone image; builds that include the fix place it in their own code
        {0x9680, "fx_auto_off"},       // features/fix-auto-off standalone image; builds that include the fix place it in their own code
        {0x96B0, "sv_limit"},          // features/start-volume standalone image (hook 0x5596): g_volume and g_volume_hp capped at the build's limits, then audio_chips_init;
                                       // builds that include the fix place it in their own code (house-numerals hn14: 0xF082)
        {0x9700, "fast_pixel"},        // features/fast-lcd, replaces lcd_write_pixel
        {0x9716, "fast_clear"},        // features/fast-lcd, replaces lcd_clear_black's loop
        // features/house-numerals (hn10)
        {0xD457, "uk_fill"},             // rectangle in one colour, streamed
        {0xD4AD, "uk_acc"},              // R6:R7 = accent (theme colour, SMSL orange on White)
        {0xD4BE, "hn_name_ptr"},         // volume page: input 1..6 -> name pointer
        {0xD4D7, "uk_avg"},              // R6:R7 = per-channel average of the RGB565 colours R2:R3, R4:R5
        {0xD4EF, "uk_tfetch"},           // uk_text: next character (code or XDATA string)
        {0xD576, "uk_text"},             // proportional text painter (pfont fonts): align, spacing, x clip; 1-bit or 4-level run-length; every row
        {0xD57E, "uk_textc"},            // uk_text with a row clip (TP_YC0..TP_YC1): the number roll
        {0xDA99, "tx_yclip"},            // uk_text: the run-length decoder for cells cut by the row clip
        {0xDB4D, "hn_draw_volume"},      // replaces volpage_draw_volume 0x5936: records the value (muted: the text "M"); idle page: caption, then a roll; a mute change also redraws the label and the line
        {0xDBEC, "hn_dyn_now"},          // the number, the line (spring snapped) and the dB caption at once
        {0xDBFA, "hn_dec2"},             // A (0..99) -> decimal text at DPTR, no leading zero, NUL
        {0xDC0E, "hn_roll"},             // number roll: one frame per tick (after hn_spring), 14 frames, idle page only
        {0xDC66, "hv_num"},              // volume page: the number, right-aligned (num84), the rest of the roll box black; ends a roll
        {0xDC75, "hn_num_at"},           // a number in num84 at a row offset and ink, clipped to the roll box, the rest of the box black; the text "M": MUTE (hn_strmute) in pf_name, the ink's red part
        {0xDD52, "hv_name"},             // volume page: the input name (disp36)
        {0xDDA7, "hv_status"},           // volume page: the status line, loaded by hn_stat_load (mono16)
        {0xDE05, "hn_stat_load"},        // XDATA 0x50 = the status line as home_refresh_periodic loads it (0x4016.., hn_hold returns)
        {0xDE19, "hn_dim_ink"},          // TP_INK = DIM, or DIM_LOST without a signal (0x22.5) on a digital input
        {0xDE34, "hv_vol"},              // volume page: VOL, letter-spaced, accent; muted (0x22.1): the red muted speaker (pf_icon)
        {0xDECA, "hv_capr"},             // volume page: "max 60"
        {0xDF17, "hv_div"},              // volume page: divider
        {0xDF28, "hv_cap"},              // volume page: the dB caption from the NJW1194 code table 0x9289
        {0xDFE4, "hv_line"},             // volume page: whole position line (two halves)
        {0xE00F, "hn_line_seg"},         // columns HN_S0..HN_S1 of the position line, split HN_SPL (the spring's); the fill dark red while muted
        {0xE08B, "hn_vol_static"},
        {0xE09A, "hn_volpage"},          // page 2 renderer (jump-table entry 0x2143)
        {0xE0BB, "hn_spring"},           // the position line's spring: one tick (fixed-point matrix of the mock's integrator), redraws the moved columns
        {0xE1DA, "hn_sp_lin"},           // spring: V * k - e * k' (Q16)
        {0xE20E, "hn_sp_mulx"},          // spring: signed word at DPTR * R4:R5 / 65536, rounded
        {0xE261, "hn_sp_t6"},            // spring: 64 * the line's fill for HN_VOL; 0 while muted
        {0xE286, "hn_sp_split"},         // spring: position -> split column 16..304
        {0xE2BA, "hn_sp_snap"},          // spring: on its target, still (hn_volpage, hn_dyn_now)
        {0xE2D1, "hn_sp_reset"},         // spring: at 0, still, split 16 (home)
        {0xE2E8, "hn_enter_vol"},        // volume-key sites and hn_clear page 2: start / turn round the entry wipe
        {0xE321, "hn_mute_key"},         // replaces key_1c 0x1047: the stock toggle, then the volume page (hn_enter_vol unless open) and vol_key_tail_draw
        {0xE344, "hn_key_p2"},           // read_key's page-2 filter from 0x3DD1: keeps the mute key 0x1C as well as 0x1A, 0x1B, 0x1F
        {0xE354, "hn_reverse"},
        {0xE371, "hn_clear"},            // ui_render_page's clear (0x2106): entry, exit, or cancel + stock clear
        {0xE3D5, "hn_stop"},             // no wipe, no page drawn, no roll, spring at home (hn_cancel, hn_home_now)
        {0xE3E5, "hn_cancel"},           // ui_clear_screen's first instruction: stops a wipe and a roll, spring home
        {0xE3EE, "hn_hold"},             // 0x4081: holds the periodic home refresh back during a wipe
        {0xE411, "hn_name_guard"},       // home_draw_input_name's entry: cancels an exit wipe first
        {0xE421, "hn_home_now"},         // stop a wipe, black, then hn_hold's stock path: home_refresh + status line (hn_name_guard)
        {0xE42A, "hn_flag_path"},        // 0x3FF8: during a wipe the flag path skips its 0x412F fill
        {0xE43F, "hn_name_load"},        // XDATA 0x35 = input name, as 0x4A85 loads it
        {0xE460, "hh_icon"},  {0xE463, "hh_vol"},  {0xE468, "hh_fmt"},  {0xE46B, "hh_eq"},  {0xE46E, "hh_bar"},  {0xE47E, "hh_name"}, // exit wipe: home elements
        {0xE481, "uk_tasks"},            // replaces main_tasks_on's lcall main_tick_tasks (0x5B2A): re-mute request, then per tick a wipe step, the spring, the roll
        {0xE497, "hn_step"},             // one wipe step
        {0xEA1F, "hn_after"},            // each tick after hn_step: hn_spring, then hn_roll
        {0xEA7B, "hn_home_tail"},        // home_refresh's tail: volume, accent bar
        {0xEA8E, "hn_align_big"},        // big_text_render on page 1: the name at y 75 is hm_name, other texts start at x 16
        {0xEAB5, "hn_align_small"},      // small_text_render on page 1: the status at y 135 is hm_status_r, other texts start at x 16
        {0xEADC, "hm_name"},             // home: the input name (XDATA 0x35), display face
        {0xEB34, "hm_name_meas"},        // hm_name's end column, nothing drawn
        {0xEB81, "hm_status_r"},         // small_text_render's hand-over at y 135: grey unless the draw is the loader's (hn_hold marks it), then hm_status
        {0xEB8D, "hm_status"},           // home: the status line (XDATA 0x50), mono
        {0xEBE8, "hm_stat_meas"},        // hm_status's end column, nothing drawn
        {0xEC35, "hm_rest"},             // black from TP_END + 1 to R6:R7, rows R5.., R4 rows (not during a wipe)
        {0xEC95, "hm_icon"},             // replaces home_draw_output_icon 0x5744: speaker / muted / headphones
        {0xED9B, "hm_volume"},           // replaces home_draw_volume 0x5916
        {0xEE07, "hm_eq"},               // replaces eq_tag_paint 0x4F18: the EQ tag box
        {0xEE10, "hm_fmt"},              // replaces home_draw_format_tag's lcall small_text_at (0x425D): the format tag box
        {0xEE17, "hm_tag"},              // a tag: accent box with corners of radius 2 (pf_box edges) and text, black up to it
        {0xEE4C, "ht_edges"},            // hm_tag: the box edges (pf_box "[" and "]")
        {0xEFE6, "hm_tag_copy"},         // R3:R2:R1 string -> HM_TAG, trailing spaces cut
        {0xF026, "hm_fmt_clear"},        // replaces home_draw_format_tag's tag_box_clear calls (0x41E8, 0x41FC)
    };

    Object[][] codeLabels = {
        {0x0000, "RESET_VEC"}, {0x0003, "INT0_VEC"}, {0x000B, "T0_VEC"},
        {0x0013, "INT1_VEC"},  {0x001B, "T1_VEC"},   {0x0023, "UART1_VEC"},
        {0x009B, "T3_VEC"},    {0x540A, "main_loop"},
        {0x5635, "input_apply_check"}, {0x5640, "input_apply"},
        {0x5D17, "ir_cmd_to_key_tail"},
        {0x22FA, "ui_render_done"},         {0x336A, "main_render_page"},
        {0x3DD6, "read_key_volpage_exit"},  // page 2: keys other than Vol+/Vol-/Power -> 0x15 (home)
        {0x3DC6, "read_key_volpage_filter"}, // read_key, IR, page 2: key 0x1A, 0x1B or 0x1F -> 0x3DD8, else read_key_volpage_exit
        {0x3DD1, "read_key_volpage_last"},  // its last test, mov A,R3 ; xrl A,#0x1F (hooked, features/house-numerals: hn_key_p2 keeps the mute key 0x1C too)
        {0x0C23, "dispatch_key_menu_mute"}, // dispatch_key, pages >= 3: the mute key 0x1C -> 0x15 (home), so key_1c only runs on pages 1 and 2
        {0x0CB3, "key_switch_1c"},          // dispatch_key's switch table entry: 0x1047, key 0x1C
        {0x0F50, "vol_key_tail_draw"},      // vol_key_tail from its draw: volpage_draw_volume(0x31), 0x27:0x28 = 0x3F:0x40 = 200 (hn_mute_key ends here)
        {0x1052, "key_1c_toggle"},          // cpl 0x22.1; muted: mute_state_set(0), clr P2.5; unmuted: 0x43:0x44 = 10
        {0x3ED9, "t0_return_home"},         // 0x3F:0x40 reaches 0 -> page 1, redraw
        {0x0BBD, "key_arm_screen_off"},     // dispatch_key, dimmer 2: setb P0.6 (not for key 0x1F), g_screen_off = (dimmer-1)*500
        {0x33DB, "screen_off_tick"},        // main_tick_10ms, dimmer 2: countdown16_dec(g_screen_off); reaching 0 -> clr P0.6 (backlight off)
        {0x3335, "main_tick_10ms"},         // runs once per 0x20.7 tick flag; missed ticks are lost
        {0x332F, "main_tick_flag_test"},    // jb 0x20.7: the 10 ms tick path of main_tick_tasks
        {0x3351, "osd_timer_expired"},      // page 1, 0x27:0x28 ran out: lcall home_refresh_periodic
        {0x5B2A, "main_tasks_tick_call"},   // main_tasks_on: lcall main_tick_tasks (hooked, features/house-numerals: uk_tasks)
        {0x5422, "main_loop_tasks_call"},   // main loop, amp on: lcall main_tasks_on
        {0x4081, "home_refresh_periodic_draw"}, // lcall home_refresh; status line (hooked, features/house-numerals: hn_hold)
        {0x3FF8, "home_refresh_periodic_flags"}, // 0x21.3 / 0x21.1 / 0x20.6 set: clear them, page 1, 0x412F fill (hooked, features/house-numerals: hn_flag_path)
        {0x4A9B, "input_name_table"},       // home_draw_input_name's jump table, inputs 1..8 (7: no load)
        {0x9864, "hn_ease"},                // features/house-numerals: wipe edge x per step (STEPS + 1 words, the cubic ease)
        {0x9800, "hn_names"},               // features/house-numerals: volume-page name pointers, inputs 1..6
        {0x9854, "hn_names8"},              // features/house-numerals: home_draw_input_name's strings, inputs 1..8
        {0x9825, "hn_rolltab"},        // features/house-numerals: number roll frames 1..13 (rows for a step up, ink), 3 bytes each
        {0x984C, "hn_spkt"},           // features/house-numerals: spring constants K2, K1, K4, K3 (Q16 words)
        {0x9817, "hn_strmute"},        // features/house-numerals: "MUTE", the muted volume page's text (hn_num_at)
        {0x98B0, "pf_name"},    // features/house-numerals: disp54, home name, format 2 (uk_text)
        {0xA43A, "pf_status"},  // features/house-numerals: mono28, home status line, format 2 (uk_text)
        {0xB6BC, "pf_mono"},    // features/house-numerals: mono16, tags, volume-page small texts, format 2 (uk_text)
        {0xC2EE, "pf_hvol"},    // features/house-numerals: num33, home volume, format 2 (uk_text)
        {0xC678, "pf_icon"},    // features/house-numerals: icons22, icons, format 2 (uk_text)
        {0xC80B, "pf_box"},     // features/house-numerals: box22, tag box edges (pfont.box_edges), format 2 (uk_text)
        {0xC837, "pf_vname"},   // features/house-numerals: disp36, volume-page name, format 2 (uk_text)
        {0xCBE6, "pf_vnum"},    // features/house-numerals: num84, volume-page number, format 2 (uk_text)
        {0x33ED, "mute_timer_expired"},     // 0x43:0x44 reaches 0 -> mute_state_set(1) (call at 0x33FB)
        {0x341B, "format_poll_tick"},       // inputs 1..5: 0x4B:0x4C reaches 0 -> reload 10, format_poll, on BT bt_hold_mute_poll
        {0x3E92, "t0_remute_no_lock"},      // Timer0: optical/coax and P4.2 high (no lock) -> setb 0x21.4, 0x43:0x44 = 100
        {0x3EE9, "t0_hold_mute_p26"},       // Timer0: P2.6 low, powered, output 2 (or P2.6 high in standby) -> clr P2.5, 0x43:0x44 = 300
        {0x45CE, "port_init"},              {0x5C79, "lcd_write_pixel_black"},
        {0x2143, "ui_page_table"},          // jump-table entry for page 2 (data: 02 21 67, ljmp volpage_render); 12 ljmps, pages 2..13. Any other page: ljmp ui_render_done at 0x2132
        {0x1143, "menu_enter_table"},       // key_menu_nav on page 3: 10 ljmps indexed by the main-menu cursor (0x17, checked against 10 at 0x1134; else ljmp 0x11BB at 0x1139).
                                            // Item i opens page i + 4; key_menu (back) and 0x1261 rely on that: 0x17 = page - 4
        {0x5596, "post_power_on_chips"},    // post_power_on: lcall audio_chips_init, outputs still muted; cold power-up and standby wake both pass here (hooked, features/start-volume: sv_limit)
        {0x442F, "lcd_set_window_x1_from_a"},
        {0x2A25, "big_text_start_x_stored"},   // big_text_render: clr A ; mov R0,#2 ; movx @R0,A (hooked, features/house-numerals)
        {0x3A82, "small_text_start_x_stored"}, // small_text_render: same shape (hooked, features/house-numerals)
        {0x0F48, "vol_key_tail"},            // common tail of the volume keys: volume_apply, 0x5D7D, draw (0x5936), arm page timers
        {0x0D30, "volpage_enter_a"},         // mov 0x45,#2 before volume-entry site 0x0D33, in key_volume_up
        {0x0DB0, "volpage_enter_b"},         // mov 0x45,#2 before volume-entry site 0x0DB3, in key_volume_up2
        {0x0E57, "volpage_enter_c"},         // mov 0x45,#2 before volume-entry site 0x0E5A, in key_volume_down4
        {0x0EFF, "volpage_enter_d"},         // mov 0x45,#2 before volume-entry site 0x0F02, in key_volume_down
        // data
        {0x5DAB, "font_small_14x24"},       {0x6A23, "font_big_32x30"},
        {0x9241, "theme_colours_rgb565"},   {0x9289, "volume_code_table"},
        {0x92C6, "clkgen_table"},           // 43 x (register hi, lo, value) for the clock generator at I2C 0xC0
        {0x9251, "str_bt_clear"},           {0x9270, "str_not_bt"},             {0x934E, "str_bt_reconnect"},
        {0x9048, "input_name_strings"},     {0x9347, "str_volume"},
        {0x9260, "str_resetting"},
        // menu list tables for menu_list_render, 4-byte entries {count, FF, string hi, lo}, packed back to back
        {0x8F1E, "menu_list_input"},        // 6
        {0x8F36, "menu_list_eq"},           // 8
        {0x8F56, "menu_list_color"},        // 8
        {0x8F76, "menu_list_output"},       // 2
        {0x8F7E, "menu_list_dimmer"},       // 2
        {0x8F86, "menu_list_main"},         // 10: Input, Output, EQ, Treble, Bass, Filter, Color, BT Clear, Dimmer, RESET. Referenced by the immediates at
                                            // 0x2197 / 0x2199 (page 3 renderer) and by the Keil init record at 0x583A (03 11 FF 8F 86: RAM 0x11..0x13)
        {0x8FAE, "menu_list_filter"},       // 5
        {0x8D6D, "menu_main_strings"},      // "- Input      " ...: 10 x 14 bytes
    };

    Object[][] ramLabels = {
        {0x10, "g_menu_a"},        {0x17, "g_menu_cursor"},   {0x19, "g_menu_b"},
        // menus: 0x10 highlighted row on screen, 0x19 scroll offset, 0x17 selected item (a value 0..18 on the Treble, Bass and BT Clear pages)
        {0x14, "g_menu_len"},      {0x15, "g_menu_rows"},     {0x16, "g_menu_main_item"},
        // 0x14: items in the list on screen (menu_list_render); 0x15: visible rows, 5 (init record at 0x5836); 0x16: main-menu item kept while a sub-page is open
        {0x26, "g_power_on_flag"}, // EEPROM 0x0002: non-zero, the amp turns on by itself after a cold power-up (standby_power_step)
        {0x37, "g_save_timer_hi"}, {0x38, "g_save_timer_lo"}, // reset_timer_37 arms it to 50; at 0 (0x3446) settings_save_eeprom
        {0x27, "g_osd_timer_hi"},  {0x28, "g_osd_timer_lo"},  {0x29, "g_dimmer_mode"},
        // 0x27:0x28, page 1: home_refresh_periodic countdown (10 after a render, 50 after a refresh)
        {0x2B, "g_output"},        {0x2C, "g_filter"},        {0x2F, "g_screen_off_hi"},
        {0x2D, "g_encoder_key"},   // encoder_scan result; read_key's tail returns it on every page when no IR or panel key is pending
        {0x30, "g_screen_off_lo"}, {0x31, "g_volume"},        {0x32, "g_render_req"},
        {0x39, "g_eq"},            {0x3D, "g_format"},        // g_format: 3 DSD, 4 MQA (by 0x75), 5 DoP, else PCM (home_draw_format_tag)
        {0x75, "g_format_mqa"},    // with g_format 4: 3 -> "MQA ", 4 or 5 -> "MQA.", else "PCM "
        // bit 0x22.1: muted (the mute key cpl's it, 0x1052); home_draw_output_icon draws the red icon then
        {0x3F, "g_home_timer_hi"}, {0x40, "g_home_timer_lo"}, {0x43, "g_mute_timer_hi"},
        {0x44, "g_mute_timer_lo"},      // unmute countdown, main-loop ticks; see 0x33ED
        {0x23, "g_settle_timer_hi"}, {0x24, "g_settle_timer_lo"}, // 1000 at power-on, 500 by input_set_hw, 100 after a format reconfig; reloads 100
        {0x4B, "g_format_poll_hi"},  {0x4C, "g_format_poll_lo"},  // format_poll_tick countdown, 10 ticks
        {0x4E, "g_format_cfg"},      // format the DAC is set up for; 0xFF: none (input switch, INT1)
        {0x58, "g_format_read"},     // last format_read result
        {0x7C, "g_signal_loss_hi"},  {0x7D, "g_signal_loss_lo"}, // signal_monitor: after a loss, then clr P2.5
        {0x45, "g_ui_page"},       {0x46, "g_render_req2"},
        {0x47, "g_input"},         {0x48, "g_text_colour_hi"}, {0x49, "g_text_colour_lo"},
        {0x52, "g_volume_hp"},
        {0x4F, "g_power_on"},      {0x54, "g_ir_pulse_hi"},   {0x55, "g_ir_pulse_lo"},
        {0x56, "g_ir_error"},      {0x57, "g_last_key"},      {0x6A, "g_ir_cmd"},
        {0x6B, "g_ir_state"},      {0x6C, "g_ir_repeat_cnt"}, {0x6D, "g_ir_shift_hi"},
        {0x6E, "g_ir_shift_lo"},   {0x6F, "g_ir_key2"},       {0x70, "g_ir_bit_cnt"},
        {0x68, "g_pixel_hi"},      {0x69, "g_pixel_lo"},      {0x7F, "g_blink_timer"},
        {0x59, "l_render_page"},  // page argument saved inside ui_render_page (0x2101)
        {0x3B, "g_bt_enable_hi"},  {0x3C, "g_bt_enable_lo"},  // 200 ticks from input_set_hw on Bluetooth (else 0); when it runs out (0x3449) expander pin 0x10 goes high
        {0x73, "g_xmos_rate"},     // second byte of the XMOS message, rate index 1..12 (xmos_format_take)
        {0x76, "g_uart_byte0"},    {0x77, "g_uart_byte1"},    // uart1_isr: the message bytes before the 0xFF terminator
        {0x78, "g_uart_valid"},    // 0xFF after a terminator; a third message byte would overwrite it
        {0x79, "g_uart_index_hi"}, {0x7A, "g_uart_index_lo"},
        {0x7E, "g_format_tag_drawn"},  // home_draw_format_tag: the format (0x3D) its tag shows; the box is cleared when it changes
    };

    static final int TABLE_ADDR = 0x9398;
    static final int TABLE_LEN = 15;

    AddressSpace space(String name) {
        return currentProgram.getAddressFactory().getAddressSpace(name);
    }

    Address code(int off) {
        return space("CODE").getAddress(off);
    }

    boolean inImage(Address a) {
        return currentProgram.getMemory().contains(a);
    }

    void label(Address a, String name) throws Exception {
        currentProgram.getSymbolTable().createLabel(a, name, SourceType.USER_DEFINED);
    }

    void makeFunc(int off, String name) throws Exception {
        Address a = code(off);
        if (!inImage(a)) return;
        if (currentProgram.getListing().getInstructionAt(a) == null) {
            disassemble(a);
        }
        Function f = currentProgram.getFunctionManager().getFunctionAt(a);
        if (f == null) f = createFunction(a, name);
        if (f != null) f.setName(name, SourceType.USER_DEFINED);
        else label(a, name);
    }

    void makeTable() throws Exception {
        Address a = code(TABLE_ADDR);
        if (!inImage(a)) return;
        Address end = code(TABLE_ADDR + TABLE_LEN - 1);
        clearListing(new AddressSet(a, end));
        createData(a, new ArrayDataType(ByteDataType.dataType, TABLE_LEN, 1));
        label(a, "ir_cmd_to_key_table");
    }

    @Override
    public void run() throws Exception {
        for (Object[] e : codeFuncs) makeFunc((Integer) e[0], (String) e[1]);
        for (Object[] e : codeLabels) {
            Address a = code((Integer) e[0]);
            if (inImage(a)) label(a, (String) e[1]);
        }
        makeTable();
        AddressSpace ram = space("INTMEM");
        if (ram == null) ram = space("RAM");
        if (ram == null) {
            println("no INTMEM space found; RAM labels skipped");
        } else {
            for (Object[] e : ramLabels) label(ram.getAddress((Integer) e[0]), (String) e[1]);
        }
        println("SMSL AO300 labels applied");
    }
}
