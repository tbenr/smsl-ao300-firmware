"""Minimal 8051 recursive-descent disassembler."""
import sys

SFR = {0x80:'P0',0x81:'SP',0x82:'DPL',0x83:'DPH',0x87:'PCON',0x88:'TCON',0x89:'TMOD',0x8a:'TL0',0x8b:'TL1',
       0x8c:'TH0',0x8d:'TH1',0x8e:'AUXR',0x90:'P1',0x98:'SCON',0x99:'SBUF',0xa0:'P2',0xa8:'IE',0xb0:'P3',
       0xb8:'IP',0xd0:'PSW',0xe0:'ACC',0xf0:'B',0xc8:'T2CON',0xa2:'P_SW1',0xba:'P_SW2',0xc0:'P4',0xc2:'IAP_DATA',
       0xc3:'IAP_ADDRH',0xc5:'IAP_CMD',0xc6:'IAP_TRIG',0xc7:'IAP_CONTR',0xc4:'IAP_ADDRL',0xaf:'IE2',0x8f:'INTCLKO',
       0xd6:'T2H',0xd7:'T2L',0xd4:'T3H',0xd5:'T3L',0xd2:'T4H',0xd3:'T4L',0xd1:'T4T3M',0x9a:'S2CON',0x9b:'S2BUF',
       0xbc:'ADC_CONTR',0xbd:'ADC_RES',0xbe:'ADC_RESL',0xdc:'ADCCFG',0x93:'P1M1',0x94:'P1M0',0x95:'P0M1',0x96:'P0M0',
       0x91:'P1M1?',0x92:'P1M0?',0xb1:'P3M1',0xb2:'P3M0',0xb3:'P4M1',0xb4:'P4M0',0xc9:'P5M1',0xca:'P5M0',0xc8:'P5',
       0xe8:'P6',0xf8:'P7',0x97:'DPS?',0xb5:'IP2H',0xb6:'IP2',0xb7:'IPH',0xf1:'PWMSET?',0xa1:'BUS_SPEED',0x8e:'AUXR',
       0xd8:'CCON',0xd9:'CMOD',0xda:'CCAPM0',0xdb:'CCAPM1',0xe9:'CL',0xf9:'CH',0xea:'CCAP0L',0xfa:'CCAP0H'}
BITS = {0x88:'TCON',0x98:'SCON',0xa8:'IE',0xb8:'IP',0xd0:'PSW',0xe0:'ACC',0xf0:'B',0x80:'P0',0x90:'P1',0xa0:'P2',0xb0:'P3',0xc0:'P4',0xc8:'P5',0xd8:'CCON',0xe8:'P6',0xf8:'P7'}
BITNAMES = {0x88:'IT0',0x89:'IE0',0x8a:'IT1',0x8b:'IE1',0x8c:'TR0',0x8d:'TF0',0x8e:'TR1',0x8f:'TF1',
            0x98:'RI',0x99:'TI',0xa8:'EX0',0xa9:'ET0',0xaa:'EX1',0xab:'ET1',0xac:'ES',0xaf:'EA',
            0xd7:'CY',0xd0:'P',0xd2:'OV',0xd3:'RS0',0xd4:'RS1',0xd5:'F0'}

