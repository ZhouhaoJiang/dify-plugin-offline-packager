#!/usr/bin/env python3
"""Build and verify Dify offline plugin packages inside the target runtime image."""

from __future__ import annotations

import argparse
import hashlib
import json
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile


PYTHON = "python3.12"
UV = "uv"
PACKAGE_CLI = "/app/commandline"
ONLINE_REQUIREMENT_OPTIONS = (
    "--index-url",
    "--extra-index-url",
    "--trusted-host",
    "--find-links",
    "--no-index",
    "-i",
    "-f",
)


class PackagerError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[offline-packager] {message}", flush=True)


def run(command: list[str], *, cwd: Path | None = None) -> None:
    log("running: " + " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_extract(package: Path, destination: Path, max_uncompressed_bytes: int) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with zipfile.ZipFile(package) as archive:
        members = archive.infolist()
        if len(members) > 100_000:
            raise PackagerError("package contains too many archive entries")

        for member in members:
            if "\\" in member.filename:
                raise PackagerError(f"unsafe archive path: {member.filename!r}")
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise PackagerError(f"unsafe archive path: {member.filename!r}")

            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PackagerError(f"symbolic links are not accepted: {member.filename!r}")

            total += member.file_size
            if total > max_uncompressed_bytes:
                raise PackagerError("package exceeds the configured uncompressed size limit")

            target = destination.joinpath(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            if mode:
                target.chmod(mode & 0o777)


def clean_staging(staging: Path) -> None:
    for relative in (".venv", "wheels", ".git"):
        candidate = staging / relative
        if candidate.is_dir():
            shutil.rmtree(candidate)
        elif candidate.exists():
            candidate.unlink()

    verification = staging / ".verification.dify.json"
    if verification.exists():
        verification.unlink()

    for directory in list(staging.rglob("*")):
        if directory.is_dir() and directory.name in {
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
        }:
            shutil.rmtree(directory)
    for bytecode in list(staging.rglob("*.py[co]")):
        bytecode.unlink()


def validate_python_plugin(staging: Path) -> None:
    manifest = staging / "manifest.yaml"
    if not manifest.is_file():
        raise PackagerError("manifest.yaml is missing")
    text = manifest.read_text(encoding="utf-8")
    runner = re.search(r"runner:\s*(.*?)(?:\n\S|\Z)", text, flags=re.DOTALL)
    if not runner or not re.search(r"language:\s*['\"]?python['\"]?", runner.group(1)):
        raise PackagerError("only Python plugins are supported")
    if not re.search(r"version:\s*['\"]?3\.12(?:\.[0-9]+)?['\"]?", runner.group(1)):
        raise PackagerError("the selected Dify 3.12 runtime requires a Python 3.12 plugin")


def strip_online_requirement_options(content: str) -> str:
    result: list[str] = []
    skip_value = False
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if skip_value:
            skip_value = False
            continue
        if not stripped or stripped.startswith("#"):
            result.append(raw_line)
            continue

        matched = False
        for option in ONLINE_REQUIREMENT_OPTIONS:
            if stripped == option:
                skip_value = option != "--no-index"
                matched = True
                break
            if stripped.startswith(option + "=") or stripped.startswith(option + " "):
                matched = True
                break
        if not matched:
            result.append(raw_line)
    return "\n".join(result).strip() + "\n"


def prepare_build_requirements(staging: Path) -> Path:
    output = staging / ".offline-build-requirements.txt"
    requirements = staging / "requirements.txt"
    pyproject = staging / "pyproject.toml"

    if requirements.is_file():
        output.write_text(
            strip_online_requirement_options(requirements.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        return output

    if not pyproject.is_file():
        raise PackagerError("neither requirements.txt nor pyproject.toml was found")

    run(
        [
            UV,
            "export",
            "--no-config",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--no-editable",
            "--python",
            PYTHON,
            "--output-file",
            output.name,
        ],
        cwd=staging,
    )
    output.write_text(
        strip_online_requirement_options(output.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return output


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_pins(wheel_directory: Path) -> list[str]:
    packages: dict[str, tuple[str, str]] = {}
    for wheel in sorted(wheel_directory.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
                and len(PurePosixPath(name).parts) == 2
            ]
            if len(metadata_names) != 1:
                raise PackagerError(f"cannot identify wheel metadata: {wheel.name}")
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        name = metadata.get("Name")
        version = metadata.get("Version")
        if not name or not version:
            raise PackagerError(f"wheel metadata is incomplete: {wheel.name}")
        key = canonical_name(name)
        current = packages.get(key)
        if current and current[1] != version:
            raise PackagerError(
                f"multiple versions were built for {name}: {current[1]} and {version}"
            )
        packages[key] = (name, version)
    return [f"{packages[key][0]}=={packages[key][1]}" for key in sorted(packages)]


def make_difyignore_wheel_safe(staging: Path) -> None:
    ignore = staging / ".difyignore"
    if not ignore.exists():
        return
    retained = []
    for line in ignore.read_text(encoding="utf-8").splitlines():
        if "wheel" in line.strip().lower():
            continue
        retained.append(line)
    ignore.write_text("\n".join(retained).rstrip() + "\n", encoding="utf-8")


def package_members(package: Path) -> set[str]:
    with zipfile.ZipFile(package) as archive:
        return set(archive.namelist())


def validate_built_package(package: Path, expected_wheels: int, signed: bool) -> None:
    members = package_members(package)
    if "manifest.yaml" not in members or "requirements.txt" not in members:
        raise PackagerError("built package is missing manifest.yaml or requirements.txt")
    if "pyproject.toml" in members or "uv.lock" in members:
        raise PackagerError("built package would still select uv sync")
    wheel_count = sum(name.startswith("wheels/") and name.endswith(".whl") for name in members)
    if wheel_count != expected_wheels:
        raise PackagerError(
            f"built package contains {wheel_count} wheels, expected {expected_wheels}"
        )
    has_verification = ".verification.dify.json" in members
    if has_verification != signed:
        raise PackagerError("package signature metadata does not match the requested mode")


def build(args: argparse.Namespace) -> None:
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    staging = Path(args.workdir).resolve() / "staging"
    if staging.exists():
        shutil.rmtree(staging)

    log("extracting and validating the source package")
    safe_extract(source, staging, args.max_size_mb * 1024 * 1024)
    clean_staging(staging)
    validate_python_plugin(staging)

    build_requirements = prepare_build_requirements(staging)
    wheels = staging / "wheels"
    wheels.mkdir()
    log("building dependency wheels inside the target runtime")
    run(
        [
            PYTHON,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--prefer-binary",
            "--wheel-dir",
            str(wheels),
            "-r",
            build_requirements.name,
        ],
        cwd=staging,
    )

    pins = wheel_pins(wheels)
    requirements = staging / "requirements.txt"
    requirements.write_text(
        "--no-index\n--find-links=./wheels\n\n" + "\n".join(pins) + "\n",
        encoding="utf-8",
    )

    build_requirements.unlink()
    for dependency_file in (staging / "pyproject.toml", staging / "uv.lock"):
        if dependency_file.exists():
            dependency_file.unlink()
    make_difyignore_wheel_safe(staging)

    if output.exists():
        output.unlink()
    log("packaging with the Dify 3.12 command-line packager")
    run(
        [
            PACKAGE_CLI,
            "plugin",
            "package",
            str(staging),
            "--output_path",
            str(output),
            "--max-size",
            str(args.max_size_mb),
        ]
    )

    validate_built_package(output, len(pins), signed=False)
    report = {
        "source_sha256": sha256_file(source),
        "package_sha256": sha256_file(output),
        "package_size_bytes": output.stat().st_size,
        "python": capture([PYTHON, "--version"]),
        "uv": capture([UV, "--version"]),
        "dependency_count": len(pins),
        "dependencies": pins,
        "signed": False,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log(f"built {len(pins)} wheels")


def verify(args: argparse.Namespace) -> None:
    package = Path(args.input).resolve()
    staging = Path(args.workdir).resolve() / "verify"
    if staging.exists():
        shutil.rmtree(staging)
    safe_extract(package, staging, args.max_size_mb * 1024 * 1024)

    members = package_members(package)
    if "requirements.txt" not in members:
        raise PackagerError("requirements.txt is missing")
    if "pyproject.toml" in members or "uv.lock" in members:
        raise PackagerError("package is not requirements-only")
    requirements = (staging / "requirements.txt").read_text(encoding="utf-8")
    if "--no-index" not in requirements or "--find-links=./wheels" not in requirements:
        raise PackagerError("requirements.txt does not enforce local wheel installation")

    run([UV, "venv", "--clear", ".venv", "--python", "3.12"], cwd=staging)
    run([UV, "pip", "install", "--link-mode=copy", "-r", "requirements.txt"], cwd=staging)
    run(
        [
            str(staging / ".venv/bin/python"),
            "-m",
            "compileall",
            "-q",
            "-x",
            r"(^|/)\.venv/",
            ".",
        ],
        cwd=staging,
    )
    Path(args.report).write_text(
        json.dumps({"offline_verified": True, "package_sha256": sha256_file(package)}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    log("offline dependency installation passed")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    subcommands = root.add_subparsers(dest="command", required=True)

    build_parser = subcommands.add_parser("build")
    build_parser.add_argument("--input", required=True)
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--workdir", required=True)
    build_parser.add_argument("--report", required=True)
    build_parser.add_argument("--max-size-mb", type=int, default=50)
    build_parser.set_defaults(handler=build)

    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--input", required=True)
    verify_parser.add_argument("--workdir", required=True)
    verify_parser.add_argument("--report", required=True)
    verify_parser.add_argument("--max-size-mb", type=int, default=50)
    verify_parser.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (PackagerError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
