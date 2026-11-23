#!/usr/bin/env python3
"""Build the catalog from published catalogs, source READMEs, and digest-bound SPDX.
No per-extension editorial data. Network failures are explicit, never zero findings.
"""
import argparse, concurrent.futures, hashlib, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from collections import Counter
from build_timing import timed, phase
from evidence_shards import database_identity, merge_shards, shard_path
from source_commits import REPOS
from scorecard_repositories import publisher_for
from image_notices import container_notices
from osv_scan import scan_osv_batch, refresh_database
from guide_layout import getting_started
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs, unquote, quote
import requests, yaml, markdown
from catalog_recipes import find_recipe, recipe_index
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache'
REPORTS = ROOT / 'static/reports'
NOW = datetime.now(timezone.utc).isoformat(timespec='seconds')

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def source_refresh_time(refreshed, commits, previous, now):
    if refreshed:
        return now
    if previous.get('commits') == commits:
        return previous.get('refreshedAt')
    return None

@timed("checkout")
def checkout(name, refresh):
    path = CACHE/name
    if 'CATALOG_SOURCE_COMMITS' in os.environ:
        commit = json.loads(os.environ['CATALOG_SOURCE_COMMITS'])[name]
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError(f'Invalid pinned source commit for {name}')
        url = f'https://github.com/{REPOS[name]}.git'
        subprocess.run(['git', 'init', '--quiet', str(path)], check=True)
        subprocess.run(['git', '-C', str(path), 'fetch', '--depth', '1', url, commit], check=True)
        subprocess.run(['git', '-C', str(path), 'checkout', '--detach', commit], check=True)
    elif not (path/'.git').exists():
        subprocess.run(['git','clone','--depth','1',f'https://github.com/{REPOS[name]}.git',str(path)],check=True)
    elif refresh:
        subprocess.run(['git','-C',str(path),'fetch','--depth','1','origin','main'],check=True)
        subprocess.run(['git','-C',str(path),'checkout','--detach','FETCH_HEAD'],check=True)
    return run('git','-C',str(path),'rev-parse','HEAD')

def advisory_url(package):
    purl=next((r.get('referenceLocator','') for r in package.get('externalRefs',[]) if r.get('referenceType')=='purl'),'')
    if not purl.startswith('pkg:'): return ''
    identity, _, query=purl[4:].partition('?')
    kind, _, coordinate=identity.partition('/')
    name, sep, version=coordinate.rpartition('@')
    if not sep: return ''
    qualifiers=parse_qs(query)
    if kind=='cargo' and not qualifiers.get('repository_url'):
        return 'https://deps.dev/cargo/'+quote(unquote(name),safe='')+'/'+quote(unquote(version),safe='')
    if kind=='deb' and name.startswith('debian/'):
        # Debian omits Source when source and binary names/versions match.
        source=(qualifiers.get('upstream',[''])[0] or unquote(name.split('/',1)[1])).split('@',1)[0]
        if source: return 'https://security-tracker.debian.org/tracker/source-package/'+quote(source,safe='')
    return ''

def crate_url(package):
    """Link crates.io identities using the installed version from SPDX."""
    for ref in package.get('externalRefs', []):
        if ref.get('referenceType') != 'purl':
            continue
        identity, _, query = ref.get('referenceLocator', '').partition('?')
        if not identity.startswith('pkg:cargo/') or parse_qs(query).get('repository_url'):
            continue
        name, sep, version = identity.removeprefix('pkg:cargo/').rpartition('@')
        if sep and name and version:
            return 'https://crates.io/crates/' + quote(unquote(name), safe='') + '/' + quote(unquote(version), safe='')
    return ''

def image_package_url(reference):
    """Use the catalog image repository rather than the extension recipe name."""
    if not reference.startswith('ghcr.io/'):
        return ''
    repository = reference.removeprefix('ghcr.io/').split('@', 1)[0].split(':', 1)[0]
    owner, sep, name = repository.partition('/')
    if not owner or not sep or not name:
        return ''
    return 'https://github.com/orgs/' + quote(owner, safe='') + '/packages/container/package/' + quote(name, safe='')

def package_ecosystem(package):
    for ref in package.get('externalRefs', []):
        if ref.get('referenceType') == 'purl':
            purl = ref.get('referenceLocator', '')
            if purl.startswith('pkg:'):
                return purl[4:].split('/', 1)[0]
    return ''