def d(a): return SFR.get(a, '0x%02x' % a) if a >= 0x80 else '0x%02x' % a
def b(a):
    if a in BITNAMES: return BITNAMES[a]
    if a < 0x80: return '0x%02x.%d' % (0x20 + a // 8, a % 8)
    base = a & 0xf8
    return '%s.%d' % (BITS.get(base, '0x%02x' % base), a & 7)

def decode(code, pc):
    op = code[pc]
    g = lambda i: code[pc + i] if pc + i < len(code) else 0
    rel = lambda i, ln: (pc + ln + ((g(i) ^ 0x80) - 0x80)) & 0xffff
    lo = op & 0x0f; hi = op >> 4
    rn = 'R%d' % (op & 7); ri = '@R%d' % (op & 1)
    # returns (length, text, targets, flow) flow: 'n' normal,'j' jump,'c' call,'r' ret,'b' branch
    if lo == 1:
        addr = ((pc + 2) & 0xf800) | ((op & 0xe0) << 3) | g(1)
        return (2, ('ajmp' if not (op & 0x10) else 'acall') + ' 0x%04x' % addr, [addr], 'j' if not (op & 0x10) else 'c')
    if op >= 0x06 and lo >= 6:
        opnd = ri if lo < 8 else rn
        if lo in (6, 7) or lo >= 8:
            t = {0: ('inc %s', 1), 1: ('dec %s', 1), 2: ('add A, %s', 1), 3: ('addc A, %s', 1), 4: ('orl A, %s', 1),
                 5: ('anl A, %s', 1), 6: ('xrl A, %s', 1), 7: ('mov %s, #0x%02x', 2), 8: ('mov 0x%02x, %s', 2),
                 9: ('subb A, %s', 1), 0xa: ('mov %s, 0x%02x', 2), 0xb: ('cjne %s, #0x%02x, 0x%04x', 3),
                 0xc: ('xch A, %s', 1), 0xd: ('djnz %s, 0x%04x', 2), 0xe: ('mov A, %s', 1), 0xf: ('mov %s, A', 1)}[hi]
            fmt, ln = t
            if hi == 7: return (2, fmt % (opnd, g(1)), [], 'n')
            if hi == 8: return (2, 'mov %s, %s' % (d(g(1)), opnd), [], 'n')
            if hi == 0xa: return (2, 'mov %s, %s' % (opnd, d(g(1))), [], 'n')
            if hi == 0xb: return (3, fmt % (opnd, g(1), rel(2, 3)), [rel(2, 3)], 'b')
            if hi == 0xd:
                if lo < 8: return (2, 'xchd A, %s' % opnd, [], 'n')
                return (2, fmt % (opnd, rel(1, 2)), [rel(1, 2)], 'b')
            return (1, fmt % opnd, [], 'n')
    T = {
        0x00: (1, 'nop'), 0x02: (3, 'ljmp'), 0x03: (1, 'rr A'), 0x04: (1, 'inc A'), 0x05: (2, 'inc D'),
        0x10: (3, 'jbc'), 0x12: (3, 'lcall'), 0x13: (1, 'rrc A'), 0x14: (1, 'dec A'), 0x15: (2, 'dec D'),
        0x20: (3, 'jb'), 0x22: (1, 'ret'), 0x23: (1, 'rl A'), 0x24: (2, 'add A, #I'), 0x25: (2, 'add A, D'),
        0x30: (3, 'jnb'), 0x32: (1, 'reti'), 0x33: (1, 'rlc A'), 0x34: (2, 'addc A, #I'), 0x35: (2, 'addc A, D'),
        0x40: (2, 'jc'), 0x42: (2, 'orl D, A'), 0x43: (3, 'orl D, #I'), 0x44: (2, 'orl A, #I'), 0x45: (2, 'orl A, D'),
        0x50: (2, 'jnc'), 0x52: (2, 'anl D, A'), 0x53: (3, 'anl D, #I'), 0x54: (2, 'anl A, #I'), 0x55: (2, 'anl A, D'),
        0x60: (2, 'jz'), 0x62: (2, 'xrl D, A'), 0x63: (3, 'xrl D, #I'), 0x64: (2, 'xrl A, #I'), 0x65: (2, 'xrl A, D'),
        0x70: (2, 'jnz'), 0x72: (2, 'orl C, B'), 0x73: (1, 'jmp @A+DPTR'), 0x74: (2, 'mov A, #I'), 0x75: (3, 'mov D, #I'),
        0x80: (2, 'sjmp'), 0x82: (2, 'anl C, B'), 0x83: (1, 'movc A, @A+PC'), 0x84: (1, 'div AB'), 0x85: (3, 'mov D2, D1'),
        0x90: (3, 'mov DPTR, #W'), 0x92: (2, 'mov B, C'), 0x93: (1, 'movc A, @A+DPTR'), 0x94: (2, 'subb A, #I'), 0x95: (2, 'subb A, D'),
        0xa0: (2, 'orl C, /B'), 0xa2: (2, 'mov C, B'), 0xa3: (1, 'inc DPTR'), 0xa4: (1, 'mul AB'), 0xa5: (1, 'db 0xa5'),
        0xb0: (2, 'anl C, /B'), 0xb2: (2, 'cpl B'), 0xb3: (1, 'cpl C'), 0xb4: (3, 'cjne A, #I, R'), 0xb5: (3, 'cjne A, D, R'),
        0xc0: (2, 'push D'), 0xc2: (2, 'clr B'), 0xc3: (1, 'clr C'), 0xc4: (1, 'swap A'), 0xc5: (2, 'xch A, D'),
        0xd0: (2, 'pop D'), 0xd2: (2, 'setb B'), 0xd3: (1, 'setb C'), 0xd4: (1, 'da A'), 0xd5: (3, 'djnz D, R'),
        0xe0: (1, 'movx A, @DPTR'), 0xe2: (1, 'movx A, @R0'), 0xe3: (1, 'movx A, @R1'), 0xe4: (1, 'clr A'), 0xe5: (2, 'mov A, D'),
        0xf0: (1, 'movx @DPTR, A'), 0xf2: (1, 'movx @R0, A'), 0xf3: (1, 'movx @R1, A'), 0xf4: (1, 'cpl A'), 0xf5: (2, 'mov D, A'),
    }
    ln, fmt = T[op]
    if op == 0x02: t = (g(1) << 8) | g(2); return (3, 'ljmp 0x%04x' % t, [t], 'j')
    if op == 0x12: t = (g(1) << 8) | g(2); return (3, 'lcall 0x%04x' % t, [t], 'c')
    if op in (0x10, 0x20, 0x30): t = rel(2, 3); return (3, '%s %s, 0x%04x' % (fmt, b(g(1)), t), [t], 'b')
    if op in (0x40, 0x50, 0x60, 0x70): t = rel(1, 2); return (2, '%s 0x%04x' % (fmt, t), [t], 'b')
    if op == 0x80: t = rel(1, 2); return (2, 'sjmp 0x%04x' % t, [t], 'j')
    if op == 0x22 or op == 0x32: return (1, fmt, [], 'r')
    if op == 0x73: return (1, fmt, [], 'r')
    if op == 0x90: return (3, 'mov DPTR, #0x%04x' % ((g(1) << 8) | g(2)), [], 'n')
    if op == 0x85: return (3, 'mov %s, %s' % (d(g(2)), d(g(1))), [], 'n')
    if op == 0xb4: t = rel(2, 3); return (3, 'cjne A, #0x%02x, 0x%04x' % (g(1), t), [t], 'b')
    if op == 0xb5: t = rel(2, 3); return (3, 'cjne A, %s, 0x%04x' % (d(g(1)), t), [t], 'b')
    if op == 0xd5: t = rel(2, 3); return (3, 'djnz %s, 0x%04x' % (d(g(1)), t), [t], 'b')
    s = fmt
    if op in (0x43, 0x53, 0x63, 0x75): return (3, s.replace('D', d(g(1))).replace('#I', '#0x%02x' % g(2)), [], 'n')
    s = s.replace('#I', '#0x%02x' % g(1))
    if 'B' in s and op in (0x72, 0x82, 0x92, 0xa0, 0xa2, 0xb0, 0xb2, 0xc2, 0xd2): s = s.replace('/B', '/' + b(g(1))).replace(' B', ' ' + b(g(1)))
    s = s.replace(' D', ' ' + d(g(1))) if op not in (0x84, 0xa4, 0xa3) else s
    return (ln, s, [], 'n')

def disasm(code, entries):
    seen = {}; todo = list(entries); calls = set()
    while todo:
        pc = todo.pop()
        while 0 <= pc < len(code) and pc not in seen:
            ln, txt, tg, fl = decode(code, pc)
            seen[pc] = (ln, txt, tg)
            for t in tg:
                if fl == 'c': calls.add(t)
                todo.append(t)
            if fl in ('j', 'r'): break
            pc += ln
    return seen, calls

if __name__ == '__main__':
    code = open(sys.argv[1], 'rb').read()
    entries = [0] + [3 + 8 * i for i in range(32) if code[3 + 8 * i] == 0x02]; print("vectors", [(hex(v), hex((code[v+1]<<8)|code[v+2])) for v in entries[1:]])
    entries += [int(x, 16) for x in sys.argv[3:]]
    seen, calls = disasm(code, entries)
    labels = set()
    for pc, (ln, txt, tg) in seen.items(): labels.update(tg)
    with open(sys.argv[2], 'w') as f:
        prev = None
        for pc in sorted(seen):
            ln, txt, tg = seen[pc]
            if prev is not None and pc != prev: f.write('\n')
            if pc in calls: f.write('\nfunc_%04x:\n' % pc)
            elif pc in labels: f.write('L_%04x:\n' % pc)
            f.write('  %04x: %-10s %s\n' % (pc, code[pc:pc + ln].hex(), txt))
            prev = pc + ln
    print('covered bytes', sum(v[0] for v in seen.values()), 'of', len(code), 'functions', len(calls))
