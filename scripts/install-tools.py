#!/usr/bin/env python3
"""Install pinned release binaries, validating release checksums before extraction."""
import urllib.request, hashlib, tarfile, io
from pathlib import Path
out=Path('.tools');out.mkdir(exist_ok=True)
for repo,ver,filename,binary in [('gohugoio/hugo','0.170.0','hugo_extended_0.170.0_linux-amd64.tar.gz','hugo'),('anchore/grype','0.121.3','grype_0.121.3_linux_amd64.tar.gz','grype')]:
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
base='https://github.com/google/osv-scanner/releases/download/v2.7.1/'
filename='osv-scanner_linux_amd64'
sums=urllib.request.urlopen(base+'osv-scanner_SHA256SUMS').read().decode()
expected=next(line.split()[0] for line in sums.splitlines() if line.endswith(filename))
data=urllib.request.urlopen(base+filename).read()
if hashlib.sha256(data).hexdigest()!=expected: raise RuntimeError('OSV release checksum mismatch')
(out/'osv-scanner').write_bytes(data)
(out/'osv-scanner').chmod(0o755)
print('Installed osv-scanner 2.7.1; release checksum verified')
