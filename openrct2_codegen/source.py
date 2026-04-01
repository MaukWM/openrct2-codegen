"""Download and cache OpenRCT2 source repos for a given version tag."""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CACHE_DIR = Path.home() / ".cache" / "openrct2-codegen"

# Sparse clone features (--sparse, --filter) require git 2.25+
MIN_GIT_VERSION = (2, 25)


# ── Repo definitions ─────────────────────────────────────────────────


@dataclass
class RepoSource:
    """A git repo that can be sparse-cloned, cached, and validated."""

    url: str
    sparse_paths: list[str]
    cache_prefix: (
        str  # e.g. "" for main repo (cache as "v0.4.32"), "objects-" for objects repo
    )
    validate: Callable[[Path], None]  # raises FileNotFoundError if invalid

    def get(self, version: str) -> Path:
        """Get the cached source, downloading if needed."""
        cache_path = CACHE_DIR / f"{self.cache_prefix}{version}"

        if cache_path.exists():
            try:
                self.validate(cache_path)
            except FileNotFoundError:
                print(
                    f"Cache at {cache_path} is incomplete — updating sparse checkout..."
                )
                self._repair_sparse_checkout(cache_path)
                self.validate(cache_path)
            return cache_path

        git_version = _check_git()

        if git_version >= MIN_GIT_VERSION:
            print(
                f"Downloading {self.cache_prefix or 'OpenRCT2 '}{version} (sparse clone)..."
            )
            self._sparse_clone(version, cache_path)
        else:
            print("git too old for sparse clone, falling back to full shallow clone...")
            self._shallow_clone(version, cache_path)

        print("Download complete.")
        self.validate(cache_path)
        return cache_path

    def _sparse_clone(self, version: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--sparse",
                    "--filter=blob:none",
                    "--branch",
                    version,
                    self.url,
                    str(dest),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "sparse-checkout", "set", *self.sparse_paths],
                cwd=dest,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            if dest.exists():
                shutil.rmtree(dest)
            raise RuntimeError(f"Sparse clone failed for {version}: {e.stderr}") from e

    def _shallow_clone(self, version: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    version,
                    self.url,
                    str(dest),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            if dest.exists():
                shutil.rmtree(dest)
            raise RuntimeError(f"Shallow clone failed for {version}: {e.stderr}") from e

    def _repair_sparse_checkout(self, dest: Path) -> None:
        try:
            subprocess.run(
                ["git", "sparse-checkout", "set", *self.sparse_paths],
                cwd=dest,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to repair sparse checkout at {dest}: {e.stderr}"
            ) from e


# ── Validation functions ─────────────────────────────────────────────

MIN_ACTION_FILES = 50


def _validate_main_source(source_root: Path) -> None:
    """Sanity-check that the main OpenRCT2 source has the files we need."""
    script_engine = source_root / "src" / "openrct2" / "scripting" / "ScriptEngine.cpp"
    if not script_engine.exists():
        raise FileNotFoundError(f"ScriptEngine.cpp not found at {script_engine}")

    dts = get_dts_path(source_root)
    if not dts.exists():
        raise FileNotFoundError(f"openrct2.d.ts not found at {dts}")

    action_files = list(source_root.glob("src/openrct2/actions/**/*Action.cpp"))
    if len(action_files) < MIN_ACTION_FILES:
        raise FileNotFoundError(
            f"Expected at least {MIN_ACTION_FILES} action files, found {len(action_files)}"
        )

    # Enum source files (added in sparse path expansion for enums parser)
    for expected in [
        source_root / "src" / "openrct2" / "entity" / "Guest.h",
        source_root / "src" / "openrct2" / "ride" / "ShopItem.h",
        source_root / "src" / "openrct2" / "drawing" / "Colour.h",
        source_root / "src" / "openrct2" / "world" / "MapSelection.h",
        source_root / "src" / "openrct2" / "interface" / "Window.h",
    ]:
        if not expected.exists():
            raise FileNotFoundError(f"Enum source file not found: {expected}")


def _validate_objects_source(objects_root: Path) -> None:
    """Sanity-check that the objects repo has the files we need."""
    ride_dir = objects_root / "objects" / "rct2" / "ride"
    if not ride_dir.is_dir():
        raise FileNotFoundError(f"Ride objects directory not found: {ride_dir}")
    json_files = list(ride_dir.glob("*.json"))
    if len(json_files) < 100:
        raise FileNotFoundError(
            f"Expected at least 100 ride object JSONs, found {len(json_files)}"
        )


# ── Repo instances ───────────────────────────────────────────────────

MAIN_REPO = RepoSource(
    url="https://github.com/OpenRCT2/OpenRCT2.git",
    sparse_paths=[
        "src/openrct2/actions",
        "src/openrct2/scripting",
        "src/openrct2/entity",
        "src/openrct2/ride",
        "src/openrct2/drawing",
        "src/openrct2/world",
        "src/openrct2/interface",
        "distribution",
    ],
    cache_prefix="",
    validate=_validate_main_source,
)

OBJECTS_REPO = RepoSource(
    url="https://github.com/OpenRCT2/objects.git",
    sparse_paths=[
        "objects/rct2",
    ],
    cache_prefix="objects-",
    validate=_validate_objects_source,
)


# ── Public API ───────────────────────────────────────────────────────


def get_source(version: str | None = None, local_path: Path | None = None) -> Path:
    """Get path to OpenRCT2 source root.

    Either downloads the source for a version tag (sparse clone),
    or validates and returns a local path.
    """
    if local_path and version:
        raise ValueError(
            "Provide either --openrct2-version or --openrct2-source, not both."
        )

    if local_path:
        if not local_path.is_dir():
            raise FileNotFoundError(f"Source path does not exist: {local_path}")
        _validate_main_source(local_path)
        return local_path

    if version:
        return MAIN_REPO.get(version)

    raise ValueError("Provide either --openrct2-version or --openrct2-source.")


def get_objects_source(version: str) -> Path:
    """Download and cache the OpenRCT2/objects repo for a given version tag."""
    return OBJECTS_REPO.get(version)


def get_pinned_objects_version(source_root: Path) -> str:
    """Read the objects version pinned by this OpenRCT2 release from assets.json.

    The URL format is: https://github.com/OpenRCT2/objects/releases/download/v1.7.6/objects.zip
    """
    assets_path = source_root / "assets.json"
    if not assets_path.exists():
        raise FileNotFoundError(f"assets.json not found at {assets_path}")

    data = json.loads(assets_path.read_text())
    url = data["objects"]["url"]
    match = re.search(r"/download/(v[\d.]+)/", url)
    if not match:
        raise ValueError(f"Could not extract objects version from URL: {url}")
    return match.group(1)


def get_dts_path(source_root: Path) -> Path:
    """Return the path to openrct2.d.ts within a source root."""
    return source_root / "distribution" / "openrct2.d.ts"


# ── Internal helpers ─────────────────────────────────────────────────


def _check_git() -> tuple[int, ...]:
    """Verify git is available and return its version as a tuple."""
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git not found. Install git to use --openrct2-version, "
            "or use --openrct2-source with a local path."
        ) from None

    version_str = result.stdout.strip().split()[2]
    return tuple(int(x) for x in version_str.split(".")[:2])
