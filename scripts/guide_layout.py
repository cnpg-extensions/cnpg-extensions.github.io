"""Arrange imported quick-start instructions without duplicating their YAML."""
from bs4 import BeautifulSoup

def getting_started(html):
    soup=BeautifulSoup(html,'html.parser')
    for paragraph in soup.find_all('p'):
        if 'less than 24 hours' in paragraph.get_text(' ', strip=True):
            paragraph.clear()
            paragraph.string = 'New extension versions are automatically detected and rebuilt, typically appearing in the CNPG Extensions catalog in less than 30 minutes.'
            upstream = soup.new_tag('p')
            upstream.string = 'Signed containers built upstream by CloudNativePG are directly referenced by this catalog rather than being rebuilt. Updates to those containers (including core Postgres database patches) are reflected in this catalog within 24 hours.'
            paragraph.insert_after(upstream)
    steps=soup.find_all('h3',recursive=False)
    if len(steps)!=2:
        raise ValueError('Review quick-start layout: expected alerts and catalog maintenance sections')
    sections=[]
    for heading in steps:
        parts=[]
        for sibling in list(heading.next_siblings):
            if getattr(sibling,'name',None)=='h3':break
            parts.append(str(sibling))
        sections.append(''.join(parts))
    requirements=[]
    for node in soup.contents:
        if node==steps[0]:break
        requirements.append(str(node))
    return ( '<section class="guide-prerequisites">'+''.join(requirements)+'</section>'
        '<h2 id="configure-update-alerts">1. Set up alerts</h2>'
        '<p>Configure and test extension-update alerts before installing the catalog. Alerts remind you to run <code>ALTER EXTENSION … UPDATE</code> when needed.</p>'
        +sections[0]
        +'<h2 id="schedule-maintenance">2. Install the catalog with automatic updates</h2>'+sections[1])
