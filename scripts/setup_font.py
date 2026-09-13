from pathlib import Path
from urllib.request import urlretrieve
root = Path(__file__).resolve().parent.parent / 'assets'
root.mkdir(exist_ok=True)
for name, url in {
    'LXGWWenKai-Regular.ttf': 'https://github.com/lxgw/LxgwWenKai/raw/main/fonts/TTF/LXGWWenKai-Regular.ttf',
    'OFL.txt': 'https://raw.githubusercontent.com/lxgw/LxgwWenKai/main/OFL.txt',
}.items():
    dest = root / name
    if not dest.exists():
        print(f'Downloading {name} ...', flush=True)
        temp = dest.with_suffix('.download')
        urlretrieve(url, temp)
        temp.replace(dest)
print('Font ready.')
