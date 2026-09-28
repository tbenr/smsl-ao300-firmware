// Apply labels for the SMSL AO300 firmware (STC8C2K64S2, 8051).
// Works on both the stock image (flash.bin) and the patched one (flash_patched.bin).
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
        {0x0D03, "key_volume_up"},     {0x0ED2, "key_volume_down"},
        {0x0F62, "key_59"},            {0x0F93, "key_source_next"},
        {0x0FC8, "key_source_prev"},   {0x1006, "key_output_toggle"},
        {0x1047, "key_1c"},            {0x106D, "key_bt_function"},
        {0x10BE, "key_toggle_29"},     {0x10E1, "key_38_combo"},
        {0x10FC, "key_menu_nav"},      {0x126F, "key_up"},
        {0x135A, "key_down"},          {0x144E, "key_menu"},
        {0x14E3, "key_default"},       {0x2072, "keil_switch_case"},
        {0x202C, "cmp_u32"},           {0x24D6, "input_set_hw"},
        {0x2681, "nec_decode"},        {0x2F46, "settings_load_eeprom"},
        {0x3A53, "lcd_fn_3a53"},       {0x3DA2, "read_key"},
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
        {0x5D42, "ui_redraw_home"},    {0x5D4B, "timer1_isr"},
        {0x5D7D, "reset_timer_37"},    {0x5D8A, "inject_key_08"},
        {0x9400, "ir_direct_select"},  // patched image only
    };

    Object[][] codeLabels = {
        {0x0000, "RESET_VEC"}, {0x0003, "INT0_VEC"}, {0x000B, "T0_VEC"},
        {0x0013, "INT1_VEC"},  {0x001B, "T1_VEC"},   {0x0023, "UART1_VEC"},
        {0x009B, "T3_VEC"},    {0x540A, "main_loop"},
        {0x5635, "input_apply_check"}, {0x5640, "input_apply"},
        {0x5D17, "ir_cmd_to_key_tail"},
    };

    Object[][] ramLabels = {
        {0x10, "g_menu_a"},        {0x17, "g_menu_cursor"},   {0x19, "g_menu_b"},
        {0x27, "g_osd_timer_lo"},  {0x28, "g_osd_timer_hi"},  {0x29, "g_toggle_29"},
        {0x2B, "g_output"},        {0x31, "g_volume"},        {0x39, "g_eq"},
        {0x3F, "g_timer_3f"},      {0x40, "g_timer_40"},      {0x43, "g_timer_43"},
        {0x44, "g_timer_44"},      {0x45, "g_ui_page"},       {0x47, "g_input"},
        {0x4F, "g_power_on"},      {0x54, "g_ir_pulse_hi"},   {0x55, "g_ir_pulse_lo"},
        {0x56, "g_ir_error"},      {0x57, "g_last_key"},      {0x6A, "g_ir_cmd"},
        {0x6B, "g_ir_state"},      {0x6C, "g_ir_repeat_cnt"}, {0x6D, "g_ir_shift_hi"},
        {0x6E, "g_ir_shift_lo"},   {0x6F, "g_ir_key2"},       {0x70, "g_ir_bit_cnt"},
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
