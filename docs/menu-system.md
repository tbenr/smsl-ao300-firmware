# The stock menu, and what adding a setting would take

Notes from 2026-10-02, when a "start volume" menu entry was sized and then built as a
build-time setting instead (`features/start-volume`). None of it is built. Addresses are
the stock v1.4 image's. Items marked (read) come from decoding the routines once and were not
re-checked instruction by instruction; the rest was checked in the disassembly.

## Pages

`g_ui_page` (RAM 0x45): 1 home, 2 volume, 3..13 menus.

`ui_render_page` (0x2101, R7 = page):
- 0x2103: with bit 0x22.3 set it clears the screen first (the call at 0x2106).
- 0x210A..0x2126: pages 3 and up call 0x554C with the tint colour (probably the title rule).
- 0x2129: `add A,#0xFE ; cjne A,#0x0C`: pages 2..13 go through the jump table
  `ui_page_table` at 0x2143, 12 `ljmp`s. Page 2's code starts right after it at 0x2167, so
  the table cannot grow in place.
- Any other page, page 1 included, takes `ljmp 0x22FA` at **0x2132** (draws nothing).

| Page | Renderer (read) | Title | Body |
|---|---|---|---|
| 3 | 0x2182 | SETUP MENU | list `menu_list_main` 0x8F86 (10) |
| 4 | 0x219E | INPUT | list 0x8F1E (6) |
| 5 | 0x21BA | OUTPUT | list 0x8F76 (2) |
| 6 | 0x21D6 | EQ | list 0x8F36 (8) |
| 7 | 0x21F2 | TREBLE | value page, 0x57EF |
| 8 | 0x220D | BASS | value page, 0x5717 |
| 9 | 0x2282 | FILTER | list 0x8FAE (5) |
| 10 | 0x2228 | COLOR | list 0x8F56 (8) |
| 11 | 0x2243 | BT list clear | "Turn to clear" |
| 12 | 0x2267 | DIMMER | list 0x8F7E (2) |
| 13 | 0x22A2 | RESET | name, version (pointer 0x22CA), "HOLD MENU RESET BT!/ALL!" |

The main menu's item i opens page i + 4. Back (`key_menu`) and the Enter tail at 0x1261 rely
on it: both set `0x17 = page - 4` before returning to page 3.

## How a list page draws

The page 3 renderer, as an example (0x2182):

```
mov R3,#0xFF ; mov R2,#0x8E ; mov R1,#0x4B    ; title string
clr A ; mov R5,A ; mov R7,A ; lcall 0x4D3A    ; small_text_load
mov R7,#4 ; mov R6,#0 ; lcall 0x3A53          ; small_text_render, centred at y 4
mov R3,#0xFF ; mov R2,#0x8F ; mov R1,#0x86    ; the list table
ljmp 0x229B                                   ; mov R5,0x10 ; lcall menu_list_render (0x2B0D)
```

- A list table is 4-byte entries `{count, FF, string hi, string lo}`; every entry repeats
  the count. The strings are NUL-terminated, 13 characters wide ("- Input      ").
- `menu_list_render` (0x2B0D) (read): count to RAM 0x14, rows at x 70 from y 36, 28 px
  apart, 5 visible, row R5 highlighted.
- The tables are packed back to back (0x8F1E input, 0x8F36 EQ, 0x8F56 colour, 0x8F76 output,
  0x8F7E dimmer, 0x8F86 main, 0x8FAE filter): none can grow in place.
- `menu_list_main` has two references: the immediates at 0x2197 / 0x2199 above, and the Keil
  init record at 0x583A (`03 11 FF 8F 86`), which presets the pointer in RAM 0x11..0x13.

Menu RAM (register bank 2): 0x10 highlighted row, 0x14 list length, 0x15 visible rows (5),
0x16 main-menu item kept while a sub-page is open, 0x17 selected item or value, 0x19 scroll
offset. 0x3F:0x40 is the menu timeout (1000 ticks, armed by Up and Down at 0x126F / 0x135A).

## Keys

`dispatch_key` (0x0BB4) remaps keys by page, then switches through the Keil helper 0x2072
(read): on pages below 3, Up, Down, Back and OK (key 0x24) become "no key"; on pages 3 and
up, Power, Source, Mute and two more go home, and Vol+ / Vol- become Up / Down; pages 7 and
8 swap Up and Down.

