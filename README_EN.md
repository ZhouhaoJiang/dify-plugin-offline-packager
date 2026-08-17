# Dify Plugin Offline Packager

[English](README_EN.md) | [简体中文](README.md)

[![CI](https://github.com/ZhouhaoJiang/dify-plugin-offline-packager/actions/workflows/ci.yml/badge.svg)](https://github.com/ZhouhaoJiang/dify-plugin-offline-packager/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

A version-aware repackaging tool for deploying Dify Python plugins in isolated networks. It builds dependencies inside the target Linux, Python, and CPU runtime, verifies installation without network access, and produces an auditable report.

This is an independently maintained community project and is not an official Dify distribution. Repackaging changes the original Marketplace package. Users are responsible for reviewing the resulting dependency supply chain and managing their own signing keys.

## Supported targets

| Profile | Dify deployment | `linux/amd64` | `linux/arm64` |
| --- | --- | --- | --- |
| `dify-compose-3.9.2` | Docker Compose 3.9.2 | Integration tested | Not tested |
| `dify-compose-3.12.0` | Docker Compose 3.12.0 | Integration tested | Not tested |

See the [compatibility and validation matrix](docs/compatibility.md) for the evidence boundary, older-version differences, and admission criteria. Versions not listed in the matrix must not be treated as compatible by assumption.

## Why profiles are version-specific

Offline compatibility depends on a complete runtime identity:

- Dify and plugin daemon versions;
- Python ABI;
- Linux CPU architecture;
- uv and the daemon dependency-installation path;
- Dify packaging and signing CLI.

For this reason, the repository does not ship four opaque host binaries named after `darwin-amd64`, `darwin-arm64`, `linux-amd64`, and `linux-arm64`. It runs `/app/commandline` from the target daemon image and checks Python, uv, CPU architecture, and the CLI SHA-256 before building. See [architecture and trust boundaries](docs/architecture.md) for details.

## How it works

When a plugin contains both `pyproject.toml` and `uv.lock`, some daemon versions select `uv sync --frozen`. The original lock file may still contain remote URLs, so adding a `wheels/` directory or declaring `no-index` in `pyproject.toml` is not by itself an offline guarantee.

The tool:

1. builds all wheels natively in the target daemon image and CPU architecture;
2. generates a fully pinned `requirements.txt` that references only `./wheels`;
3. removes `pyproject.toml` and `uv.lock` from the output to select the requirements installation path;
4. packages and optionally signs with the Dify CLI included in the target image;
5. reinstalls dependencies in a `--network none` container before publishing the artifact;
6. records input and output SHA-256 values, image identity and digest, CLI hash, Python, uv, and the dependency inventory.

## Prerequisites

- Docker Engine or Docker Desktop;
- access to the selected Python package index during the build phase;
- access to pull the target Dify plugin daemon image;
- a Python plugin `.difypkg` as input.

The host may run macOS. `--platform linux/amd64` or `linux/arm64` selects the actual container architecture used to build wheels.

## Build in GitHub Actions after forking

Fork owners can perform download, runtime inspection, packaging, signing, and no-network verification entirely from the GitHub UI, without installing Docker locally.

### 1. Fork and enable the workflow

1. Fork this repository;
2. open the fork's **Actions** page and enable workflows;
3. select **Build offline package**, then click **Run workflow**.

A fork never inherits Actions Secrets from the upstream repository. The build uses only download locations and keys configured by the current fork owner.

### 2. Prepare the source URL and hash

`workflow_dispatch` cannot upload a local file. The source `.difypkg` must therefore be downloadable over HTTPS by a GitHub-hosted runner. Calculate the input SHA-256 locally first:

```bash
# macOS
shasum -a 256 plugin.difypkg

# Linux
sha256sum plugin.difypkg
```

A public download URL can be entered in `package_url`. Do not place a private or presigned URL in a visible workflow input; store it as a Repository Secret in the fork:

```bash
printf '%s' 'https://storage.example.com/private/plugin.difypkg?...' \
  | gh secret set DIFY_PLUGIN_PACKAGE_URL
```

If the source is reachable only from an isolated network, use the local CLI or a reviewed self-hosted runner. Never commit a customer package to a public fork.

### 3. Complete the Run workflow form

| Input | Value |
| --- | --- |
| `package_url` | Public HTTPS URL; leave empty when using the `DIFY_PLUGIN_PACKAGE_URL` secret |
| `package_filename` | Output label such as `langgenius-openai_api_compatible_0.0.59.difypkg`; it does not upload a local file |
| `package_sha256` | Full 64-character SHA-256 of the source; a mismatch stops the run |
| `profile` | Must match the target Dify deployment version |
| `architecture` | Linux CPU architecture of plugin daemon, not the browser or local computer |
| `signing_mode` | Use `ephemeral` for a first run; use `repository-secrets` for a reusable organization key |
| `index_url` | Public Python package index; use the `DIFY_PYPI_INDEX_URL` secret for a private index |

`ephemeral` creates a new temporary private key for each run and deletes it before artifact upload. The artifact contains only the corresponding public key. The target Dify deployment must trust that newly generated public key for each run.

For one organization key shared across multiple package builds, generate the pair in a controlled environment outside the repository checkout:

```bash
mkdir -p ../dify-offline-packager-keys

./dify-offline-packager keygen \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --output-dir ../dify-offline-packager-keys

base64 < ../dify-offline-packager-keys/offline-packager.private.pem \
  | tr -d '\n' | gh secret set DIFY_PLUGIN_PRIVATE_KEY_B64

base64 < ../dify-offline-packager-keys/offline-packager.public.pem \
  | tr -d '\n' | gh secret set DIFY_PLUGIN_PUBLIC_KEY_B64
```

Then select `repository-secrets`. The Action never uploads the private key; it includes the public key in every artifact for deployment-side comparison.

### 4. Download and deploy the result

After a successful run, download the `dify-offline-*` item under **Artifacts**. It contains:

- `*-offline-linux-*.difypkg`: the offline plugin package to upload to Dify;
- `*.difypkg.report.json`: runtime identity, dependency, signing, and no-network evidence;
- `offline-packager.public.pem`: the public key the target Dify deployment must trust;
- `SHA256SUMS` and `NEXT_STEPS.md`: integrity checks and next steps.

Artifacts are retained for 7 days by default. Configure and verify the public key using the [Compose override example](deploy/docker-compose.third-party-signatures.yaml), then upload `*-offline-linux-*.difypkg`, not the original source package.

The ability to execute a `linux/arm64` Action does not grant that architecture an integration-tested status. The [compatibility and validation matrix](docs/compatibility.md) remains authoritative.

## Local CLI quick start

List the declared runtime profiles first:

```bash
./dify-offline-packager profiles
```

Every command that launches a container requires an explicit `--profile`. The tool never guesses a Dify version.

Inspect the target runtime:

```bash
./dify-offline-packager doctor \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64
```

Generate a signing key pair owned by your organization:

```bash
mkdir -p ../dify-offline-packager-keys

./dify-offline-packager keygen \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --output-dir ../dify-offline-packager-keys
```

Keep the private key only in the controlled build environment. The Dify server needs only the public key.

Build, sign, and verify without network access:

```bash
./dify-offline-packager pack ./plugin.difypkg \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --index-url https://pypi.org/simple \
  --private-key ../dify-offline-packager-keys/offline-packager.private.pem \
  --public-key ../dify-offline-packager-keys/offline-packager.public.pem
```

Successful execution produces:

- `*-offline-linux-amd64.difypkg`: the repackaged plugin;
- `*.difypkg.report.json`: runtime identity, dependencies, signing status, and offline-verification evidence.

The command returns success only after a fresh installation completes without network access.

## Private container registries

When the target image is mirrored to an internal registry, select the matching profile and override only the image reference:

```bash
./dify-offline-packager doctor \
  --profile dify-compose-3.9.2 \
  --platform linux/amd64 \
  --runtime-image registry.example.com/dify-plugin-daemon:3.9.2
```

An override changes the report status to `custom-runtime-not-validated`. A successful live probe confirms basic runtime identity but does not inherit the built-in integration-test claim.

## Independent verification

Repeat the offline dependency installation:

```bash
./dify-offline-packager verify ./plugin-offline-linux-amd64.difypkg \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64
```

Verify the third-party signature:

```bash
./dify-offline-packager verify-signature ./plugin-offline-linux-amd64.difypkg \
  --profile dify-compose-3.12.0 \
  --platform linux/amd64 \
  --public-key ../dify-offline-packager-keys/offline-packager.public.pem
```

The [Compose override example](deploy/docker-compose.third-party-signatures.yaml) shows how to mount the public key. Compare every environment variable with the target Dify version and run `docker compose ... config` before applying it. Never mount the private key on the Dify server.

## Security boundaries

- Building a Python sdist executes third-party build code. Use a dedicated worker and do not mount the Docker socket, host home directory, or unrelated credentials.
- When an Action uses a private Python index, build code can read that index URL. Use only a least-privilege, read-only, revocable download credential.
- Do not place a private package URL in a visible workflow input, and never commit source packages, private keys, or credentials to a public fork.
- The private key is mounted only in a separate `--network none` signing container, followed immediately by public-key verification.
- A successful offline installation is not a plugin business-function test or a dependency vulnerability scan.
- The default extracted-size limit is 50 MB. Check the target Dify package limit before changing `--max-size-mb`.
- Omitting signing keys produces an unsigned package, which a signature-enforcing deployment will reject. Do not disable global signature verification to install one package.

Report security issues privately according to the [Security Policy](SECURITY.md).

## Development

```bash
python3 -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

Runtime profiles live in [`config/runtime-profiles.json`](config/runtime-profiles.json). New profiles must satisfy the [compatibility admission criteria](docs/compatibility.md#新增版本的准入门槛); copying an image tag is not sufficient.

## License

Apache License 2.0. The Dify name and related trademarks belong to their respective owners.
