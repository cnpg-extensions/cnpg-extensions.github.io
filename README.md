# CNPG Extensions website

Hugo + Hextra, with custom layouts preserving the approved Nunito Sans / warm-paper
homepage. Hosted with GitHub Pages. No application server, analytics, or browser-side
CVE API keys. Search/filtering runs locally in the browser; all extension links
also work without JavaScript.

## Build and preview

Linux AMD64, Python 3.12+ and Git are required. Pinned Hugo, Grype, and OSV-Scanner downloads are
checked against their release checksums. The Hextra submodule is pinned to v0.13.0.

```sh
git submodule update --init --recursive
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/install-tools.py
export PATH="$PWD/.tools:$PATH"
python scripts/generate.py --refresh --scan
hugo --minify
hugo server --bind 0.0.0.0 --baseURL http://localhost:8766/ --port 8766 --appendPort=false
```

For a quicker content/layout iteration, omit `--scan` (results explicitly say
not run), or reuse the existing generated data and run just Hugo. Omitting
`--refresh` uses the existing cached source checkouts. Production always refreshes
sources and scans. Do not commit generated data or reports; reproduce them at build
time. Full reports are available as downloads in the published site.

## Sources of truth

- Published entries, distributions, PG majors, image digests: both YAML catalogs
  in `cnpg-extensions/artifacts/image-catalogs-extensions`.
- Overview license summaries and project links: generated automatically from SPDX,
  PGDG package metadata, and GitHub/GitLab Renovate recipe metadata.
- README and recipe metadata: `cnpg-extensions/postgres-extensions-containers`,
  with `cloudnative-pg/postgres-extensions-containers` for upstream-published images.
- Current versions: published OCI annotations or config labels, **not** a recipe
  version that may not have shipped yet. Trixie is the card's preferred variant;
  detail pages select one distribution and architecture at a time.
- Package versions and licenses: digest-checked BuildKit SPDX attestations, per
  architecture. Preserve declared/concluded expressions, file licenses, and custom
  license definitions without inferring missing terms. Unknown stays unknown.
- Vulnerabilities: Grype and OSV-Scanner against current advisory data, scanning each
  published platform's SPDX document. No `wont-fix`, severity or fix-only filters.
  Downloadable reports expose database metadata, image/platform digests, and scan time.
  The dependency view uses Grype for Debian and other non-Rust packages, and
  Grype plus OSV for Cargo packages (identified by SPDX package URLs). It shows
  Yes if a relevant scanner finds advisories, No when all relevant scans complete
  without findings, and Unknown otherwise,
  with exact-version Cargo links and Debian source-package tracker links derived
  from SPDX package URLs. Missing scan results remain uncounted; external results
  may differ. No CVE table is rendered. Matches
  are not exploitability verdicts; scans exclude the separate PostgreSQL base image.
- Getting started: imported from the current top-level README; security examples
  show actual package evidence from the generated inventory.

No AI summaries, manually injected extension versions, invented categories or
per-extension license/CVE entries. Card descriptions come from the README's first
paragraph. Source revisions are recorded and linked. Generated HTML is sanitized;
source repositories are fetched as data, never executed. Changes to README link
resolution should be covered by tests.

Registry hash checks do **not** validate publisher identity. The website does not
claim signature verification; the Security page explains independent Cosign checks.

## Reproducible security checks

Website security automation must mirror the commands documented on the
[Security page](content/security.md). Document a user-runnable command before
adding or changing an automated check. Preserve the CloudNativePG-compatible
SBOM format; do not rewrite Debian package identities to accommodate a scanner.

The generator currently updates Grype's database once, then runs the documented
JSON SBOM scan for each platform with automatic database updates disabled so the
batch uses the same database. OSV-Scanner runs the documented JSON command as a temporary
supplement for the missing direct RustSec feed tracked in
[Grype #529](https://github.com/anchore/grype/issues/529); its findings contribute to a Yes/No/Unknown indicator alongside Grype.
No combined numeric count is displayed because scanner findings can overlap.
Scanner failures remain explicit and do not become zero findings. Revisit the workaround when that gap is resolved.

## GitHub Pages

In repository Settings → Pages, choose **GitHub Actions** as the source. The workflow
builds on main, on pull requests (no deploy), manually, and nightly at 10:30 UTC.
Nightly builds fetch fresh source/catalog revisions and update Grype's database.
GitHub's scheduled workflows can be delayed and may be disabled after repository
inactivity. Dates stay visible; old scan results are not relabeled current.

The configured base URL is
`https://cnpg-extensions.github.io/`. Change both Hugo config
and the workflow build argument if the repository/domain changes. Enable Pages
before the first deploy. The `github-pages` environment may need approval if the
repository owner configures protection rules.

Fatal catalog/README parsing failures stop the build and preserve the previous
site. Individual registry/SBOM/scan failures appear as unavailable, not zero CVEs.
Grype DB update failures likewise produce unavailable results. Immutable registry
blobs are cached across builds; advisory scans are rerun rather than cached.

## Validation

```sh
python -m unittest discover -s tests -v
hugo --minify
python scripts/check-site.py public
```

Review the homepage, search/reset, extension documentation/evidence, mobile menu,
light/dark modes and code copying in a browser. The homepage excerpt is intentionally
shortened; the Get started page supplies the full CronJob and RBAC.

## License and assets

Website source: Apache-2.0. See NOTICE for imported documentation and third-party
asset attribution, and the font/theme licenses alongside their sources.

### Container and SBOM license notices

For images from every publisher, the generator uses Docker to pull the
catalog-resolved platform manifest by digest, create (but never run) a container,
and export its final filesystem. Files under `/licenses` are displayed verbatim
with their paths and SHA256 hashes. This does not produce a dependency inventory;
upstream dependency tables remain hidden. The Container licenses tab shows shipped license files with expandable text.
The original downloadable SBOM retains any embedded license records. Retrieval failures are shown separately
from an inspected image with no notice files.

Generation requires an accessible Docker daemon (provided by the Ubuntu GitHub
Actions runner). Local notice results are cached by immutable platform digest in
`.cache/image-notices-v1`; new image digests are extracted on subsequent builds.