- **Enter, `key_menu_nav` (0x10FC).** On page 3 (0x112F): `0x16 = 0x17`, then
  `cjne A,#0x0A` at 0x1134; items 0..9 go through `menu_enter_table` at 0x1143 (10 `ljmp`s,
  code follows directly), anything above takes `ljmp 0x11BB` at **0x1139**. On a sub-page
  the chain 0x11F2..0x125E applies the selection (input, output, EQ, colour, dimmer, filter),
  and 0x1261 returns to page 3 through `menu_main_restore` (0x46BC).
- **`menu_main_restore` (0x46BC).** Restores cursor and scroll for the main list; the item
  count 10 is an immediate at **0x4723 and 0x472A** (`mov A,#0x0A`).
- **Up / Down (0x126F / 0x135A).** Generic list scrolling over 0x10 / 0x14 / 0x15 / 0x17 /
  0x19. Pages 7, 8 and 11 are special-cased by a compare chain (0x1286..0x129B,
  0x1371..0x1386) and treat 0x17 as a value. Both start with two 3-byte instructions
  (`mov 0x3F,#0x03 ; mov 0x40,#0xE8`), usable as hook sites.
- **Back, `key_menu` (0x144E)** (read): `0x17 = page - 4`, page 3, render. Nothing is
  applied: Back cancels.
- Treble and Bass (0x57EF, 0x5717) (read) clamp R7 to 0..18, store it, apply the tone and
  draw the level through 0x4C2C. They apply live, from the renderer.

## Adding an item

What an 11th main-menu item with its own page needs:

1. **The list.** A copy of `menu_list_main` with 11 entries in the patch area (44 bytes; the
   ten stock strings stay where they are), both references repointed (0x2198, 0x219A and
   0x583D, 0x583E), and `#0x0A` -> `#0x0B` at 0x4723 and 0x472A. The old 40 bytes become
   dead. Appended items keep "page = item + 4": item 10 is page 14.
2. **Render.** A hook on 0x2132 for pages 14 and up (page 1 must still reach 0x22FA).
3. **Enter from the menu.** A hook on 0x1139 for items 10 and up.
4. **Apply on Enter.** A hook in the chain 0x11F2..0x1261. Note that 0x1265 overwrites 0x17
   with `page - 4`, so the hook has to sit before it.
5. **Up / Down** on a value page: hooks at 0x1272 and 0x135D with the page's own range.
6. **Storage.** EEPROM sectors 0x0600 and 0x0800 are free. `settings_save_eeprom` (0x492B)
   erases and rewrites sector 0x0200 with its 12 bytes only, so a byte added there would
   need that routine extended; a sector of our own does not touch stock at all.

None of these sites is hooked by an existing feature. Reordering or removing stock items
would break "page = item + 4"; renaming them is free once the list is ours.

Cost, estimated: about 260 bytes for one hard-wired value page (list 44, strings ~30,
renderer ~60, Enter ~25, save ~30, Up / Down ~35, the feature's own code).

## A menu kit

If several features want settings, the same hooks can be written once, table-driven
(`tools/patch/menukit.py`, like the UI kit):

- A feature declares its items at build time, for example
  `MENU = [menukit.Value("Start Vol", title="START VOLUME", lo=0, hi=60, default=0, zero_label="Last")]`.
  The build collects the items of everything in an image, assigns pages 14.. and one byte
  each in a settings record, and emits the list, the strings, an 8-byte descriptor per item
  and the generic code.
- Generic code: the page dispatch, a value-page renderer (title, number or a label for 0),
  Enter from the menu, Enter on the page, Up / Down within the descriptor's range.
- The record: one EEPROM sector (0x0600) and an XDATA shadow, loaded at a cold boot (a hook
  on the `lcall settings_load_eeprom` at 0x53F6; erased or out-of-range bytes fall back to
  the item's default) and saved on Enter.
- An option-list page kind can reuse `menu_list_render` with its own table, about 40 bytes
  more.

Estimated cost: about 270 bytes once, plus 40 for the relocated list, then about 45 per
value setting. `fix` modules export one `HOOK` today; `tools/patch/features.py` would have to
take several per fix.

Open points: other hard-coded page bounds may exist (`read_key`'s tail at 0x3DD6 is a known
trap); the encoder direction on value pages (stock swaps Up and Down on pages 7 and 8 only);
and it would be the first code here that writes EEPROM.
