"""Versioned runtime profiles for Dify plugin packaging."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = ROOT / "config/runtime-profiles.json"


class ProfileError(ValueError):
    """Raised when the runtime profile catalog is invalid."""


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    display_name: str
    dify_version: str
    edition: str
    deployment: str
    runtime_image: str
    image_digest: str
    python_executable: str
    python_version: str
    uv_executable: str
    package_cli: str
    support_status: str
    platforms: dict[str, dict[str, str]]

    def platform_status(self, platform: str) -> dict[str, str]:
        return self.platforms.get(platform, {"status": "not-listed"})


@dataclass(frozen=True)
class ProfileCatalog:
    schema_version: int
    profiles: dict[str, RuntimeProfile]

    def get(self, name: str) -> RuntimeProfile:
        try:
            return self.profiles[name]
        except KeyError as error:
            available = ", ".join(sorted(self.profiles))
            raise ProfileError(
                f"unknown runtime profile {name!r}; available profiles: {available}"
            ) from error


@dataclass(frozen=True)
class RuntimeSelection:
    profile: RuntimeProfile
    customized: bool

    def validation(self, platform: str) -> dict[str, str]:
        if self.customized:
            return {"status": "custom-runtime-not-validated"}
        return self.profile.platform_status(platform)


def _required_string(data: dict[str, Any], key: str, profile_name: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"profile {profile_name!r} must define a non-empty {key!r}")
    return value


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> ProfileCatalog:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError(f"cannot load runtime profiles from {path}: {error}") from error

    if raw.get("schema_version") != 1:
        raise ProfileError("unsupported runtime profile schema_version")
    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ProfileError("profile catalog must define at least one profile")

    profiles: dict[str, RuntimeProfile] = {}
    required = (
        "display_name",
        "dify_version",
        "edition",
        "deployment",
        "runtime_image",
        "image_digest",
        "python_executable",
        "python_version",
        "uv_executable",
        "package_cli",
        "support_status",
    )
    for name, value in raw_profiles.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ProfileError("profile names and definitions must be objects")
        platforms = value.get("platforms")
        if not isinstance(platforms, dict) or not platforms:
            raise ProfileError(f"profile {name!r} must define platform validation states")
        normalized_platforms: dict[str, dict[str, str]] = {}
        for platform, evidence in platforms.items():
            if not isinstance(platform, str) or not isinstance(evidence, dict):
                raise ProfileError(f"profile {name!r} has an invalid platform entry")
            if not isinstance(evidence.get("status"), str):
                raise ProfileError(f"profile {name!r} platform {platform!r} must define status")
            if not all(
                isinstance(key, str) and isinstance(item, str) for key, item in evidence.items()
            ):
                raise ProfileError(
                    f"profile {name!r} platform {platform!r} evidence must be strings"
                )
            cli_hash = evidence.get("observed_cli_sha256")
            if cli_hash is not None:
                try:
                    valid_cli_hash = len(cli_hash) == 64 and int(cli_hash, 16) >= 0
                except ValueError:
                    valid_cli_hash = False
                if not valid_cli_hash:
                    raise ProfileError(
                        f"profile {name!r} platform {platform!r} has an invalid CLI SHA-256"
                    )
            normalized_platforms[platform] = dict(evidence)

        strings = {key: _required_string(value, key, name) for key in required}
        if not (
            strings["image_digest"].startswith("sha256:")
            and len(strings["image_digest"]) == len("sha256:") + 64
        ):
            raise ProfileError(f"profile {name!r} image_digest must be a SHA-256 digest")
        try:
            int(strings["image_digest"].removeprefix("sha256:"), 16)
        except ValueError as error:
            raise ProfileError(
                f"profile {name!r} image_digest must contain hexadecimal characters"
            ) from error
        profiles[name] = RuntimeProfile(
            name=name,
            platforms=normalized_platforms,
            **strings,
        )

    return ProfileCatalog(schema_version=1, profiles=profiles)


def select_runtime(
    catalog: ProfileCatalog,
    profile_name: str,
    *,
    runtime_image: str | None = None,
    python_executable: str | None = None,
    uv_executable: str | None = None,
    package_cli: str | None = None,
) -> RuntimeSelection:
    profile = catalog.get(profile_name)
    overrides = {
        "runtime_image": runtime_image,
        "python_executable": python_executable,
        "uv_executable": uv_executable,
        "package_cli": package_cli,
    }
    customized = any(
        value is not None and value != getattr(profile, key) for key, value in overrides.items()
    )
    selected = replace(
        profile,
        **{key: value for key, value in overrides.items() if value is not None},
    )
    return RuntimeSelection(profile=selected, customized=customized)
