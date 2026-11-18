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
hugo server --renderToMemory --bind 0.0.0.0 --baseURL http://localhost:8766/ --port 8766 --appendPort=false
```

For a quicker content/layout iteration, omit `--scan` (results explicitly say
not run), or reuse the existing generated data and run just Hugo. Omitting
`--refresh` uses the existing cached source checkouts. Production always refreshes
sources and scans. Do not commit generated data or reports; reproduce them at build
time. Full reports are available as downloads in the published site.

The website generator retrieves assets directly and saves them for reuse. The nightly
website workflow restores the previous `website-assets-v1-*` artifact, runs the
generator, and uploads the resulting assets again with **seven-day retention**.
There is no separate history workflow or snapshot publication step.

Saved assets include digest-addressed OCI metadata/SBOMs, extracted license notices,
and version-history metadata with verified GHCR links. With cached history, refreshes
read GitHub package pages newest-first until a complete page of timestamped build
tags and digests matches the cache. Newly discovered builds get their exact GHCR
links from that same page; only missing or changed builds need manifest requests.
Current catalog digest changes are checked even outside the discovered pages.

Initial loads and weekly reconciliation use the full registry tag listing, including
to discover older additions and remove deleted tags. Incremental runs retain older
cached records, so deletions can remain visible until reconciliation. Explicit full
refreshes also refetch known manifests. Timestamped tags are otherwise treated as
immutable. GitHub page ordering is an observed website behavior, not an OCI API
contract; malformed pages and failed retrievals fail the build. History updates
remain serial, preserving completed extensions without concurrent cache writes.

Advisory databases refresh and scans rerun each
build so new advisories are detected for unchanged images. Source checkouts refresh
normally. Changes to the notice extractor invalidate the saved artifact name.

Each successfully retrieved asset is saved as it is processed, including when a
later retrieval fails. The workflow retains those assets for the next attempt.
History retrieval failures fail the build; Hugo's history data is replaced only
after all extensions finish successfully. Failed builds never deploy.

On a manual website run, **Ignore all saved website assets and retrieve them again**
(`rebuild_cache`) bypasses restoration and repopulates all asset caches. Alternatively,
set **Refetch assets for one extension** (`refresh_extension`, for example `semver`)
to refresh that extension's OCI data, notices, and history while reusing the rest.
Locally use `--rebuild-cache` or `--refresh-extension semver` with `generate.py`.
Neither option reuses prior vulnerability scan results.

For a history-only local refresh using the same retrieval code:

```sh
python scripts/version_history.py --all
```

## Sources of truth

- Published entries, distributions, PG majors, image digests: both YAML catalogs
  in `cnpg-extensions/artifacts/image-catalogs-extensions`.
- Overview license summaries and project links: generated automatically from SPDX,
  PGDG package metadata, and GitHub/GitLab Renovate recipe metadata.
- README and recipe metadata: `cnpg-extensions/postgres-extensions-containers`,
  with `cloudnative-pg/postgres-extensions-containers` for upstream-published images.
- Current versions: published OCI annotations or config labels, **not** a recipe
  version that may not have shipped yet. Trixie is the card's preferred variant;
  detail pages select one distribution and architecture at a time. Image details
  link to the catalog image’s GHCR package page for published versions.
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
  with exact-version crates.io links on Cargo package names and deps.dev links
  on their advisory indicators (retaining its advisory and OpenSSF Scorecard context),
  plus Debian source-package tracker links derived
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
batch uses the same database. OSV refreshes the Cargo and Debian database archives
once per build, then scans all SBOMs with `--offline` against that fixed snapshot.
Refresh failures produce unavailable OSV results; stale databases are not silently reused.
Database hashes and refresh time are recorded with each scan in generated data.
OSV-Scanner runs the documented JSON command as a temporary
supplement for the missing direct RustSec feed tracked in
[Grype #529](https://github.com/anchore/grype/issues/529); its findings contribute to a Yes/No/Unknown indicator alongside Grype.
No combined numeric count is displayed because scanner findings can overlap.
Scanner failures remain explicit and do not become zero findings. Revisit the workaround when that gap is resolved.

## GitHub Pages

In repository Settings → Pages, choose **GitHub Actions** as the source. The workflow
builds on pushes to main, manually, and nightly at 10:30 UTC. Pull requests do not run this
workflow; run the local validation commands before pushing.
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
upstream dependency tables remain hidden. The Licenses tab shows shipped license files with expandable text.
The original downloadable SBOM retains any embedded license records. Retrieval failures are shown separately
from an inspected image with no notice files.

Generation requires an accessible Docker daemon (provided by the Ubuntu GitHub
Actions runner). Successful notice results are cached by immutable platform digest
in `.cache/image-notices-v1` and included in the seven-day website-assets artifact. Restored
results skip Docker pull, create, and export entirely; new digests are extracted
and failures are retried on the next build. Cache eviction can require extraction
again. Changes to `scripts/image_notices.py` automatically invalidate the saved website-assets artifact.

To force extraction for all current images, manually run the website workflow with
**Ignore all saved website assets and retrieve them again** enabled, or specify one
extension with `refresh_extension`. Fresh results are saved for subsequent builds.
Locally, use `--rebuild-cache` or `--refresh-extension NAME`. Advisory scans still refresh normally.

## Weekly upstream Scorecard reports

`scorecards.yml` runs every Monday at 08:17 UTC and supports manual dispatch.
Both triggers run fresh scans with the pinned Scorecard version, using the current published
catalog and reviewed upstream mappings in `data/scorecard-repositories.json`.
Only extensions explicitly listed in `data/scorecard-local-scans.json` are scanned.
The initial list contains the 76 supported-host extensions without an OpenSSF API
report in the November 17, 2026 audit, including seven with older deps.dev reports.
The 26 entries with OpenSSF reports and Salsa-hosted debversion are excluded.
The list does not change when OpenSSF coverage changes: add/remove entries manually.
New catalog entries are not automatically added. The full repository mapping remains
available for looking up externally published reports.
The scanner never builds upstream code. See the user-runnable command on the
Security page before changing the automated command.

Each run uploads `scorecard-results` with **21-day retention**. It contains an
`index.json` with catalog revision, producer, run, scope and per-extension status,
plus unmodified JSON reports keyed by repository URL hash. Scores are not adjusted.
There is no release asset or automatic deletion of previous runs. Failed checks
remain in the raw report; repository failures and unsupported hosts are explicit
in the index. A run with no reports fails but uploads its diagnostic index.

For testing, dispatch with `extensions=http,hypopg`; these artifacts are named
`scorecard-results-test`, so a website consumer cannot mistake a subset for a complete local-list
snapshot. Consumers should select the latest successful default-branch run's
non-expired `scorecard-results` artifact and retain original report dates.
The overview's OpenSSF scorecard panel uses the public OpenSSF API first, linking to
the readable OpenSSF Scorecard viewer for that repository. If no usable API report is available, the website generator consumes
this artifact and offers the original JSON as a download. When neither source is
available it displays “Unavailable”. Report dates and individual check scores
(including inconclusive results) are preserved; the aggregate score is not shown.
Run `python scripts/scorecard_data.py` to refresh just this panel's data locally.
Artifact retrieval uses `gh` with `GH_TOKEN` (or a local authenticated session);
API lookup does not require authentication.

The built-in GitHub token is used by default. Optional `SCORECARD_TOKEN` can supply
additional API capacity; `SCORECARD_GITLAB_TOKEN` enables GitLab.com scans. Without
it GitLab entries are unavailable. Salsa is explicitly unsupported by this workflow.
Concurrency is limited to two scans, with a five-minute timeout per repository.

The ardentperf-labs full-catalog test produced 83 reports with the built-in token.
Some repositories' classic branch-protection settings cause Scorecard to return
an error with this token; a generic higher-quota token does not necessarily grant
access to those settings. Organization IP allow lists can also prevent scans.
Valid partial JSON reports are retained even on a nonzero exit, with the exit code,
inconclusive check count and sanitized diagnostics. Invalid or absent reports
remain unavailable. The workflow prints per-repository progress as scans finish.

### Scorecard dependency updates

`renovate.json` limits automated dependency updates to
`.github/workflows/scorecards.yml`: GitHub Actions, Python, PyYAML, and the
Scorecard release binary. Renovate checks on the first day of each month between 00:00 and
07:00 UTC and batches all available updates, including major versions, into one
PR for manual review. Only one regular update PR can be open at a time; existing
update branches are refreshed during the monthly window. The Scorecard version is
defined once in `SCORECARD_VERSION`; the release tag, archive name, and checksum
selection all use that value. Release checksum verification remains required.

To activate updates after merging, enable the hosted [Renovate GitHub App](https://github.com/apps/renovate)
for this repository. No workflow token or additional repository secret is needed.
Existing website dependencies are outside this configuration's scope.
