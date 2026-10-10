"""Format complete embedded controllers without changing or externalizing them."""
from pathlib import Path
import re
import jsbeautifier

path=Path('index.html')
source=path.read_text(encoding='utf-8')
options=jsbeautifier.default_options()
options.indent_size=2
options.preserve_newlines=True
scripts=[]
def script(match):
    scripts.append('<script>\n'+jsbeautifier.beautify(match.group(1),options)+'\n</script>')
    return f'<!--CONTROLLER-{len(scripts)-1}-->'
source=re.sub(r'<script>([\s\S]*?)</script>',script,source)
source=re.sub(r'>(?=<)', '>\n', source)
for i,block in enumerate(scripts):source=source.replace(f'<!--CONTROLLER-{i}-->',block)
path.write_text(source,encoding='utf-8')
print(f'Formatted all {len(scripts)} complete inline controllers.')