def packages(spdx):
    # Preserve both SPDX fields and all expressions; never split AND/OR into a claim of alternatives.
    return sorted([{'name':p['name'],'version':p.get('versionInfo','Not recorded'),
                    'declared':p.get('licenseDeclared','NOASSERTION'),
                    'concluded':p.get('licenseConcluded','NOASSERTION'),
                    'files':p.get('licenseInfoFromFiles',[]),'ecosystem':package_ecosystem(p),'packageURL':crate_url(p),'advisoryURL':advisory_url(p)} for p in spdx.get('packages',[])],key=lambda p:(p['name'],p['version']))

def notice_files(spdx):
    """Find notice paths in the shipped-file inventory, not embedded license records."""
    paths=set()
    for item in spdx.get('files',[]):
        path=item.get('fileName','').removeprefix('./').lstrip('/')
        parts=path.lower().split('/')
        if not path or '..' in parts or 'DIRECTORY' in item.get('fileTypes',[]):
            continue
        if parts[0]=='licenses' or parts[:3]==['usr','share','licenses'] or (
            parts[:3]==['usr','share','doc'] and re.match(r'^(copyright|copying|licen[cs]e|notice)([.\-]|$)',parts[-1])):
            paths.add('/'+path)
    return sorted(paths)

def check_digest(data, digest):
    if not digest.startswith('sha256:') or hashlib.sha256(data).hexdigest()!=digest[7:]:
        raise ValueError('Registry content does not match catalog/descriptor digest')

class Registry:
    def __init__(self, ref, refresh=False):
        self.refresh = refresh
        host, rest=ref.split('/',1)
        if host!='ghcr.io': raise ValueError('Unsupported registry: '+host)
        named,self.digest=rest.split('@')
        self.repo=named.split(':')[0]
        self.base=f'https://ghcr.io/v2/{self.repo}/'
        self.session=requests.Session()
        self.session.mount('https://',HTTPAdapter(max_retries=Retry(total=3,backoff_factor=1,status_forcelist=[429,500,502,503,504])))
        r=self.session.get('https://ghcr.io/token',params={'service':'ghcr.io','scope':f'repository:{self.repo}:pull'},timeout=60)
        r.raise_for_status()
        self.session.headers.update({'Authorization':'Bearer '+r.json()['token'], 'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json'})
    @timed("registry asset")
    def get(self,digest,kind='manifests'):
        dest=CACHE/'oci'/digest.replace(':','-')
        if dest.exists() and not self.refresh: data=dest.read_bytes()
        else:
            r=self.session.get(self.base+kind+'/'+digest,timeout=120);r.raise_for_status();data=r.content
            check_digest(data,digest)
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        check_digest(data,digest)
        return json.loads(data)

@timed("scan")
def scan(sbom, grype, database):
    if not grype: return {'status':'not-run','reason':'Vulnerability scanning was not requested.'}
    if database.get('error'): return {'status':'unavailable','reason':database['error']}
    env={**os.environ,'GRYPE_DB_AUTO_UPDATE':'false'}
    result=subprocess.run([grype,'sbom:'+str(sbom),'-o','json'],capture_output=True,text=True,env=env,timeout=600)
    if result.returncode: raise RuntimeError('Grype scan failed: '+result.stderr[-400:])
    raw=json.loads(result.stdout)
    dest=sbom.with_suffix('.grype.json');dest.write_text(result.stdout)
    findings={}
    for m in raw.get('matches',[]):
        v=m['vulnerability']; a=m['artifact']
        k=(v['id'],a['name'],a.get('version',''))
        findings[k]={'id':v['id'],'package':a['name'],'version':a.get('version',''),'severity':v.get('severity','Unknown'),
                     'url':v.get('dataSource',''),'fix':v.get('fix',{}),'namespace':v.get('namespace','')}
    return {'status':'scanned','scannedAt':datetime.now(timezone.utc).isoformat(timespec='seconds'),'database':database,'scanner':raw.get('descriptor',{}).get('version',''),
            'findings':sorted(findings.values(),key=lambda v:(v['severity'],v['id'],v['package'])),
            'report':str(dest.relative_to(ROOT/'static'))}

