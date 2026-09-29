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
        {0x1047, "key_1c"},            {0x106D, "key_bt_function"},
        {0x10BE, "key_toggle_29"},     {0x10E1, "key_38_combo"},
        {0x10FC, "key_menu_nav"},      // reached by NEC 0x04, which opens the menu (page -> 3) from home
        {0x126F, "key_up"},
        {0x135A, "key_down"},          {0x144E, "key_menu"},          // NEC 0x03 (NEC_MENU in ao300.py); acts only inside a menu, does not open it
        {0x14E3, "key_default"},       {0x2072, "keil_switch_case"},
        {0x202C, "cmp_u32"},           {0x24D6, "input_set_hw"},
        {0x2681, "nec_decode"},        {0x2F46, "settings_load_eeprom"},
        {0x3A53, "small_text_render"}, {0x3DA2, "read_key"},
        {0x3E67, "timer0_isr"},        {0x449F, "main_init"},
        {0x4E2D, "step_with_wrap"},    {0x5040, "timer3_isr"},
        {0x396D, "encoder_scan"},      // timer3_isr (every 0.5 ms): RE_A P5.5 / RE_B P5.4 -> key code, stored in 0x2D (0xFF idle)
        {0x536F, "key_history_combo"}, {0x549F, "int0_isr"},
        {0x55F2, "uart1_isr"},         {0x5628, "input_step"},
        {0x56E8, "int1_isr"},          {0x588B, "input_menu_select"},
        {0x58AF, "eeprom_write"},
        {0x58D3, "audio_apply_mute"},  // 0x22.4 set: volume_apply(0x31), setb 0x22.5; clear: NJW1194 to the mute code (0x92C5), clr 0x22.5; then DAC reg 9 by 0x22.5 (0x5A0A). 5.2 ms when muting
        {0x5956, "eeprom_read"},       {0x59B2, "standby_key"},
        {0x59D0, "eeprom_erase"},      {0x5A5E, "fn_5a5e"},
        {0x5AAB, "power_on_sequence"}, {0x5CE8, "iap_idle"},
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
        {0x4CDF, "i2c_read_reg16"},    // R7 device, R4:R5 register, returns R7; 5 tries
        {0x4DDC, "volume_apply"},      // R7 = volume (0x31): saves it in 0x5B, looks up 0x9289, njw1194_write(R7=0x10)
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
        {0x9400, "ir_direct_select"},  // features/direct-select
        {0x9450, "blit_test"},         // features/blit-test
        {0x9680, "fx_auto_off"},       // features/fix-auto-off standalone image; builds that include the fix place it in their own code
        {0x9700, "fast_pixel"},        // features/fast-lcd, replaces lcd_write_pixel
        {0x9716, "fast_clear"},        // features/fast-lcd, replaces lcd_clear_black's loop
        // features/house-numerals (hn6)
        {0xBC45, "uk_fill"},         // rectangle in one colour, streamed
        {0xBC9B, "uk_acc"},          // R6:R7 = accent (theme colour, SMSL orange on White)
        {0xBCAC, "hn_name_ptr"},     // volume page: input 1..6 -> name pointer
        {0xBCC5, "uk_fp_load"},      // uk_paint: copy the font descriptor
        {0xBCE5, "uk_fetch"},        // uk_paint: next character (code or XDATA string)
        {0xBD0C, "uk_map"},          // uk_paint: character -> glyph index | narrow
        {0xBD28, "uk_home_x"},       // stock page-1 start x of a text (centring + x 16 rule)
        {0xBD95, "uk_paint"},        // text painter: font, string, x, y, ink, background, x clip, scale 1/2
        {0xBE6E, "uk_cell"},         // uk_paint: one glyph cell, streamed
        {0xC1DD, "uk_avg"},          // R6:R7 = per-channel average of the RGB565 colours R2:R3, R4:R5
        {0xC1F5, "uk_tfetch"},       // uk_text: next character (code or XDATA string)
        {0xC27C, "uk_text"},         // proportional text painter (pfont fonts): align, spacing, x clip; 1-bit or 4-level run-length
        {0xC749, "hn_draw_volume"},  // replaces volpage_draw_volume 0x5936
        {0xC796, "hv_num"},          // volume page: number (big font at 2x)
        {0xC7DF, "hv_name"},         // volume page: input name
        {0xC830, "hv_vol"},          // volume page: VOL
        {0xC87A, "hv_div"},          // volume page: divider
        {0xC88B, "hv_line"},         // volume page: whole position line
        {0xC89F, "hn_line_seg"},     // columns HN_S0..HN_S1 of the position line
        {0xC927, "hn_vol_static"},
        {0xC930, "hn_volpage"},      // page 2 renderer (jump-table entry 0x2143)
        {0xC94F, "hn_enter_vol"},    // volume-key sites and hn_clear page 2: start / turn round the entry wipe
        {0xC982, "hn_reverse"},
        {0xC998, "hn_clear"},        // ui_render_page's clear (0x2106): entry, exit, or cancel + stock clear
        {0xC9F3, "hn_cancel"},       // ui_clear_screen's first instruction: stops a wipe
        {0xCA02, "hn_hold"},         // 0x4081: holds the periodic home refresh back during a wipe
        {0xCA15, "hn_name_guard"},   // home_draw_input_name's entry: cancels an exit wipe first
        {0xCA25, "hn_home_now"},     // stop a wipe, black, home_refresh + status line (hn_name_guard)
        {0xCA3B, "hn_flag_path"},    // 0x3FF8: during a wipe the flag path skips its 0x412F fill
        {0xCA50, "hn_name_load"},    // XDATA 0x35 = input name, as 0x4A85 loads it
        {0xCA71, "hh_icon"},  {0xCA74, "hh_vol"},  {0xCA79, "hh_fmt"},  {0xCA7C, "hh_eq"},  {0xCA7F, "hh_bar"},  {0xCA8F, "hh_name"}, // exit wipe: home elements
        {0xCA92, "uk_tasks"},        // replaces main_tasks_on's lcall main_tick_tasks (0x5B2A): one wipe step per tick
        {0xCAA0, "hn_step"},         // one wipe step
        {0xCF82, "hn_home_tail"},    // home_refresh's tail: volume, accent bar
        {0xCF95, "hn_align_big"},    // big_text_render on page 1: the name at y 75 is hm_name, other texts start at x 16
        {0xCFBC, "hn_align_small"},  // small_text_render on page 1: the status at y 135 is hm_status, other texts start at x 16
        {0xCFE3, "hm_name"},         // home: the input name (XDATA 0x35), display face
        {0xD03B, "hm_name_meas"},    // hm_name's end column, nothing drawn
        {0xD088, "hm_status"},       // home: the status line (XDATA 0x50), mono
        {0xD0E0, "hm_stat_meas"},    // hm_status's end column, nothing drawn
        {0xD12D, "hm_rest"},         // black from TP_END + 1 to R6:R7, rows R5.., R4 rows (not during a wipe)
        {0xD18D, "hm_icon"},         // replaces home_draw_output_icon 0x5744: speaker / muted / headphones
        {0xD293, "hm_volume"},       // replaces home_draw_volume 0x5916
        {0xD30E, "hm_eq"},           // replaces eq_tag_paint 0x4F18: the EQ tag box
        {0xD317, "hm_fmt"},          // replaces home_draw_format_tag's lcall small_text_at (0x425D): the format tag box
        {0xD31E, "hm_tag"},          // a tag: accent box and text, black up to it
        {0xD475, "hm_tag_copy"},     // R3:R2:R1 string -> HM_TAG, trailing spaces cut
        {0xD4B5, "hm_fmt_clear"},    // replaces home_draw_format_tag's tag_box_clear calls (0x41E8, 0x41FC)
    };

    Object[][] codeLabels = {
        {0x0000, "RESET_VEC"}, {0x0003, "INT0_VEC"}, {0x000B, "T0_VEC"},
        {0x0013, "INT1_VEC"},  {0x001B, "T1_VEC"},   {0x0023, "UART1_VEC"},
        {0x009B, "T3_VEC"},    {0x540A, "main_loop"},
        {0x5635, "input_apply_check"}, {0x5640, "input_apply"},
        {0x5D17, "ir_cmd_to_key_tail"},
        {0x22FA, "ui_render_done"},         {0x336A, "main_render_page"},
        {0x3DD6, "read_key_volpage_exit"},  // page 2: keys other than Vol+/Vol-/Power -> 0x15 (home)
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
        {0x9820, "hn_ease"},                // features/house-numerals: wipe edge x per step (21 words)
        {0x984A, "hn_font_small"},          // features/house-numerals: stock font descriptors and character maps (uk_paint)
        {0x9852, "hn_font_big"},
        {0x985A, "hn_map_small"},           {0x98BA, "hn_map_big"},
        {0x9920, "pf_name"},         // features/house-numerals: disp52, format 2 (uk_text)
        {0xA57C, "pf_status"},       // features/house-numerals: mono20, format 2 (uk_text)
        {0xB3DD, "pf_tag"},          // features/house-numerals: mono13, format 2 (uk_text)
        {0xB6DE, "pf_hvol"},         // features/house-numerals: num36, format 2 (uk_text)
        {0xBABE, "pf_icon"},         // features/house-numerals: icons23, format 2 (uk_text)
        {0x33ED, "mute_timer_expired"},     // 0x43:0x44 reaches 0 -> mute_state_set(1) (call at 0x33FB)
        {0x341B, "format_poll_tick"},       // inputs 1..5: 0x4B:0x4C reaches 0 -> reload 10, format_poll, on BT bt_hold_mute_poll
        {0x3E92, "t0_remute_no_lock"},      // Timer0: optical/coax and P4.2 high (no lock) -> setb 0x21.4, 0x43:0x44 = 100
        {0x3EE9, "t0_hold_mute_p26"},       // Timer0: P2.6 low, powered, output 2 (or P2.6 high in standby) -> clr P2.5, 0x43:0x44 = 300
        {0x45CE, "port_init"},              {0x5C79, "lcd_write_pixel_black"},
        {0x2143, "ui_page_table"},          // jump-table entry for page 2 (data: 02 21 67, ljmp volpage_render)
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
        {0x9048, "input_name_strings"},     {0x9347, "str_volume"},
    };

    Object[][] ramLabels = {
        {0x10, "g_menu_a"},        {0x17, "g_menu_cursor"},   {0x19, "g_menu_b"},
        {0x27, "g_osd_timer_hi"},  {0x28, "g_osd_timer_lo"},  {0x29, "g_dimmer_mode"},
        // 0x27:0x28, page 1: home_refresh_periodic countdown (10 after a render, 50 after a refresh)
        {0x2B, "g_output"},        {0x2C, "g_filter"},        {0x2F, "g_screen_off_hi"},
        {0x2D, "g_encoder_key"},   // encoder_scan result; read_key returns it on pages < 3 when no IR or panel key is pending
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
