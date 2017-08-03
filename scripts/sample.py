from aenum import Enum

def split_label(label, errors=True):
    qty = []
    size = []
    text = []
    stage = Label.qty
    for ch in label:
        if stage is Label.qty:
            if ch.isdigit() or ch == '/':
                qty.append(ch)
            else:
                stage = Label.size
        if stage is Label.size and ch in ' -xX':
            continue
        if stage is Label.size:
            if ch.isdigit() or ch in './':
                size.append(ch)
            else:
                stage = Label.text
        if stage is Label.text:
            if ch == '.':
                ch = ' '
            text.append(ch)
    if not qty:
        qty = 1
    else:
        qty = ''.join(qty)
        if '/' not in qty:
            qty = int(''.join(qty))
            if qty > 1000:
                if errors:
                    return 'error: qty'
                qty = 1
    qty = str(qty)
    if not size:
        size = None
    else:
        size = ''.join(size)
        if '/' not in size and '.' not in size:
            size = int(''.join(size))
            if size > 1000:
                if errors:
                    return 'error: size'
                size = 1
        size = str(size)
    if qty == '1' and size is not None:
        qty, size = size, None
    # if size == '1':
    #     size = None
    if not text:
        if errors:
            return 'error: text'
        text = ['']
    else:
        words = ''.join(text).lower().split()
        text = []
        for w in words:
            if w in ('#', 'lb', 'lbs'):
                text.append('lb')
            elif w.startswith('ea'):
                text.append('ea')
            elif w in ('o', 'oz', 'ounce', 'ounces'):
                text.append('oz')
            elif w in ('cs', 'case', 'cases'):
                text.append('case')
            elif w in ('bg', 'bag', 'bags'):
                text.append('bag')
            elif 'p' in w and 'k' in w and 'g' in w:
                text.append('package')
            elif 's' in w and 'l' in w and 'v' in w:
                text.append('sleeve')
            else:
                text.append(w)
        if len(text) > 1 and text[-1] == 'ea':
            text.pop()
        if text[-1] not in ('ea', 'oz') and text[-1][-1] != 's':
            if (
                    (len(text) == 1 and qty != '1' and size != '1')
                    or (len(text) > 1 and qty and size)
                ):
                if text[-1][-1] in ('s', 'x', 'z', 'ch', 'sh'):
                    text[-1] = text[-1] + 'es'
                else:
                    text[-1] = text[-1] + 's'

    final = []
    if qty and size:
        final.extend([qty, '-', size])
    else:
        final.append(qty or size)
    final.extend(text)
    return ' '.join(final)


class Label(Enum):
    _order_ = 'qty size text'
    qty = 'qty'
    size = 'size'
    text = 'text'


