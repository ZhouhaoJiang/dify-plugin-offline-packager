#!/usr/bin/env python3
"""Host-side CLI for building version-aware Dify offline plugin packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from profiles import ProfileError, RuntimeSelection, load_catalog, select_runtime


ROOT = Path(__file__).resolve().parent.parent
WORKER_SOURCE = ROOT / "src"
CATALOG = load_catalog()
VERSION = "0.4.0"


class CliError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, environment: dict[str, str] | None = None) -> None:
    subprocess.run(command, check=True, env=environment)


def require_docker() -> None:
    if not shutil.which("docker"):
        raise CliError("docker is required")
    subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def docker_security_args(platform: str, network: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--platform",
        platform,
        "--network",
        network,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--env",
        "HOME=/work/home",
        "--env",
        "TMPDIR=/work/tmp",
        "--env",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
        "--env",
        "PIP_ROOT_USER_ACTION=ignore",
        "--env",
        "UV_CACHE_DIR=/work/uv-cache",
    ]


def volume(path: Path, container_path: str, read_only: bool = False) -> str:
    suffix = ":ro" if read_only else ""
    return f"{path.resolve()}:{container_path}{suffix}"


def default_output(input_path: Path, platform: str) -> Path:
    architecture = platform.split("/", 1)[1]
    return input_path.with_name(f"{input_path.stem}-offline-linux-{architecture}.difypkg")


def image_identity(image: str) -> dict[str, object]:
    raw = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{json .}}"], text=True
    )
    data = json.loads(raw)
    return {
        "reference": image,
        "id": data.get("Id"),
        "architecture": data.get("Architecture"),
        "repo_digests": data.get("RepoDigests", []),
    }


def runtime_selection(args: argparse.Namespace) -> RuntimeSelection:
    return select_runtime(
        CATALOG,
        args.profile,
        runtime_image=args.runtime_image,
        python_executable=args.python_executable,
        uv_executable=args.uv_executable,
        package_cli=args.package_cli,
    )


def profile_payload(selection: RuntimeSelection, platform: str) -> dict[str, object]:
    profile = selection.profile
    return {
        "name": profile.name,
        "display_name": profile.display_name,
        "dify_version": profile.dify_version,
        "deployment": profile.deployment,
        "support_status": profile.support_status,
        "expected_image_digest": profile.image_digest,
        "customized": selection.customized,
        "declared_platform_validation": selection.validation(platform),
    }


def probe_runtime(selection: RuntimeSelection, platform: str) -> dict[str, object]:
    profile = selection.profile
    probe = r"""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys

