# Changelog

All notable changes to this project are documented here. The project follows Semantic Versioning while it remains pre-1.0.

## [Unreleased]

## [0.2.0] - 2026-08-17

### Added

- Versioned runtime profiles for Dify Enterprise Compose 3.9.2 and 3.12.0.
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

- Initial Dify Enterprise Compose 3.12.0 offline packaging implementation.
