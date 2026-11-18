---
title: Security you can inspect
description: Verify who published an image. Inspect its build inputs, dependency versions, license evidence, and vulnerability matches.
---

## Report a vulnerability {#report-a-vulnerability}

For vulnerabilities in an extension itself, report directly to the extension project’s owners or maintainers using their security reporting process.

For vulnerabilities in CNPG Extensions packaging, container builds, or infrastructure, [report privately on GitHub](https://github.com/cnpg-extensions/postgres-extensions-containers/security/advisories/new). Include the affected extensions, image tags or digests, impact, and steps to reproduce. Please do not disclose vulnerabilities in public issues, discussions, pull requests, or Slack.

See the [security policy](https://github.com/cnpg-extensions/postgres-extensions-containers/blob/main/security.md) for response targets and coordinated disclosure, and [published security advisories](https://github.com/cnpg-extensions/postgres-extensions-containers/security/advisories) for past reports.

## Compatible with CloudNativePG {#cloudnativepg-compatibility}

CNPG Extensions follows the same verification, SBOM, and provenance conventions as [CloudNativePG’s PostgreSQL containers](https://cloudnative-pg.io/docs/current/installation_upgrade/#verifying-postgresql-operand-images). Our [SBOM generator](https://github.com/cnpg-extensions/cnpg-sbom-generator#compatibility) uses the same Syft and BuildKit approach, preserving SPDX formats while identifying the packages and license evidence shipped in each extension image.

Use the same commands you use for your PostgreSQL container: Cosign to verify signatures, Docker Buildx to extract SBOMs and inspect provenance, Grype to check advisories, and Grant to report licenses. Supply the appropriate image reference and publisher identity. [CloudNativePG’s image inspection and verification instructions](https://cloudnative-pg.io/docs/current/installation_upgrade/#verifying-postgresql-operand-images) and the [SBOM generator’s inspection guide](https://github.com/cnpg-extensions/cnpg-sbom-generator#inspect-an-image) describe the shared workflow. For publisher-specific details, see the [CNPG Extensions SBOM and authenticity documentation](https://github.com/cnpg-extensions/postgres-extensions-containers#sboms-and-authenticity).

See example captured command output for [OGR FDW](https://github.com/cnpg-extensions/postgres-extensions-containers/blob/main/examples/sbom-reports.txt) and [pg_parquet](https://github.com/cnpg-extensions/postgres-extensions-containers/blob/main/examples/pg-parquet-sbom-reports.txt), including vulnerability and license reports.

## Find the image reference {#find-the-image-reference}

Set `IMAGE` once; the examples throughout the rest of this page reuse it. Choose a digest-pinned image reference from its extension page, such as pg_cron:

```sh
IMAGE='ghcr.io/cnpg-extensions/pg-cron:1.6.8-202611130420-18-trixie@sha256:1f3eec1740ffa0c2856bb652883f031813cccbfc26134b82ba770cb63169a190'
```

## Verify an image {#verify-the-publisher}

Install [Cosign](https://docs.sigstore.dev/cosign/system_config/installation/) to verify the image signature.

Select the exact workflow identity for its publisher and build type:

{{< disclosure title="Choose the publisher and workflow identity" >}}

| Publisher / build | Workflow identity |
| --- | --- |
| CloudNativePG / Debian | `https://github.com/cloudnative-pg/postgres-extensions-containers/.github/workflows/bake_targets.yml@refs/heads/main` |
| CNPG Extensions / Debian | `https://github.com/cnpg-extensions/postgres-extensions-containers/.github/workflows/bake_targets.yml@refs/heads/main` |
| CNPG Extensions / PGRX or Universe | `https://github.com/cnpg-extensions/postgres-extensions-containers/.github/workflows/source-build-targets.yml@refs/heads/main` |

{{< /disclosure >}}

```sh
IDENTITY='https://github.com/cnpg-extensions/postgres-extensions-containers/.github/workflows/bake_targets.yml@refs/heads/main'

cosign verify "$IMAGE" \
  --certificate-identity="$IDENTITY" \
  --certificate-oidc-issuer='https://token.actions.githubusercontent.com' \
  --new-bundle-format=false
```

Check for a successful verification. A valid index signature binds the platform manifests and their attached SBOM and BuildKit provenance.

## Inspect build provenance {#inspect-build-provenance}

Requires [Docker Buildx](https://docs.docker.com/build/install-buildx/) and [jq](https://jqlang.org/).

```sh
docker buildx imagetools inspect "$IMAGE" \
  --format '{{ json (index .Provenance "linux/amd64").SLSA }}' \
  > provenance.json

jq . provenance.json
```

Review the recorded source revision, build inputs, and parameters. Inspecting provenance alone is not signature verification. Use `linux/arm64` to inspect ARM64 evidence. For a single-platform index, confirm its platform and use `.Provenance.SLSA` instead.

## Inspect dependencies and licenses {#extract-the-package-inventory}

Requires [Docker Buildx](https://docs.docker.com/build/install-buildx/) and [jq](https://jqlang.org/).

```sh
docker buildx imagetools inspect "$IMAGE" \
  --format '{{ json (index .SBOM "linux/amd64").SPDX }}' \
  > image.spdx.json

jq -r '.packages[] | [.name, .versionInfo] | @tsv' image.spdx.json
```

For a single-platform index, use `.SBOM.SPDX`. Inspect both architectures if you deploy both. The extension SBOM covers shipped extension files and dependencies; **inspect and scan the PostgreSQL base image separately**.

{{< disclosure title="View a real package and license example" >}}

{{< evidence-example >}}

{{< /disclosure >}}

### Package licenses {#licenses}

List all package license expressions, or inspect one package by its exact SBOM name:

```sh
jq -r '.packages[] |
  [.name, .versionInfo, .licenseDeclared, .licenseConcluded] |
  @tsv' image.spdx.json

PACKAGE='postgresql-18-cron'
jq --arg name "$PACKAGE" '.packages[] |
  select(.name == $name) |
  {name, versionInfo, licenseDeclared, licenseConcluded,
   licenseInfoFromFiles}' image.spdx.json
```

The expandable example above shows output from an actual published SBOM. The extension pages expose the same fields for every package, plus any extracted license texts. A recipe's top-level license is not a substitute for the complete container inventory.

`NOASSERTION` means the document makes no assertion. `LicenseRef-…` can refer to custom or unclassified terms. Preserve `AND` and `OR` expressions when assessing obligations; do not treat them as interchangeable. Alternatively, install [Grant](https://github.com/anchore/grant) for license reports:

```sh
grant list image.spdx.json
grant list image.spdx.json MIT
```

{{< disclosure title="Retrieve an original notice from the image" id="retrieve-an-original-notice" >}}

Requires Docker with a running daemon, jq, and `sha256sum`.

License text can be shipped as a file in the container even when it is not embedded in the SBOM. The extension page lists notice paths recorded for the selected image. Copy a file from that exact image and architecture, then verify it against the SBOM checksum. The container does not need to run or contain a shell.

Use the digest-pinned `IMAGE` and matching `image.spdx.json` from the steps above. Set `NOTICE` to one of the listed paths, without a leading slash:

```sh
PLATFORM=linux/amd64
NOTICE=licenses/libgomp1/copyright

CONTAINER=$(docker create --platform "$PLATFORM" "$IMAGE" /unused)
docker cp "$CONTAINER:/$NOTICE" ./original-notice
docker rm "$CONTAINER"
```

The path above is an example; select a path present in your image. For ARM64, use `linux/arm64` and its SBOM.

Verify the copied file before reading it:

```sh
EXPECTED=$(jq -r --arg path "$NOTICE" '
  .files[]? |
  select((.fileName | sub("^\\./"; "") | sub("^/"; "")) == $path) |
  .checksums[]? | select(.algorithm == "SHA256") |
  .checksumValue' image.spdx.json | sort -u)

if [ -n "$EXPECTED" ]; then
  printf '%s  original-notice\n' "$EXPECTED" | sha256sum --check -
else
  printf '%s\n' 'No SHA256 checksum recorded for this path.' >&2
fi
```

A successful check prints `original-notice: OK`. If the checksum is missing or does not match, the file has not been verified against this SBOM. After a successful check, open `original-notice` in a text editor to read the terms.

If you are starting with a 64-character notice checksum from `grant list`, find its file paths first:

```sh
CHECKSUM='REPLACE_WITH_NOTICE_SHA256'
jq -r --arg checksum "$CHECKSUM" '
  .files[]? |
  select(any(.checksums[]?;
    .algorithm == "SHA256" and .checksumValue == $checksum)) |
  .fileName' image.spdx.json
```

Several paths may contain identical copies of a notice; choose one. A named reference such as `LicenseRef-citus` is not itself a checksum. Shared package notices may cover multiple libraries and more code than a single shipped binary.

{{< /disclosure >}}

## Check advisories {#vulnerabilities}

Install [Grype](https://github.com/anchore/grype) and use the `image.spdx.json` extracted above.

```sh
grype db update
grype sbom:image.spdx.json -o table
grype sbom:image.spdx.json -o json > vulnerabilities.json
```

### RustSec coverage: temporary workaround

Grype can match Rust dependencies against GitHub advisories, but does not yet consume the RustSec database directly. Direct support is tracked in [Grype issue #529](https://github.com/anchore/grype/issues/529). Some RustSec advisories can therefore be missing from Grype results, when using Grype alone.

Until that gap is resolved, install [OSV-Scanner](https://google.github.io/osv-scanner/installation/) and scan the **same, unchanged SBOM** for additional RustSec coverage:

{{< disclosure title="Run OSV-Scanner against the SBOM" >}}

```sh
osv-scanner scan source -L image.spdx.json
```

To save a machine-readable report:

```sh
osv-scanner scan source -L image.spdx.json --format json > osv-results.json
```

Keep the `.spdx.json` filename so OSV-Scanner recognizes the format. It queries OSV for the package versions in the SBOM; no Cargo.lock or source checkout is needed. Exit code `1` means findings were returned.

{{< /disclosure >}}

## Rapid updates {#updates}

Catalog refreshes run daily and after successful extension builds. Eligible dependency updates are automated after required checks pass; major updates and cases requiring SQL-version review remain manual. [Read the current update policy](https://github.com/cnpg-extensions/postgres-extensions-containers#automated-dependency-updates).

Your CronJob initiates catalog updates at the start of your maintenance window. It does not impose a rollout end time. Catalog-referencing clusters adopt changed image references; SQL extension upgrades can still need an explicit version change or `ALTER EXTENSION … UPDATE`. [Set up monitoring before scheduling updates](../get-started/).

## Upstream OpenSSF Scorecard scans

To reproduce a repository scan with Scorecard v5.6.0, install the release binary
from [OpenSSF](https://github.com/ossf/scorecard/releases/tag/v5.6.0), verify its
release checksum, and supply a GitHub API token through `GITHUB_AUTH_TOKEN`:

```sh
scorecard --repo=https://github.com/pgvector/pgvector --show-details --format=json > pgvector-scorecard.json
```

These checks inspect upstream repository practices, not the installed image.
The original scores and check details are preserved. GitLab scans use
`GITLAB_AUTH_TOKEN`; inaccessible checks remain inconclusive.