package_cli = sys.argv[1]
uv_name = sys.argv[2]
uv_path = shutil.which(uv_name)
cli_exists = os.path.isfile(package_cli) and os.access(package_cli, os.X_OK)
cli_sha256 = None
if cli_exists:
    digest = hashlib.sha256()
    with open(package_cli, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    cli_sha256 = digest.hexdigest()
uv_version = None
if uv_path:
    uv_version = subprocess.check_output([uv_path, "--version"], text=True).strip()
print(json.dumps({
    "python_executable": sys.executable,
    "python_version": platform.python_version(),
    "machine": platform.machine(),
    "uv_path": uv_path,
    "uv_version": uv_version,
    "package_cli": package_cli,
    "package_cli_exists": cli_exists,
    "package_cli_sha256": cli_sha256,
}))
"""
    command = docker_security_args(platform, "none")
    command.extend(
        [
            "--entrypoint",
            profile.python_executable,
            profile.runtime_image,
            "-c",
            probe,
            profile.package_cli,
            profile.uv_executable,
        ]
    )
    raw = subprocess.check_output(command, text=True)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CliError(f"runtime probe returned invalid JSON: {raw!r}") from error
    result["runtime_image"] = profile.runtime_image
    result["platform"] = platform
    return result


def runtime_errors(
    selection: RuntimeSelection,
    platform: str,
    probe: dict[str, object],
    *,
    require_cli: bool,
    identity: dict[str, object] | None = None,
) -> list[str]:
    profile = selection.profile
    errors: list[str] = []
    actual_python = str(probe.get("python_version", ""))
    if not (
        actual_python == profile.python_version
        or actual_python.startswith(profile.python_version + ".")
    ):
        errors.append(
            f"profile requires Python {profile.python_version}, image provides "
            f"{actual_python or 'unknown'}"
        )
    if not probe.get("uv_path"):
        errors.append(f"uv executable {profile.uv_executable!r} was not found")
    if require_cli and not probe.get("package_cli_exists"):
        errors.append(
            f"Dify package CLI {profile.package_cli!r} was not found or is not executable"
        )

    evidence = selection.validation(platform)
    expected_cli_hash = evidence.get("observed_cli_sha256")
    actual_cli_hash = probe.get("package_cli_sha256")
    if require_cli and expected_cli_hash and actual_cli_hash != expected_cli_hash:
        errors.append(
            "Dify package CLI hash differs from the integration-tested runtime profile "
            f"(expected {expected_cli_hash}, got {actual_cli_hash or 'missing'})"
        )
    expected_machine = {"linux/amd64": "x86_64", "linux/arm64": "aarch64"}.get(platform)
    if expected_machine and probe.get("machine") != expected_machine:
        errors.append(
            f"requested {platform}, but the container reports machine {probe.get('machine')!r}"
        )
    if identity is not None and not selection.customized:
        repo_digests = identity.get("repo_digests", [])
        actual_digests = {
            str(item).rsplit("@", 1)[-1]
            for item in repo_digests
            if isinstance(item, str) and "@" in item
        }
        if profile.image_digest not in actual_digests:
            errors.append(
                "runtime image digest differs from the integration-tested profile "
                f"(expected {profile.image_digest}, got {sorted(actual_digests) or ['missing']})"
            )
    return errors


def inspect_runtime(
    selection: RuntimeSelection,
    platform: str,
    *,
    require_cli: bool,
) -> dict[str, object]:
    probe = probe_runtime(selection, platform)
    identity = image_identity(selection.profile.runtime_image)
    errors = runtime_errors(
        selection,
        platform,
        probe,
        require_cli=require_cli,
        identity=identity,
    )
    probe["compatible"] = not errors
    probe["errors"] = errors
    probe["image_identity"] = identity
    if errors:
        raise CliError("runtime profile check failed: " + "; ".join(errors))
    return probe


def worker_runtime_arguments(selection: RuntimeSelection) -> list[str]:
    profile = selection.profile
    return [
        "--python",
        profile.python_executable,
        "--uv",
        profile.uv_executable,
        "--package-cli",
        profile.package_cli,
    ]


def sign_package(
    package: Path,
    private_key: Path,
    public_key: Path,
    *,
    platform: str,
    selection: RuntimeSelection,
) -> None:
    profile = selection.profile
    signing_directory = package.parent / "signing"
    if signing_directory.exists():
        shutil.rmtree(signing_directory)
    signing_directory.mkdir()
    signing_input = signing_directory / package.name
    shutil.copy2(package, signing_input)

    sign_command = docker_security_args(platform, "none")
    sign_command.extend(
        [
            "--volume",
            volume(signing_directory, "/signing"),
            "--volume",
            volume(private_key, "/keys/signing.private.pem", True),
            "--entrypoint",
            profile.package_cli,
            profile.runtime_image,
            "signature",
            "sign",
            f"/signing/{package.name}",
            "--private_key",
            "/keys/signing.private.pem",
            "--authorized_category",
            "community",
        ]
    )
    run(sign_command)
    signed = signing_input.with_name(f"{package.stem}.signed{package.suffix}")
    if not signed.is_file():
        raise CliError("the Dify signer did not produce the expected output")
    os.replace(signed, package)

    verify_command = docker_security_args(platform, "none")
    verify_command.extend(
        [
            "--volume",
            volume(package, "/input/plugin.difypkg", True),
            "--volume",
            volume(public_key, "/keys/signing.public.pem", True),
            "--entrypoint",
            profile.package_cli,
            profile.runtime_image,
            "signature",
            "verify",
            "/input/plugin.difypkg",
            "--public_key",
            "/keys/signing.public.pem",
        ]
    )
    run(verify_command)


def pack(args: argparse.Namespace) -> None:
    require_docker()
    selection = runtime_selection(args)
    profile = selection.profile
    runtime_probe = inspect_runtime(selection, args.platform, require_cli=True)

    source = Path(args.input).expanduser().resolve()
    if not source.is_file():
        raise CliError(f"input package does not exist: {source}")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else default_output(source, args.platform)
    )
    if source == output:
        raise CliError("output must differ from the input package")
    if output.exists() and not args.force:
        raise CliError(f"output already exists (use --force to replace it): {output}")

    if bool(args.private_key) != bool(args.public_key):
        raise CliError("--private-key and --public-key must be supplied together")

    private_key: Path | None = None
    public_key: Path | None = None
    if args.private_key and args.public_key:
        private_key = Path(args.private_key).expanduser().resolve()
        public_key = Path(args.public_key).expanduser().resolve()
        if not private_key.is_file():
            raise CliError(f"private key does not exist: {private_key}")
        if not public_key.is_file():
            raise CliError(f"public key does not exist: {public_key}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dify-offline-packager-") as temporary:
        work = Path(temporary)
        (work / "home").mkdir()
        (work / "tmp").mkdir()
        input_copy = work / "input.difypkg"
        built = work / "output.difypkg"
        build_report = work / "build-report.json"
        verify_report = work / "verify-report.json"
        shutil.copy2(source, input_copy)

        command = docker_security_args(args.platform, "bridge")
        command.extend(
            [
                "--volume",
                volume(WORKER_SOURCE, "/tool/src", read_only=True),
                "--volume",
                volume(work, "/work"),
                "--env",
                "PIP_INDEX_URL",
                "--env",
                "UV_INDEX_URL",
            ]
        )
        worker_arguments = [
            "/tool/src/container_worker.py",
            "build",
            "--input",
            "/work/input.difypkg",
            "--output",
            "/work/output.difypkg",
            "--workdir",
            "/work/build",
            "--report",
            "/work/build-report.json",
            "--max-size-mb",
            str(args.max_size_mb),
            *worker_runtime_arguments(selection),
        ]
        command.extend(
            ["--entrypoint", profile.python_executable, profile.runtime_image, *worker_arguments]
        )
        build_environment = os.environ.copy()
        build_environment["PIP_INDEX_URL"] = args.index_url
        build_environment["UV_INDEX_URL"] = args.index_url
        run(command, environment=build_environment)

        if private_key and public_key:
            sign_package(
                built,
                private_key,
                public_key,
                platform=args.platform,
                selection=selection,
            )

        verify_command = docker_security_args(args.platform, "none")
        verify_command.extend(
            [
                "--volume",
                volume(WORKER_SOURCE, "/tool/src", read_only=True),
                "--volume",
                volume(work, "/work"),
                "--entrypoint",
                profile.python_executable,
                profile.runtime_image,
                "/tool/src/container_worker.py",
                "verify",
                "--input",
                "/work/output.difypkg",
                "--workdir",
                "/work/offline-verify",
                "--report",
                "/work/verify-report.json",
                "--max-size-mb",
                str(args.max_size_mb),
                *worker_runtime_arguments(selection),
            ]
        )
        run(verify_command)

        container_report = json.loads(build_report.read_text(encoding="utf-8"))
        container_report["signed"] = bool(private_key)
        offline_report = json.loads(verify_report.read_text(encoding="utf-8"))
        if not offline_report.get("offline_verified"):
            raise CliError("offline verification did not pass")

        temporary_output = output.with_name(f".{output.name}.tmp")
        shutil.copy2(built, temporary_output)
        os.replace(temporary_output, output)
        report = {
            **container_report,
            "source": str(source),
            "output": str(output),
            "package_sha256": sha256_file(output),
            "package_size_bytes": output.stat().st_size,
            "platform": args.platform,
            "profile": profile_payload(selection, args.platform),
            "runtime_image": runtime_probe["image_identity"],
            "runtime_probe": runtime_probe,
            "index_host": urlsplit(args.index_url).hostname,
            "offline_verified": True,
        }
        if public_key:
            report["public_key_sha256"] = sha256_file(public_key)
        report_path = output.with_suffix(output.suffix + ".report.json")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"package: {output}")
    print(f"sha256:  {sha256_file(output)}")
    print(f"report:  {report_path}")


def offline_verify(args: argparse.Namespace) -> None:
    require_docker()
    selection = runtime_selection(args)
    profile = selection.profile
    inspect_runtime(selection, args.platform, require_cli=False)

    package = Path(args.input).expanduser().resolve()
    if not package.is_file():
        raise CliError(f"package does not exist: {package}")
    with tempfile.TemporaryDirectory(prefix="dify-offline-verify-") as temporary:
        work = Path(temporary)
        (work / "home").mkdir()
        (work / "tmp").mkdir()
        shutil.copy2(package, work / "input.difypkg")
        command = docker_security_args(args.platform, "none")
        command.extend(
            [
                "--volume",
                volume(ROOT, "/tool", read_only=True),
                "--volume",
                volume(work, "/work"),
                "--entrypoint",
                profile.python_executable,
                profile.runtime_image,
                "/tool/src/container_worker.py",
                "verify",
                "--input",
                "/work/input.difypkg",
                "--workdir",
                "/work/offline-verify",
                "--report",
                "/work/verify-report.json",
                "--max-size-mb",
                str(args.max_size_mb),
                *worker_runtime_arguments(selection),
            ]
        )
        run(command)
    print(f"offline verification passed: {package}")


def keygen(args: argparse.Namespace) -> None:
    require_docker()
    selection = runtime_selection(args)
    profile = selection.profile
    inspect_runtime(selection, args.platform, require_cli=True)

    output_directory = Path(args.output_dir).expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    private_key = output_directory / f"{args.name}.private.pem"
    public_key = output_directory / f"{args.name}.public.pem"
    if private_key.exists() or public_key.exists():
        raise CliError("refusing to overwrite an existing key pair")

    command = docker_security_args(args.platform, "none")
    command.extend(
        [
            "--volume",
            volume(output_directory, "/keys"),
            "--workdir",
            "/keys",
            "--entrypoint",
            profile.package_cli,
            profile.runtime_image,
            "signature",
            "generate",
            "--filename",
            args.name,
        ]
    )
    run(command)
    private_key.chmod(0o600)
    public_key.chmod(0o644)
    print(f"private key (keep offline): {private_key}")
    print(f"public key:                {public_key}")


def signature_verify(args: argparse.Namespace) -> None:
    require_docker()
    selection = runtime_selection(args)
    profile = selection.profile
    inspect_runtime(selection, args.platform, require_cli=True)

    package = Path(args.input).expanduser().resolve()
    public_key = Path(args.public_key).expanduser().resolve()
    if not package.is_file() or not public_key.is_file():
        raise CliError("package and public key must both exist")
    command = docker_security_args(args.platform, "none")
    command.extend(
        [
            "--volume",
            volume(package, "/input/plugin.difypkg", True),
            "--volume",
            volume(public_key, "/keys/signing.public.pem", True),
            "--entrypoint",
            profile.package_cli,
            profile.runtime_image,
            "signature",
            "verify",
            "/input/plugin.difypkg",
            "--public_key",
            "/keys/signing.public.pem",
        ]
    )
    run(command)
    print("signature verification passed")


def doctor(args: argparse.Namespace) -> None:
    require_docker()
    selection = runtime_selection(args)
    probe = probe_runtime(selection, args.platform)
    identity = image_identity(selection.profile.runtime_image)
    errors = runtime_errors(
        selection,
        args.platform,
        probe,
        require_cli=True,
        identity=identity,
    )
    result = {
        "compatible": not errors,
        "errors": errors,
        "profile": profile_payload(selection, args.platform),
        "runtime_image": identity,
        "runtime_probe": probe,
    }
    print(json.dumps(result, indent=2))
    if errors:
        raise CliError("runtime profile check failed")


def list_profiles(args: argparse.Namespace) -> None:
    if args.json:
        payload = {
            "profiles": [
                {
                    "name": profile.name,
                    "display_name": profile.display_name,
                    "dify_version": profile.dify_version,
                    "runtime_image": profile.runtime_image,
                    "image_digest": profile.image_digest,
                    "support_status": profile.support_status,
                    "platforms": profile.platforms,
                }
                for profile in CATALOG.profiles.values()
            ],
        }
        print(json.dumps(payload, indent=2))
        return

    print("PROFILE             DIFY      AMD64               ARM64       RUNTIME IMAGE")
    for profile in CATALOG.profiles.values():
        amd64 = profile.platform_status("linux/amd64")["status"]
        arm64 = profile.platform_status("linux/arm64")["status"]
        print(
            f"{profile.name:<19} {profile.dify_version:<9} "
            f"{amd64:<19} {arm64:<11} {profile.runtime_image}"
        )


def add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", choices=("linux/amd64", "linux/arm64"), required=True)
    parser.add_argument(
        "--profile",
        choices=tuple(CATALOG.profiles),
        required=True,
        help="target Dify runtime profile; explicit selection is required",
    )
    parser.add_argument(
        "--runtime-image",
        "--image",
        dest="runtime_image",
        help="override the profile image; the report will mark the runtime as custom",
    )
    parser.add_argument("--python-executable", help=argparse.SUPPRESS)
    parser.add_argument("--uv-executable", help=argparse.SUPPRESS)
    parser.add_argument("--package-cli", help=argparse.SUPPRESS)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="dify-offline-packager",
        description="Build and verify Python plugins for versioned Dify offline runtimes.",
    )
    root.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subcommands = root.add_subparsers(dest="command", required=True)

    profiles_parser = subcommands.add_parser("profiles", help="list supported runtime profiles")
    profiles_parser.add_argument("--json", action="store_true")
    profiles_parser.set_defaults(handler=list_profiles)

    doctor_parser = subcommands.add_parser("doctor", help="inspect a target runtime image")
    add_runtime_options(doctor_parser)
    doctor_parser.set_defaults(handler=doctor)

    pack_parser = subcommands.add_parser("pack", help="build and offline-verify a package")
    pack_parser.add_argument("input")
    pack_parser.add_argument("--output")
    pack_parser.add_argument("--index-url", default="https://pypi.org/simple")
    pack_parser.add_argument("--private-key")
    pack_parser.add_argument("--public-key")
    pack_parser.add_argument("--max-size-mb", type=int, default=50)
    pack_parser.add_argument("--force", action="store_true")
    add_runtime_options(pack_parser)
    pack_parser.set_defaults(handler=pack)

    verify_parser = subcommands.add_parser("verify", help="repeat the no-network install test")
    verify_parser.add_argument("input")
    verify_parser.add_argument("--max-size-mb", type=int, default=50)
    add_runtime_options(verify_parser)
    verify_parser.set_defaults(handler=offline_verify)

    key_parser = subcommands.add_parser("keygen", help="generate a third-party signing key pair")
    key_parser.add_argument("--output-dir", default="keys")
    key_parser.add_argument("--name", default="offline-packager")
    add_runtime_options(key_parser)
    key_parser.set_defaults(handler=keygen)

    signature_parser = subcommands.add_parser("verify-signature")
    signature_parser.add_argument("input")
    signature_parser.add_argument("--public-key", required=True)
    add_runtime_options(signature_parser)
    signature_parser.set_defaults(handler=signature_verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (
        CliError,
        ProfileError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
