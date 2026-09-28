#!/usr/bin/env python3
"""Unpack / repack the firmware container embedded in STC-ISP "release project" updaters
(e.g. SMSL_AO300_UPDATE_VER0A5_EN.exe).

The container lives in RT_RCDATA resource #1. It is obfuscated with a fixed-key byte
cipher (initial key 0x4C, 256-byte permutation table at VA 0x425BF0 in the updater).
Decrypted, it is "STC\\0" followed by TLV records:
    0x70, type, u16 checksum, u32 length, data
    checksum = -(0x70 + type + sum(length bytes) + sum(data)) & 0xFF
Record 0xFF holds the raw flash image (loaded at address 0x0000).

Usage:
    stc_release.py unpack UPDATER.exe OUTDIR
    stc_release.py repack UPDATER.exe NEW_FLASH.bin OUT_RESOURCE.bin
        (writes only the re-encrypted resource blob)
    stc_release.py rebuild UPDATER.exe NEW_FLASH.bin OUT_UPDATER.exe
        (writes a complete updater .exe carrying NEW_FLASH.bin)
"""
import os
import struct
import sys

import pefile

TABLE_VA = 0x425BF0
KEY0 = 0x4C


def load(exe):
    """Return (cipher table, RCDATA blob). The 256-byte permutation table moves between
    STC-ISP builds, so it is located by searching for a byte permutation that decrypts
    the blob to the 'STC\\0' magic (the fixed key 0x4C is common to all builds seen)."""
    pe = pefile.PE(exe)
    blob = None
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if t.id == pefile.RESOURCE_TYPE['RT_RCDATA']:
            leaf = t.directory.entries[0].directory.entries[0].data.struct
            blob = pe.get_data(leaf.OffsetToData, leaf.Size)
    if blob is None:
        raise SystemExit('no RCDATA resource found')
    data = pe.__data__
    try:
        table = pe.get_data(TABLE_VA - pe.OPTIONAL_HEADER.ImageBase, 256)
        if decrypt(table, blob[:4]) == b'STC\0':
            return table, blob
    except Exception:
        pass
    for off in range(0, len(data) - 256):
        table = data[off:off + 256]
        if len(set(table)) == 256 and decrypt(table, blob[:4]) == b'STC\0':
            return table, blob
    raise SystemExit('cipher table not found in this updater')


def decrypt(table, src):
    k1, k2, out = KEY0, 0, bytearray()
    for c in src:
        d = table[(((table[c] ^ table[k1]) + table[(k1 + 1) & 0xFF]) & 0xFF)]
        out.append(d)
        k1 = ((d ^ k1) + k2) & 0xFF
        k2 = (k2 + 1) & 0xFF
    return bytes(out)


def encrypt(table, pt):
    inv = [0] * 256
    for i, v in enumerate(table):
        inv[v] = i
    k1, k2, out = KEY0, 0, bytearray()
    for d in pt:
        out.append(inv[((inv[d] - table[(k1 + 1) & 0xFF]) & 0xFF) ^ table[k1]])
        k1 = ((d ^ k1) + k2) & 0xFF
        k2 = (k2 + 1) & 0xFF
    return bytes(out)


def records(plain):
    assert plain[:4] == b'STC\0', 'bad magic'
    i, recs = 4, []
    while i < len(plain) and plain[i] == 0x70:
        typ = plain[i + 1]
        ln = struct.unpack_from('<I', plain, i + 4)[0]
        recs.append((typ, plain[i + 8:i + 8 + ln]))
        i += 8 + ln
        if typ == 0:
            break
    return recs, plain[i:]