@timed("inspect_image")
def inspect_image(item, grype, database, refresh=False):
    result={**item,'platforms':[]}
    try:
        reg=Registry(item['reference'], refresh=refresh);index=reg.get(reg.digest)
        result['annotations']=index.get('annotations',{})
        manifests=index.get('manifests',[])
        platforms=[m for m in manifests if m.get('platform',{}).get('os')=='linux' and m.get('platform',{}).get('architecture') in ['amd64','arm64']]
        if not platforms: raise ValueError('No supported platform manifests in published index')
        for platform in platforms:
            arch=platform['platform']['architecture'];pd=platform['digest']
            record={'architecture':arch,'digest':pd,'status':'unavailable'}
            try:
                manifest=reg.get(pd);config=reg.get(manifest['config']['digest'],'blobs')
                record['labels']=config.get('config',{}).get('Labels',{}) or {}
                att=next((m for m in manifests if m.get('annotations',{}).get('vnd.docker.reference.digest')==pd and m.get('annotations',{}).get('vnd.docker.reference.type')=='attestation-manifest'),None)
                if not att: raise ValueError('SBOM not published for this architecture')
                am=reg.get(att['digest']);spdx=None
                for layer in am.get('layers',[]):
                    if layer.get('annotations',{}).get('in-toto.io/predicate-type')=='https://spdx.dev/Document':
                        statement=reg.get(layer['digest'],'blobs')
                        if statement.get('predicateType')!='https://spdx.dev/Document': raise ValueError('Unexpected SBOM predicate type')
                        if not any(s.get('digest',{}).get('sha256')==pd[7:] for s in statement.get('subject',[])): raise ValueError('SBOM subject does not match platform manifest')
                        spdx=statement['predicate'];break
                if not spdx or not spdx.get('spdxVersion','').startswith('SPDX-'): raise ValueError('SPDX SBOM not published for this architecture')
                dest=REPORTS/item['name']/f"{item['distro']}-pg{item['pg']}-{arch}.spdx.json"
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(spdx))
                record.update(status='available',packages=packages(spdx),licenses=spdx.get('hasExtractedLicensingInfos',[]),sbom=str(dest.relative_to(ROOT/'static')))
                try: record['scan']=scan(dest,grype,database)
                except Exception as ex: record['scan']={'status':'unavailable','reason':str(ex)}
            except Exception as ex: record['reason']=str(ex)
            result['platforms'].append(record)
        result['status']='available'
        result['version']=result['annotations'].get('org.opencontainers.image.version') or next((p.get('labels',{}).get('org.opencontainers.image.version') for p in result['platforms'] if p.get('labels',{}).get('org.opencontainers.image.version')), 'Not recorded')
    except Exception as ex: result.update(status='unavailable',reason=str(ex),version='Unavailable')
    return result

@timed("readme_html")
def readme_html(text, repo, commit, path, routes, depth=2):
    html=markdown.markdown(text,extensions=['fenced_code','tables','toc'])
    soup=BeautifulSoup(html,'html.parser')
    # GitHub alert markers are not part of Python Markdown's blockquote syntax.
    for quote in soup.find_all('blockquote'):
        first=quote.find('p',recursive=False)
        if not first or not first.contents or not isinstance(first.contents[0],str):
            continue
        match=re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:[ \t]*\n|[ \t]*$)',str(first.contents[0]))
        if not match:
            continue
        kind=match.group(1)
        first.contents[0].replace_with(str(first.contents[0])[match.end():])
        if not first.get_text(strip=True) and not first.find():
            first.decompose()
        quote['class']=['github-alert','github-alert-'+kind.lower()]
        title=soup.new_tag('p',attrs={'class':'github-alert-title'})
        icon=soup.new_tag('span',attrs={'class':'github-alert-icon','aria-hidden':'true'})
        title.append(icon);title.append(' '+kind.title())
        quote.insert(0,title)
    for a in soup.find_all(['a','img']):
        key='href' if a.name=='a' else 'src'; link=a.get(key,'')
        if not link:continue
        if link.startswith('#'):
            if path=='README.md' and link=='#supported-extensions': a[key]='../'*depth+'extensions/'
            continue
        absolute=urljoin(f'https://github.com/{repo}/blob/{commit}/{path}',link)
        if not urlsplit(link).scheme:
            target=absolute.split('#')[0].split(f'/blob/{commit}/')[-1]
            if a.name=='img': absolute=urljoin(f'https://raw.githubusercontent.com/{repo}/{commit}/{path}',link)
            elif (repo,target) in routes: absolute='../'*depth+routes[(repo,target)]+('/#'+link.split('#',1)[1] if '#' in link else '/')
            if a.name=='a' and target=='README.md' and '#quick-start' in link: absolute='../'*depth+'get-started/'
            if a.name=='a' and target=='README.md' and '#supported-extensions' in link: absolute='../'*depth+'extensions/'
        a[key]=absolute
        if a.name=='a' and urlsplit(absolute).scheme in ('http','https') and urlsplit(absolute).netloc != 'cnpg-extensions.github.io':
            a['target']='_blank'
            a['rel']='noopener noreferrer'
    # Source Markdown is content, not executable page code.
    import bleach
    tags={'a','p','div','span','h1','h2','h3','h4','h5','h6','ul','ol','li','pre','code','strong','em','blockquote','table','thead','tbody','tr','th','td','hr','br','img','details','summary','del','sup','sub'}
    return bleach.clean(str(soup),tags=tags,attributes={'*':['id','class'],'a':['href','title','target','rel'],'img':['src','alt','width','height'],'details':['open'],'span':['class','aria-hidden']},protocols=['http','https','mailto'],strip=True)

