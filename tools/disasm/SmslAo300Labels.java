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
        {0x536F, "key_history_combo"}, {0x549F, "int0_isr"},
        {0x55F2, "uart1_isr"},         {0x5628, "input_step"},
        {0x56E8, "int1_isr"},          {0x588B, "input_menu_select"},
        {0x58AF, "eeprom_write"},      {0x58D3, "input_show_name"},
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
        {0x4DDC, "volume_apply"},      // R7 = volume (0x31): saves it in 0x5B, looks up 0x9289, njw1194_write(R7=0x10)
        // main loop and timers
        {0x3325, "main_tick_tasks"},   {0x5585, "post_power_on"},
        {0x5A62, "mute_state_set"},    // R7=0: clear 0x22.4, P2.2 on; else 0x5B39 by output
        {0x5B39, "p2_mute_pins_by_output"}, // output 1: P2.5/P2.7/P2.2 low, 2: high
        {0x5A78, "countdown16_dec"},   {0x5B22, "main_tasks_on"},
        {0x5D6E, "dispatch_key_if_any"},
        // Keil runtime
        {0x1EF5, "keil_cldptr"},       {0x1F91, "keil_ildptr"},
        // patch code, only in the images that carry it
        {0x9400, "ir_direct_select"},  // features/direct-select
        {0x9450, "blit_test"},         // features/blit-test
        {0x9700, "fast_pixel"},        // features/fast-lcd, replaces lcd_write_pixel
        {0x9716, "fast_clear"},        // features/fast-lcd, replaces lcd_clear_black's loop
        {0x9810, "hn_fill"},           // features/house-numerals
        {0x9866, "hn_begin"},          // features/house-numerals
        {0x9888, "hn_end"},            // features/house-numerals
        {0x9893, "hn_accent"},         // features/house-numerals
        {0x98A0, "hn_white"},          // features/house-numerals
        {0x98A7, "hn_name_ptr"},       // features/house-numerals
        {0x98C0, "hn_text"},           // features/house-numerals
        {0x990D, "hn_digit2x"},        // features/house-numerals
        {0x9999, "hn_draw_volume"},    // features/house-numerals
        {0x9A32, "hn_vol_static"},     // features/house-numerals
        {0x9A6A, "hn_volpage"},        // features/house-numerals
        {0x9A75, "hn_enter_vol"},      // features/house-numerals
        {0x9A7C, "hn_clear"},          // features/house-numerals
        {0x9A86, "hn_wipe"},           // features/house-numerals
        {0x9B10, "hn_home_tail"},      // features/house-numerals
        {0x9B2E, "hn_align_big"},      // features/house-numerals
        {0x9B48, "hn_align_small"},    // features/house-numerals
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
        {0x3335, "main_tick_10ms"},         // runs once per 0x20.7 tick flag; missed ticks are lost
        {0x33ED, "mute_timer_expired"},     // 0x43:0x44 reaches 0 -> mute_state_set(1)
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
        {0x2B, "g_output"},        {0x2C, "g_filter"},        {0x2F, "g_screen_off_hi"},
        {0x30, "g_screen_off_lo"}, {0x31, "g_volume"},        {0x32, "g_render_req"},
        {0x39, "g_eq"},
        {0x3F, "g_home_timer_hi"}, {0x40, "g_home_timer_lo"}, {0x43, "g_mute_timer_hi"},
        {0x44, "g_mute_timer_lo"},      {0x45, "g_ui_page"},       {0x46, "g_render_req2"},
        {0x47, "g_input"},         {0x48, "g_text_colour_hi"}, {0x49, "g_text_colour_lo"},
        {0x52, "g_volume_hp"},
        {0x4F, "g_power_on"},      {0x54, "g_ir_pulse_hi"},   {0x55, "g_ir_pulse_lo"},
        {0x56, "g_ir_error"},      {0x57, "g_last_key"},      {0x6A, "g_ir_cmd"},
        {0x6B, "g_ir_state"},      {0x6C, "g_ir_repeat_cnt"}, {0x6D, "g_ir_shift_hi"},
        {0x6E, "g_ir_shift_lo"},   {0x6F, "g_ir_key2"},       {0x70, "g_ir_bit_cnt"},
        {0x68, "g_pixel_hi"},      {0x69, "g_pixel_lo"},      {0x7F, "g_blink_timer"},
        {0x59, "l_render_page"},  // page argument saved inside ui_render_page (0x2101)
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
