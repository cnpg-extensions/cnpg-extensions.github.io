#!/usr/bin/env python3
"""Check catalog completeness and local page/asset/report links after Hugo builds."""
import json,sys
from pathlib import Path
from urllib.parse import urlsplit,unquote
from bs4 import BeautifulSoup
root=Path(sys.argv[1] if len(sys.argv)>1 else 'public')
data=json.loads(Path('data/generated.json').read_text())
assert data['extensions'], 'Empty catalog'
prefix='/cnpg-extensions-website/'
errors=[];checked=0;anchors={}
for page in root.rglob("*.html"):
    anchors[page.resolve()]={tag.get("id") for tag in BeautifulSoup(page.read_text(),"html.parser").select("[id]")}
for page in root.rglob('*.html'):
    soup=BeautifulSoup(page.read_text(),'html.parser')
    for tag in soup.select('[href], [src]'):
        href=tag.get('href') or tag.get('src');url=urlsplit(href)
        if url.scheme or url.netloc:continue
        if not url.path:
            if url.fragment and unquote(url.fragment) not in anchors[page.resolve()]:errors.append(f'{page}: missing anchor {href}')
            continue
        path=unquote(url.path)
        if path.startswith(prefix):target=root/path[len(prefix):]
        elif path.startswith('/'):target=root/path.lstrip('/')
        else:target=page.parent/path
        if target.is_dir():target=target/'index.html'
        if not target.exists():errors.append(f'{page}: missing {href}')
        elif url.fragment and target.suffix=='.html' and unquote(url.fragment) not in anchors.get(target.resolve(),set()):errors.append(f'{page}: missing anchor {href}')
        checked+=1
for e in data['extensions']:
    assert (root/'extensions'/e['name']/'index.html').exists(),e['name']
    for view in ('overview', 'documentation', 'dependencies', 'licenses'):
        tab_page = root/'extensions'/e['name']/view/'index.html'
        assert tab_page.exists(), tab_page
        tab_soup = BeautifulSoup(tab_page.read_text(), 'html.parser')
        visible = tab_soup.select('.detail-view:not([hidden])')
        assert [section['id'] for section in visible] == [view], tab_page

    for v in e['variants']:
        for p in v['platforms']:
            if p['status']=='available':
                sbom=json.loads((root/p['sbom']).read_text());assert len(sbom.get('packages',[]))==len(p['packages'])
                scan=p.get('scan',{})
                if scan.get('status')=='scanned':assert (root/scan['report']).exists()
if errors:raise SystemExit('\n'.join(errors[:40]))
print(f'Validated {data["count"]} extension pages, SBOM package completeness, and {checked} local links.')
