"""Auto-install Git for Windows when no bash is found.

Ported from the KIMI agent install logic.  Provides a silent fallback
that downloads PortableGit (or runs the official installer) when the
local terminal backend can't locate a usable Git Bash.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GIT_VERSION: str = "2.54.0"
_GIT_WINDOWS_RELEASE: int = 1

_PORTABLE_DOWNLOAD_URL = (
    "https://github.com/git-for-windows/git/releases/download/"
    "v{version}.windows.{release}/PortableGit-{version}-64-bit.7z.exe"
)

_DOWNLOAD_URL = (
    "https://github.com/git-for-windows/git/releases/download/"
    "v{version}.windows.{release}/Git-{version}-64-bit.exe"
)

_INNO_FLAGS = [
    "/VERYSILENT",
    "/NORESTART",
    "/NOCANCEL",
    "/SP-",
    "/CLOSEAPPLICATIONS",
    "/RESTARTAPPLICATIONS",
]

_INNO_COMPONENTS = r"icons,ext\reg\shellhere,assoc,assoc_sh"


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _download_file(url: str, dest: Path) -> None:
    """Download *url* to *dest*, with a progress indicator."""
    import urllib.request

    def _report(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            pct = min(100, int(block_num * block_size * 100 / total_size))
            sys.stdout.write(f"\r  {pct}%")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, str(dest), _report)
    print()


def _git_found(install_dir: str | None = None) -> bool:
    """Return True if git.exe is available in *install_dir* or on PATH."""
    if install_dir:
        base = Path(install_dir)
        if (base / "bin" / "git.exe").exists():
            return True
        if (base / "cmd" / "git.exe").exists():
            return True
    return shutil.which("git") is not None


def _ensure_in_user_path(dirpath: str) -> None:
    """Add *dirpath* to the current user's PATH environment variable (persistent)."""
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
    except FileNotFoundError:
        return
    try:
        path_val, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        path_val = ""
    entries = [p.strip() for p in path_val.split(";") if p.strip()]
    if dirpath in entries:
        winreg.CloseKey(key)
        return
    entries.append(dirpath)
    new_path = ";".join(entries)
    winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
    winreg.CloseKey(key)


def _try_portable(version: str = GIT_VERSION, install_dir: str | None = None) -> bool:
    """Download PortableGit self-extracting archive and extract it to *install_dir*."""
    url = _PORTABLE_DOWNLOAD_URL.format(version=version, release=_GIT_WINDOWS_RELEASE)
    archive = Path(tempfile.gettempdir()) / f"PortableGit-{version}-64-bit.7z.exe"
    try:
        print(f"Downloading PortableGit {version} ...")
        _download_file(url, archive)
    except Exception as exc:
        print(f"Download failed: {exc}")
        return False

    target = Path(install_dir) if install_dir else Path.home() / ".hermes" / "git"
    target.mkdir(parents=True, exist_ok=True)
    try:
        print(f"Extracting to {target} ...")
        _run([str(archive), "-o" + str(target), "-y"], timeout=300)
    except subprocess.TimeoutExpired:
        print("Extraction timed out.")
        return False
    except Exception as exc:
        print(f"Extraction error: {exc}")
        return False
    finally:
        archive.unlink(missing_ok=True)

    bash_exe = target / "bin" / "bash.exe"
    git_exe = target / "bin" / "git.exe"
    ok = bash_exe.exists() and git_exe.exists()
    if ok:
        _ensure_in_user_path(str(target / "bin"))
        _ensure_in_user_path(str(target / "cmd"))
    return ok


def _try_direct_download(version: str = GIT_VERSION, install_dir: str | None = None) -> bool:
    """Download the official Git installer and run it silently."""
    url = _DOWNLOAD_URL.format(version=version, release=_GIT_WINDOWS_RELEASE)
    installer = Path(tempfile.gettempdir()) / f"Git-{version}-64-bit.exe"
    try:
        print(f"Downloading Git {version} ...")
        _download_file(url, installer)
    except Exception as exc:
        print(f"Download failed: {exc}")
        return False

    args = [str(installer), *_INNO_FLAGS, f"/COMPONENTS={_INNO_COMPONENTS}"]
    if install_dir:
        args.append(f'/DIR="{install_dir}"')
    try:
        print("Running silent installer ...")
        _run(args, timeout=900)
    except subprocess.TimeoutExpired:
        print("Installer timed out.")
    except Exception as exc:
        print(f"Installer error: {exc}")
    installer.unlink(missing_ok=True)
    return _git_found()


def _try_choco() -> bool:
    """Install Git via Chocolatey (if already on the machine)."""
    if not shutil.which("choco"):
        return False
    try:
        result = _run(["choco", "install", "git", "-y"])
        return result.returncode == 0
    except Exception:
        return False


def _try_scoop() -> bool:
    """Install Git via Scoop (if already on the machine)."""
    if not shutil.which("scoop"):
        return False
    try:
        result = _run(["scoop", "install", "git"])
        return result.returncode == 0
    except Exception:
        return False


def install_git(version: str = GIT_VERSION, install_dir: str | None = None) -> bool:
    """Install Git for Windows using the best available strategy.

    Parameters
    ----------
    version:
        Git version string (only used for the direct-download strategy).
    install_dir:
        Custom install directory.  ``None`` falls back to the Hermes home
        ``git/`` subdirectory (``~/.hermes/git`` by default).

    Returns
    -------
    ``True`` if Git is available after execution, ``False`` otherwise.
    """
    if sys.platform != "win32":
        return False

    if install_dir is None:
        try:
            from hermes_constants import get_hermes_home
            install_dir = str(get_hermes_home() / "git")
        except Exception:
            install_dir = str(Path.home() / ".hermes" / "git")

    if _git_found(install_dir):
        return True

    strategies = [
        ("portable", lambda: _try_portable(version, install_dir)),
        ("direct download", lambda: _try_direct_download(version, install_dir)),
        ("chocolatey", _try_choco),
        ("scoop", _try_scoop),
    ]

    for name, fn in strategies:
        print(f"Trying {name} ...")
        try:
            ok = fn()
        except Exception as exc:
            print(f"  {name} raised: {exc}")
            ok = False
        if ok and _git_found(install_dir):
            print(f"Git installed successfully via {name}.")
            return True
        print(f"  {name} did not succeed.")

    print("All installation strategies failed.", file=sys.stderr)
    return False
