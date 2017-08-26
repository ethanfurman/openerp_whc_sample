from antipathy import Path as _Path
from xaml import Xaml as _Xaml

report_name = (_Path(__file__).path or _Path('.'))/'sample.xaml'
with open(report_name) as src:
    xaml_doc = _Xaml(src.read()).document

if len(xaml_doc.pages) != 2:
    raise ValueError('%s should have an xml and an xsl component' % report_name)

for page in xaml_doc.pages:
    with open(report_name.strip_ext() + '.' + page.ml.type, 'wb') as dst:
        dst.write(page.bytes())
