"""Download and cache OpenRCT2 source for a given version tag."""

import shutil
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/OpenRCT2/OpenRCT2.git"
CACHE_DIR = Path.home() / ".cache" / "openrct2-codegen"

# Minimum expected files — sanity check after download
MIN_ACTION_FILES = 50
# Sparse clone features (--sparse, --filter) require git 2.25+
MIN_GIT_VERSION = (2, 25)


def get_cache_path(version: str) -> Path:
    """Return the cache directory for a given version tag."""
    return CACHE_DIR / version


def get_source(version: str | None = None, local_path: Path | None = None) -> Path:
    """Get path to OpenRCT2 source root.

    Either downloads the source for a version tag (sparse clone),
    or validates and returns a local path.
    """
    if local_path and version:
        raise ValueError("Provide either --openrct2-version or --openrct2-source, not both.")

    if local_path:
        return _use_local(local_path)

    if version:
        return _download(version)

    raise ValueError("Provide either --openrct2-version or --openrct2-source.")


def _use_local(path: Path) -> Path:
    """Validate and return a local source path."""
    if not path.is_dir():
        raise FileNotFoundError(f"Source path does not exist: {path}")
    _validate_source(path)
    return path


def _download(version: str) -> Path:
    """Download source via sparse clone (or full shallow clone as fallback)."""
    cache_path = get_cache_path(version)
    if cache_path.exists():
        _validate_source(cache_path)
        return cache_path

    git_version = _check_git()

    if git_version >= MIN_GIT_VERSION:
        print(f"Downloading OpenRCT2 {version} source (sparse clone)...")
        _sparse_clone(version, cache_path)
    else:
        print(f"git {'.'.join(str(v) for v in git_version)} too old for sparse clone, "
              f"falling back to full shallow clone...")
        _shallow_clone(version, cache_path)

    print("Download complete.")
    _validate_source(cache_path)
    return cache_path


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

    # "git version 2.39.5" or "git version 2.39.5 (Apple Git-154)" -> (2, 39)
    version_str = result.stdout.strip().split()[2]
    return tuple(int(x) for x in version_str.split(".")[:2])


def _sparse_clone(version: str, dest: Path) -> None:
    """Shallow sparse clone of only the directories we need."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                "git", "clone",
                "--depth", "1",
                "--sparse",
                "--filter=blob:none",
                "--branch", version,
                REPO_URL,
                str(dest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git", "sparse-checkout", "set",
                "src/openrct2/actions",
                "src/openrct2/scripting",
                "distribution",
            ],
            cwd=dest,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        # Clean up partial clone on failure
        if dest.exists():
            shutil.rmtree(dest)
        raise RuntimeError(f"Sparse clone failed for {version}: {e.stderr}") from e


def _shallow_clone(version: str, dest: Path) -> None:
    """Full shallow clone (fallback for git < 2.25)."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                "git", "clone",
                "--depth", "1",
                "--branch", version,
                REPO_URL,
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


def get_dts_path(source_root: Path) -> Path:
    """Return the path to openrct2.d.ts within a source root."""
    return source_root / "distribution" / "openrct2.d.ts"


def _validate_source(source_root: Path) -> None:
    """Sanity-check that the source has the files we need."""
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