def build(recs, trailer):
    out = bytearray(b'STC\0')
    for typ, data in recs:
        lb = struct.pack('<I', len(data))
        ck = (-(0x70 + typ + sum(lb) + sum(data))) & 0xFF
        out += bytes([0x70, typ]) + struct.pack('<H', ck) + lb + data
    return bytes(out + trailer)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == 'unpack':
        table, blob = load(sys.argv[2])
        plain = decrypt(table, blob)
        os.makedirs(sys.argv[3], exist_ok=True)
        open(os.path.join(sys.argv[3], 'container.bin'), 'wb').write(plain)
        recs, _ = records(plain)
        for typ, data in recs:
            print('record 0x%02x  %6d bytes' % (typ, len(data)))
            if typ == 0xFF:
                open(os.path.join(sys.argv[3], 'flash.bin'), 'wb').write(data)
        assert encrypt(table, plain) == blob, 'round-trip failed'
        print('round-trip OK; flash image written to flash.bin')
    elif len(sys.argv) == 5 and sys.argv[1] == 'repack':
        table, blob = load(sys.argv[2])
        recs, trailer = records(decrypt(table, blob))
        new = open(sys.argv[3], 'rb').read()
        recs = [(t, new if t == 0xFF else d) for t, d in recs]
        open(sys.argv[4], 'wb').write(encrypt(table, build(recs, trailer)))
        print('wrote re-encrypted resource (%d bytes)' % (len(build(recs, trailer))))
    elif len(sys.argv) == 5 and sys.argv[1] == 'rebuild':
        table, blob = load(sys.argv[2])
        recs, trailer = records(decrypt(table, blob))
        new = open(sys.argv[3], 'rb').read()
        recs = [(t, new if t == 0xFF else d) for t, d in recs]
        rebuild_exe(sys.argv[2], encrypt(table, build(recs, trailer)), sys.argv[4])
    else:
        print(__doc__)


def rebuild_exe(src_exe, new_blob, dst_exe):
    """Write a copy of the updater whose RT_RCDATA #1 resource is new_blob.

    The blob is larger than the original, so it is placed at the end of the
    .rsrc section (the last section of the file) and the section, the resource
    data entry and the PE headers are grown to match.
    """
    pe = pefile.PE(src_exe)
    data = bytearray(pe.__data__)
    rsrc = [s for s in pe.sections if s.Name.rstrip(b'\0') == b'.rsrc'][0]
    assert rsrc is pe.sections[-1], '.rsrc must be the last section'
    assert pe.get_overlay_data_start_offset() is None, 'unexpected overlay data'

    leaf = None
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if t.id == pefile.RESOURCE_TYPE['RT_RCDATA']:
            leaf = t.directory.entries[0].directory.entries[0].data
    assert leaf is not None, 'no RCDATA resource'

    file_align = pe.OPTIONAL_HEADER.FileAlignment
    sect_align = pe.OPTIONAL_HEADER.SectionAlignment
    up = lambda v, a: (v + a - 1) // a * a

    # place the blob right after the current section contents, 16-byte aligned
    new_rva = up(rsrc.VirtualAddress + rsrc.Misc_VirtualSize, 16)
    new_off = rsrc.PointerToRawData + (new_rva - rsrc.VirtualAddress)
    end_rva = new_rva + len(new_blob)
    new_vsize = end_rva - rsrc.VirtualAddress
    new_rawsize = up(new_vsize, file_align)

    # extend file: zero-fill up to new_off, then blob, then pad to raw size
    file_end = rsrc.PointerToRawData + new_rawsize
    data = data[:rsrc.PointerToRawData + rsrc.SizeOfRawData]
    data += b'\0' * (file_end - len(data))
    data[new_off:new_off + len(new_blob)] = new_blob

    # patch resource data entry (RVA, size)
    struct.pack_into('<II', data, leaf.struct.get_file_offset(), new_rva, len(new_blob))
    # patch section header
    hdr = rsrc.get_file_offset()
    struct.pack_into('<I', data, hdr + 8, new_vsize)      # VirtualSize
    struct.pack_into('<I', data, hdr + 16, new_rawsize)   # SizeOfRawData
    # patch optional header: SizeOfImage, SizeOfInitializedData, resource dir size, checksum
    oh = pe.OPTIONAL_HEADER.get_file_offset()
    struct.pack_into('<I', data, oh + 8, pe.OPTIONAL_HEADER.SizeOfInitializedData
                     + (new_rawsize - rsrc.SizeOfRawData))
    struct.pack_into('<I', data, oh + 56, up(rsrc.VirtualAddress + new_vsize, sect_align))
    rd = pe.OPTIONAL_HEADER.DATA_DIRECTORY[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']]
    struct.pack_into('<I', data, rd.get_file_offset() + 4, new_vsize)
    struct.pack_into('<I', data, oh + 64, 0)              # CheckSum (recomputed below)

    out = pefile.PE(data=bytes(data))
    struct.pack_into('<I', data, oh + 64, out.generate_checksum())
    open(dst_exe, 'wb').write(data)
    print('wrote %s: resource moved to RVA 0x%X, %d bytes; file %d -> %d bytes'
          % (dst_exe, new_rva, len(new_blob), len(pe.__data__), len(data)))


if __name__ == '__main__':
    main()
