# Changelog

All notable changes to this project are documented here. The project follows Semantic Versioning while it remains pre-1.0.

## [Unreleased]

### Changed

- Name each GitHub Actions Artifact after its generated offline package instead of the runtime profile and workflow run number.

## [0.4.0] - 2026-08-17

### Added

- Fork-friendly `Build offline package` manual GitHub Actions workflow.
- Public URL and repository-secret source download modes with mandatory SHA-256 verification.
- Ephemeral and reusable organization signing-key modes; artifacts contain only the public key.
- Bilingual GitHub Actions tutorials, workflow security tests, and checksum-pinned actionlint CI.

### Security

- Limit the source mounted into build and verification containers to `src/`, preventing repository-level keys and checkout metadata from becoming readable inside the plugin build container.
- Run containers with the host runner UID/GID so protected bind mounts work consistently without making key directories globally writable.

## [0.3.0] - 2026-08-17

### Added

- Complete Chinese and English README documentation.

### Changed

- Renamed runtime profiles to deployment-focused `dify-compose-*` identifiers.
- Removed the unused deployment-category field from profile configuration and audit output.
- Updated public wording to describe Dify Docker Compose versions without product-tier labels.

## [0.2.0] - 2026-08-17

### Added

- Versioned runtime profiles for Dify Docker Compose 3.9.2 and 3.12.0.
- `profiles` and `doctor` commands.
- Runtime checks for CPU architecture, Python, uv, Dify CLI presence, and CLI SHA-256.
- Explicit compatibility, architecture, security, and contribution documentation.
- CI matrices for Python 3.10, 3.12, and 3.13 with pinned Ruff checks.

### Changed

- Removed the Dify 3.12 hardcoding from the worker.
- Renamed the GitHub Actions workflow from `test.yml` to `ci.yml`.
- Custom runtime overrides now lose the built-in validation claim in audit reports.
- Runtime profile selection is mandatory; commands no longer silently assume one Dify version.

## [0.1.0] - 2026-08-17

- Initial Dify Docker Compose 3.12.0 offline packaging implementation.
