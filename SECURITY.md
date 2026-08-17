# Security Policy

## Supported versions

Security fixes are applied to the latest release on `main`. Runtime compatibility is tracked separately in [docs/compatibility.md](docs/compatibility.md).

## Reporting a vulnerability

Please use this repository's GitHub private vulnerability reporting or Security Advisory feature. Do not publish signing keys, customer packages, credentials, exploit details, or customer data in a public issue.

Include the affected release, runtime profile, target architecture, a minimal reproduction, and whether the issue can expose the host, signing key, package contents, or generated artifact.

## Operational guidance

- Keep private signing keys outside the repository and the Dify server.
- Forks do not inherit upstream Actions Secrets. Configure secrets only in the fork that runs the build, keep private package URLs out of visible workflow inputs, and never upload a private signing key as an artifact.
- A private Python index credential is visible to dependency build code. Use a scoped, read-only, revocable token and no unrelated credentials on the runner.
- Review the build report's image identity and CLI SHA-256 before distributing a package.
- Treat source distributions as executable build input. Run builds on a dedicated worker without a Docker socket, home-directory mount, or unrelated credentials.
- Do not treat offline installation as a dependency vulnerability scan.
