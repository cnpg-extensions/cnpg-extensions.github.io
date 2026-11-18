#!/usr/bin/env python3
"""Install pinned release binaries, validating release checksums before extraction."""
import urllib.request, hashlib, tarfile, io
from pathlib import Path
# renovate: datasource=github-releases depName=gohugoio/hugo
HUGO_VERSION = "0.170.0"
# renovate: datasource=github-releases depName=anchore/grype
GRYPE_VERSION = "0.121.3"
# renovate: datasource=github-releases depName=google/osv-scanner
OSV_SCANNER_VERSION = "2.7.1"

out=Path('.tools');out.mkdir(exist_ok=True)
for repo,ver,filename,binary in [('gohugoio/hugo',HUGO_VERSION,f'hugo_extended_{HUGO_VERSION}_linux-amd64.tar.gz','hugo'),('anchore/grype',GRYPE_VERSION,f'grype_{GRYPE_VERSION}_linux_amd64.tar.gz','grype')]:
    base=f'https://github.com/{repo}/releases/download/v{ver}/'
    sums=urllib.request.urlopen(base+f'{binary}_{ver}_checksums.txt').read().decode()
    expected=next(line.split()[0] for line in sums.splitlines() if line.endswith(filename))
    data=urllib.request.urlopen(base+filename).read()
    if hashlib.sha256(data).hexdigest()!=expected: raise RuntimeError('Release checksum mismatch: '+filename)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        (out/binary).write_bytes(archive.extractfile(binary).read())
    (out/binary).chmod(0o755)
    print(f'Installed {binary} {ver}; release checksum verified')

# OSV publishes a standalone executable rather than a tar archive.
base=f'https://github.com/google/osv-scanner/releases/download/v{OSV_SCANNER_VERSION}/'
filename='osv-scanner_linux_amd64'
sums=urllib.request.urlopen(base+'osv-scanner_SHA256SUMS').read().decode()
expected=next(line.split()[0] for line in sums.splitlines() if line.endswith(filename))
data=urllib.request.urlopen(base+filename).read()
if hashlib.sha256(data).hexdigest()!=expected: raise RuntimeError('OSV release checksum mismatch')
(out/'osv-scanner').write_bytes(data)
(out/'osv-scanner').chmod(0o755)
print(f'Installed osv-scanner {OSV_SCANNER_VERSION}; release checksum verified')
