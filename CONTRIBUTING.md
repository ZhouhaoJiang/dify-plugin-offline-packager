# Contributing

## Development checks

```bash
python3 -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
```

Use focused commits and keep generated `.difypkg`, reports, caches, and private keys out of Git.

## Runtime profile changes

A new Dify version is not accepted from image naming alone. Follow the admission checklist in [docs/compatibility.md](docs/compatibility.md), attach sanitized `doctor` and end-to-end reports to the pull request, and mark every untested architecture as `not-tested`.

Do not commit downloaded or locally built Dify CLI binaries. If an older runtime lacks `/app/commandline`, propose a reproducible source build tied to an upstream tag and document the compatibility proof.