def variant_order(image):
    """Prefer newest PG, then stable/oldstable Debian before testing/unstable."""
    distro = image['distro']
    rank = {'trixie': 0, 'stable': 0, 'bookworm': 1, 'oldstable': 1,
            'sid': 3, 'unstable': 3}.get(distro, 2)
    return -int(image['pg']), rank, distro


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--refresh',action='store_true');parser.add_argument('--scan',action='store_true');parser.add_argument('--workers',type=int,default=4)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--reuse-evidence', action='store_true', help='Local layout iteration only: reuse exact-digest evidence with original scan timestamps')
    mode.add_argument('--evidence-only', action='store_true', help='Scan one catalog partition and save its evidence and notices')
    mode.add_argument('--merge-evidence', action='store_true', help='Validate and assemble scanned catalog partitions')
    parser.add_argument('--prepared-advisories', action='store_true', help='Scan with the verified workflow database snapshot')
    parser.add_argument('--merge-history', action='store_true', help='Use verified history retrieved in this workflow run')
    parser.add_argument('--shard-index', type=int, help='Zero-based index of the partition to scan')
    parser.add_argument('--shard-count', type=int, help='Total number of catalog partitions')
    parser.add_argument('--rebuild-cache', action='store_true', help='Ignore saved OCI assets, license notices, and version history')
    parser.add_argument('--refresh-extension', help='Refetch saved assets for one catalog extension')
    args=parser.parse_args()
    if args.prepared_advisories and not args.scan:
        parser.error('--prepared-advisories requires --scan')
    if args.refresh_extension and args.reuse_evidence:
        parser.error('--refresh-extension cannot be combined with --reuse-evidence')
    if args.evidence_only:
        if not args.scan:
            parser.error('--evidence-only requires --scan')
        if args.shard_count is None or args.shard_index is None or not 0 <= args.shard_index < args.shard_count:
            parser.error('--evidence-only requires a shard index between zero and shard count minus one')
    elif args.shard_index is not None or args.shard_count is not None:
        parser.error('--shard-index and --shard-count require --evidence-only')
    if args.merge_history and not args.merge_evidence:
        parser.error('--merge-history requires --merge-evidence')
    if args.merge_evidence and args.scan:
        parser.error('--merge-evidence already consumes scanned evidence')
    if args.rebuild_cache and (args.reuse_evidence or args.merge_evidence):
        parser.error('--rebuild-cache requires fresh evidence collection')

    CACHE.mkdir(exist_ok=True)
    if args.evidence_only:
        output_shard = shard_path(CACHE, args.shard_index)
        output_shard.unlink(missing_ok=True)
    if args.rebuild_cache:
        for name in ('oci', 'image-notices-v1', 'version-history'):
            shutil.rmtree(CACHE / name, ignore_errors=True)
    with phase("source refresh"):
        commits={n:checkout(n,args.refresh) for n in REPOS}
        refresh_record=CACHE/'source-refresh.json'
        previous=json.loads(refresh_record.read_text()) if refresh_record.exists() else {}
        source_refreshed_at=source_refresh_time(args.refresh, commits, previous, NOW)
        if args.refresh:
            refresh_record.write_text(json.dumps({'commits':commits,'refreshedAt':source_refreshed_at}))
    jobs=[]
    for cat in sorted((CACHE/'artifacts/image-catalogs-extensions').glob('catalog-*.yaml')):
        document=yaml.safe_load(cat.read_text());distro=document['metadata']['labels']['images.cnpg.io/os']
        for entry in document['spec']['images']:
            for e in entry.get('extensions',[]):
                ref=e['image']['reference']
                if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',e['name']):raise ValueError('Unsafe extension name')
                jobs.append({'name':e['name'],'pg':entry['major'],'distro':distro,'reference':ref,'catalog':cat.name})
    if not jobs: raise RuntimeError('Catalog contains no extensions')
    if args.refresh_extension and args.refresh_extension not in {j['name'] for j in jobs}:
        parser.error('Unknown catalog extension: ' + args.refresh_extension)
    evidence_file=CACHE/'inspected.json'
    if args.merge_evidence:
        with phase("evidence assembly"):
            images, database = merge_shards(CACHE, jobs, commits, ROOT / 'static')
    elif args.reuse_evidence:
        saved=json.loads(evidence_file.read_text());images=saved['images'];database=saved['database']
        if sorted((x['name'],x['pg'],x['distro'],x['reference']) for x in images)!=sorted((x['name'],x['pg'],x['distro'],x['reference']) for x in jobs):
            raise RuntimeError('Cached evidence does not match current catalogs; regenerate it')
    else:
        scan_jobs = jobs
        if args.evidence_only:
            if args.shard_count > len(jobs):
                parser.error('--shard-count exceeds the number of catalog images')
            scan_jobs = jobs[args.shard_index::args.shard_count]
        grype=shutil.which('grype') if args.scan else None
        if args.scan and (not grype or not shutil.which('osv-scanner')):raise RuntimeError('--scan requires Grype and OSV-Scanner')
        with phase("advisory refresh"):
            database={}
            if args.prepared_advisories:
                snapshot = json.loads((CACHE / 'advisory-databases.json').read_text())
                osv_database = snapshot['osvDatabase']
                database = json.loads(run(grype, 'db', 'status', '-o', 'json'))
                if database_identity(database, osv_database) != database_identity(snapshot['database'], osv_database):
                    raise RuntimeError('Installed Grype database differs from the prepared snapshot')
            else:
                if grype:
                    p=subprocess.run([grype,'db','update'],capture_output=True,text=True)
                    if p.returncode: database={'error':'Vulnerability database update failed; no current scan is available.'}
                    else: database=json.loads(run(grype,'db','status','-o','json'))
                osv_database=timed("OSV database refresh")(refresh_database)(ROOT) if args.scan else None
            if args.evidence_only:
                database_identity(database, osv_database)
        images=[]
        with phase("image inspection and Grype"):
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures=[pool.submit(inspect_image,j,grype,database,j['name']==args.refresh_extension) for j in scan_jobs]
                for f in concurrent.futures.as_completed(futures):
                    image=f.result();images.append(image)
                    print(f"{len(images)}/{len(scan_jobs)} {image['name']} {image['distro']}: {image['status']}",flush=True)
        platforms = [p for image in images for p in image['platforms'] if p['status'] == 'available']
        with phase("OSV batch scan"):
            osv_results = scan_osv_batch([ROOT / 'static' / p['sbom'] for p in platforms],
                                        ROOT, shutil.which('osv-scanner') if args.scan else None, osv_database)
        for platform in platforms:
            platform['osvScan'] = osv_results[ROOT / 'static' / platform['sbom']]
    if not (args.reuse_evidence or args.evidence_only):
        evidence_file.write_text(json.dumps({'images':images,'database':database}))
    for scanner in ('scan', 'osvScan'):
        counts = Counter(p.get(scanner, {}).get('status', 'missing') for image in images
                         for p in image['platforms'] if p['status'] == 'available')
        print(f'EVIDENCE {scanner}: {json.dumps(counts, sort_keys=True)}', flush=True)
    # Rebuild display fields from original SPDX, including during local evidence reuse.
    if not args.evidence_only:
        for image in images:
            image['packageURL'] = image_package_url(image['reference'])
            for platform in image['platforms']:
                if platform['status']=='available':
                    spdx=json.loads((ROOT/'static'/platform['sbom']).read_text())
                    platform['packages']=packages(spdx)
                    platform['noticeFiles']=notice_files(spdx)
    # Read shipped notices for every publisher, independently of SBOM availability.
    if not args.merge_evidence:
        with phase("license notices"):
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending=[]
                for image in images:
                    for platform in image['platforms']:
                        pending.append((platform, pool.submit(timed("notices")(container_notices),
                            image['reference'], platform['architecture'], platform['digest'], CACHE,
                            refresh=image['name']==args.refresh_extension and not args.merge_evidence)))
                for platform, future in pending:
                    platform['containerNotices']=future.result()
    if args.evidence_only:
        output_shard.write_text(json.dumps({'shardIndex': args.shard_index, 'shardCount': args.shard_count,
                                           'commits': commits, 'database': database,
                                           'osvDatabase': osv_database, 'images': images}))
        return

    with phase("page content"):
        recipes,routes=recipe_index(CACHE, commits)
        entries=[]
        content=ROOT/'content/extensions';content.mkdir(parents=True,exist_ok=True)
        for old in content.glob('*/index.md'): old.unlink()
        for name in sorted({j['name'] for j in jobs}):
            variants=sorted([i for i in images if i['name']==name],key=variant_order)
            publisher=publisher_for(variants[0]['reference'])
            repo=publisher+'/postgres-extensions-containers'
            recipe=find_recipe(CACHE, recipes, publisher, name, commits)
            if not recipe: raise RuntimeError('No source README found for published extension '+name)
            text=recipe['readme'].read_text()
            soup=BeautifulSoup(markdown.markdown(text),'html.parser');first=soup.find('p')
            description=first.get_text(' ',strip=True) if first else name
            entry={'name':name,'title':name,'sqlName':recipe['meta'].get('sql_name',''),'description':description,'publisher':publisher,'build':'PGRX' if recipe['build'].lower()=='pgrx' else recipe['build'].capitalize(),
                'source':f"https://github.com/{repo}/blob/main/{recipe['path']}", 'variants':variants,
                'version':variants[0]['version'],'distros':sorted({i['distro'] for i in variants}),'pgVersions':sorted({i['pg'] for i in variants}),
                'declaredLicenses':recipe['meta'].get('licenses',[])}
            entries.append(entry)
            directory=content/name;directory.mkdir(exist_ok=True)
            fm={'title':entry['title'],'description':description,'extension':name,'layout':'extension'}
            body=readme_html(text,repo,recipe['commit'],recipe['path'],routes)
            (directory/'index.md').unlink(missing_ok=True)
            fm['type'] = 'extensions'
            (directory/'_index.md').write_text('---\n'+yaml.safe_dump(fm,sort_keys=False)+'---\n'+body+'\n')
            tab_body=readme_html(text,repo,recipe['commit'],recipe['path'],routes,depth=3)
            for view in ('overview', 'documentation', 'dependencies', 'licenses', 'versions'):
                tab_directory = directory/view
                tab_directory.mkdir(exist_ok=True)
                tab_fm = dict(fm, view=view)
                (tab_directory/'index.md').write_text('---\n'+yaml.safe_dump(tab_fm,sort_keys=False)+'---\n'+tab_body+'\n')
    from version_history import generate_history
    if args.merge_history:
        from history_evidence import verify
        timed("history assembly")(verify)(ROOT, entries, commits)
    else:
        timed("history")(generate_history)(entries, refresh_extension=args.refresh_extension)
    result={'generatedAt':NOW,'sourceRefreshedAt':source_refreshed_at,'commits':commits,'count':len(entries),'extensions':entries,'database':database}
    (ROOT/'data').mkdir(exist_ok=True)
    (ROOT/'data/generated.json').write_text(json.dumps(result))
    search=[{k:v for k,v in e.items() if k!='variants'} for e in entries]
    (ROOT/'static/catalog.json').write_text(json.dumps({'generatedAt':NOW,'sourceRefreshedAt':source_refreshed_at,'extensions':search}))
    # Keep the top-level setup in sync with the published README, without manually duplicating YAML.
    readme=(CACHE/'source/README.md').read_text()
    requirements='## Requirements'+readme.split('## Requirements',1)[1].split('\n---',1)[0]
    quick=readme.split('## Quick start',1)[1].split('\n## Supported Extensions',1)[0].strip().rstrip('-\n')
    (ROOT/'content/getting-started.md').write_text('---\ntitle: Get started\nurl: /get-started/\naliases: [/getting-started/]\ndescription: Configure alerts, install the catalog, and enable extensions in your databases.\n---\n'+
        getting_started(readme_html(requirements+'\n\n'+quick,REPOS['source'],commits['source'],'README.md',routes,depth=1)))
    subprocess.run([sys.executable, str(ROOT/'scripts/overview_metadata.py')], check=True)
    from scorecard_data import generate_scorecards
    timed("scorecards")(generate_scorecards)()
    print(f'Generated {len(entries)} extension pages from {len(images)} catalog images',flush=True)

if __name__=='__main__':main()
