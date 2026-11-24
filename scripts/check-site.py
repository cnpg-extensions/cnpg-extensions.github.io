#!/usr/bin/env python3
"""Check catalog completeness and local page/asset/report links after Hugo builds."""
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PageMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = set()
        self.links = []
        self.visible_views = []

    def handle_starttag(self, tag, attributes):
        if not attributes:
            return
        attrs = dict(attributes)
        if 'id' in attrs:
            self.anchors.add(attrs['id'] or '')
        link = attrs.get('href') or attrs.get('src')
        if link:
            self.links.append(link)
        if 'hidden' not in attrs and 'detail-view' in (attrs.get('class') or '').split():
            self.visible_views.append(attrs.get('id'))


def read_page(path):
    markup = PageMarkup()
    markup.feed(path.read_text())
    markup.close()
    return markup


def check_site(root):
    data = json.loads(Path('data/generated.json').read_text())
    assert data['extensions'], 'Empty catalog'
    prefix = '/cnpg-extensions-website/'
    errors = []
    checked = 0
    pages = {}
    anchors = {}
    for page in root.rglob('*.html'):
        markup = read_page(page)
        pages[page] = markup
        anchors[page.resolve()] = markup.anchors

    for page, markup in pages.items():
        for href in markup.links:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                continue
            if not url.path:
                if url.fragment and unquote(url.fragment) not in markup.anchors:
                    errors.append(f'{page}: missing anchor {href}')
                continue
            path = unquote(url.path)
            if path.startswith(prefix):
                target = root / path[len(prefix):]
            elif path.startswith('/'):
                target = root / path.lstrip('/')
            else:
                target = page.parent / path
            if target.is_dir():
                target = target / 'index.html'
            if not target.exists():
                errors.append(f'{page}: missing {href}')
            elif (url.fragment and target.suffix == '.html'
                  and unquote(url.fragment) not in anchors.get(target.resolve(), set())):
                errors.append(f'{page}: missing anchor {href}')
            checked += 1

    for extension in data['extensions']:
        extension_dir = root / 'extensions' / extension['name']
        assert (extension_dir / 'index.html').exists(), extension['name']
        for view in ('overview', 'documentation', 'dependencies', 'licenses', 'versions'):
            tab_page = extension_dir / view / 'index.html'
            assert tab_page.exists(), tab_page
            markup = pages.get(tab_page)
            if markup is None:
                markup = read_page(tab_page)
            assert markup.visible_views == [view], tab_page

        for variant in extension['variants']:
            for platform in variant['platforms']:
                if platform['status'] == 'available':
                    sbom = json.loads((root / platform['sbom']).read_text())
                    assert len(sbom.get('packages', [])) == len(platform['packages'])
                    scan = platform.get('scan', {})
                    if scan.get('status') == 'scanned':
                        assert (root / scan['report']).exists()

    if errors:
        raise SystemExit('\n'.join(errors[:40]))
    print(f'Validated {data["count"]} extension pages, SBOM package completeness, and {checked} local links.')


if __name__ == '__main__':
    check_site(Path(sys.argv[1] if len(sys.argv) > 1 else 'public'))
