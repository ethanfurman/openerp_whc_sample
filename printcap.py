from aenum import Constant

class k(Constant):
    START = 0x01
    END = 0x00
START, END = k.START, k.END

class Printer(object):

    def cr(self):
        return '\x0d'.encode('latin-1')

    def ff(self):
        return '\x0c'.encode('latin-1')

    def lf(self):
        return '\x0a'.encode('latin-1')

    def font(self, quality, font, cpi):
        'courier, roman, etc'
        return getattr(self, quality)() + getattr(self, font)() + self.cpi(cpi)

    def form(self, lpi, lines):
        return self.lpi(lpi) + self.form_length_lines(lines)

    def justify(self, just):
        return getattr(self, '%s_justification' % just)()

    def margins(self, left, right):
        return self.left_margin(left) + self.right_margin(right)

    def quality(self, q):
        "lq, nlq, draft"
        return getattr(self, q)()

    def style(self, style, phase=START):
        if phase not in (START, END):
            raise ValueError('unknown value for phase: %r' % (phase, ))
        return getattr(self, style)(phase)

    def transform(self, string):
        in_code = False
        in_backslash = False
        result = []
        code = []
        for ch in string:
            if in_backslash:
                result.append(ch)
                in_backslash = False
            elif ch == '\\':
                in_backslash = True
            elif ch == '{':
                in_code = True
            elif ch == '}':
                in_code = False
                func_name = ''.join(code)
                phase = None
                params = None
                if func_name.startswith('/'):
                    phase = END
                    func_name = func_name[1:]
                if ':' in func_name:
                    func_name, params = func_name.split(':', 1)
                    if ',' in params:
                        params = tuple(params.split(','))
                    else:
                        params = (params, )
                func = getattr(self, func_name)
                if phase is END:
                    result.append(func(phase))
                elif params:
                    result.append(func(*params))
                else:
                    result.append(func())
                code = []
            elif in_code:
                code.append(ch)
            else:
                result.append(ch)
        return ''.join(result)

class Oki380(Printer):

    def reset(self):
        return esc(0x40)

    def lq(self):
        return esc(0x78, 0x31)

    def nlq(self):
        return esc(0x78, 0x31)

    def draft(self):
        return esc(0x78, 0x30)

    def roman(self):
        return esc(0x6b, 0x30)

    def swiss(self):
        return esc(0x6b, 0x31)

    def courier(self):
        return esc(0x6b, 0x32)

    def bold(self, phase=START):
        if phase not in (START, END):
            raise ValueError('unknown value for phase: %r' % (phase, ))
        return (esc(0x46), esc(0x45))[phase]

    def italic(self, phase=START):
        if phase not in (START, END):
            raise ValueError('unknown value for phase: %r' % (phase, ))
        return (esc(0x35), esc(0x34))[phase]

    def underline(self, phase=START):
        if phase not in (START, END):
            raise ValueError('unknown value for phase: %r' % (phase, ))
        return (esc(0x2d, 0x00), esc(0x2d, 0x01))[phase]

    def proportional(self, phase=START):
        if phase not in (START, END):
            raise ValueError('unknown value for phase: %r' % (phase, ))
        return (esc(0x70, 0x00), esc(0x70, 0x01))[phase]

    def cpi(self, cpi):
        return {
                10: esc(0x50),
                12: esc(0x4d),
                15: esc(0x67),
                }[int(cpi)]

    def lpi(self, lpi):
        return {
                6: esc(0x32),
                8: esc(0x30),
                }[int(lpi)]

    def form_length_inches(self, inches):
        return esc(0x43, 0x00, int(inches))

    def form_length_lines(self, lines):
        return esc(0x43, int(lines))

    def left_margin(self, chars):
        return esc(0x6c, int(chars))

    def right_margin(self, chars):
        return esc(0x51, int(chars))

    def left_justification(self):
        return esc(0x61, 0x30)

    def center_justification(self):
        return esc(0x61, 0x31)

    def right_justification(self):
        return esc(0x61, 0x32)

    def full_justification(self):
        return esc(0x61, 0x33)


def esc(*codes):
    codes = (0x1b, ) + codes
    return ''.join([chr(c) for c in codes]).encode('latin-1')



if __name__ == '__main__':
    init = "{reset}{font:nlq,courier,10}{form:6,18}{margins:2,28}Howdy!{ff}"
    data = Oki380().transform(init)
    should_be = ''.join([chr(i) for i in (
            0x1b, 0x40,
            0x1b, 0x78, 0x31,
            0x1b, 0x6b, 0x32,
            0x1b, 0x50,
            0x1b, 0x32,
            0x1b, 0x43, 18,
            0x1b, 0x6c, 2,
            0x1b, 0x51, 28,
            0x48, 0x6f, 0x77, 0x64, 0x79, 0x21,
            0x0c,
            )]).encode('latin-1')
    print repr(data)
    print repr(should_be)
    assert data == should_be
    for i, ch in enumerate(data):
        if i % 8 == 0:
            print
        print hex(ord(ch))[2:],
