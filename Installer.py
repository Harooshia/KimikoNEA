"""
Kimiko Installer

Windows bootstrap installer for Kimiko.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

LLMSTER_INSTALL_SCRIPT = "https://lmstudio.ai/install.ps1"

GITHUB_OWNER = "Harooshia"
GITHUB_REPO = "ProjectKimikoNEA"

# Exact release asset to download.
KIMIKO_RELEASE_ASSET = "KimikoNEA1.zip"

# Executable inside the ZIP.
KIMIKO_EXE_NAME = "KimikoNEA1.exe"

# Name shown in Windows Start Menu / Search.
START_MENU_NAME = "KimikoNEA1"


# ============================================================
# BASIC HELPERS
# ============================================================

def print_header():
    print("=" * 60)
    print("                 KIMIKO INSTALLER")
    print("=" * 60)
    print()


def find_lms():
    """
    Locate lms.

    First checks PATH.
    Then asks a new PowerShell process.
    Finally checks the normal LM Studio installation location.
    """

    # Check PATH.
    lms = shutil.which("lms")

    if lms:
        return lms

    # Check using a new PowerShell process.
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Command lms -ErrorAction SilentlyContinue).Source",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        path = result.stdout.strip()

        if path:
            return path

    except OSError:
        pass

    # Check the normal LM Studio bin directory.
    possible_paths = [
        Path(os.environ.get("USERPROFILE", "")) / ".lmstudio" / "bin" / "lms.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "lm-studio" / "bin" / "lms.exe",
    ]

    for path in possible_paths:
        if path.is_file():
            return str(path)

    return None


# ============================================================
# LLMSTER INSTALLATION
# ============================================================

def install_llmster():
    """Install LM Studio's headless runtime."""

    print("[LM Studio] lms was not found.")
    print("[LM Studio] Installing llmster from LM Studio...")
    print()

    powershell_command = "irm https://lmstudio.ai/install.ps1 | iex"

    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        powershell_command,
    ]

    try:
        subprocess.run(command, check=True)

    except subprocess.CalledProcessError as exc:
        print()
        print("[ERROR] llmster installation failed.")
        print(f"[ERROR] Exit code: {exc.returncode}")
        return False

    return True


# ============================================================
# GITHUB
# ============================================================

def get_latest_github_release():
    """
    Get metadata for the latest normal GitHub release.

    The release must not be marked as a pre-release.
    """

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    )

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Kimiko-Installer",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    except Exception as exc:
        print(f"[GitHub] Failed to retrieve latest release: {exc}")
        return None


def choose_github_asset(release):
    """Choose the Kimiko ZIP release asset."""

    assets = release.get("assets", [])

    if not assets:
        print("[GitHub] The release contains no uploaded assets.")
        print("[GitHub] Upload KimikoNEA1.zip to the GitHub release.")
        return None

    # Prefer the exact asset name.
    for asset in assets:
        if asset.get("name") == KIMIKO_RELEASE_ASSET:
            return asset

    print(
        f"[GitHub] Could not find release asset "
        f"'{KIMIKO_RELEASE_ASSET}'."
    )

    print("[GitHub] Available uploaded assets:")

    for asset in assets:
        print(f"           {asset.get('name', 'unknown')}")

    return None


def download_file(url, destination):
    """Download a file while showing a progress indicator."""

    print("[GitHub] Downloading:")
    print(f"         {url}")
    print()

    try:
        with urllib.request.urlopen(url, timeout=60) as response:

            total = response.headers.get("Content-Length")
            total = int(total) if total else None

            downloaded = 0

            with open(destination, "wb") as output:

                while True:

                    chunk = response.read(1024 * 1024)

                    if not chunk:
                        break

                    output.write(chunk)
                    downloaded += len(chunk)

                    if total:

                        percent = downloaded * 100 // total

                        print(
                            f"\r[GitHub] {percent:3d}% "
                            f"({downloaded / 1024 / 1024:.1f} MB / "
                            f"{total / 1024 / 1024:.1f} MB)",
                            end="",
                            flush=True,
                        )

                    else:

                        print(
                            f"\r[GitHub] "
                            f"{downloaded / 1024 / 1024:.1f} MB",
                            end="",
                            flush=True,
                        )

        print()
        print("[GitHub] Download complete.")

        return True

    except Exception as exc:

        print()
        print(f"[GitHub] Download failed: {exc}")

        return False


# ============================================================
# KIMIKO INSTALLATION
# ============================================================

def find_executable(folder):
    """
    Find the Kimiko executable after extraction.

    First look for the configured name.
    Then search for any EXE as a fallback.
    """

    exact = folder / KIMIKO_EXE_NAME

    if exact.is_file():
        return exact

    matches = list(folder.rglob(KIMIKO_EXE_NAME))

    if matches:
        return matches[0]

    exe_files = list(folder.rglob("*.exe"))

    if len(exe_files) == 1:
        return exe_files[0]

    return None


def extract_kimiko_zip(zip_path, install_directory):
    """Extract the Kimiko package into the local installation folder."""

    print()
    print("[Kimiko] Extracting Kimiko package...")

    try:

        with zipfile.ZipFile(zip_path, "r") as archive:

            # Basic path traversal protection.
            base = install_directory.resolve()

            for member in archive.infolist():

                target = (
                    install_directory / member.filename
                ).resolve()

                if os.path.commonpath(
                    [str(base), str(target)]
                ) != str(base):

                    print("[ERROR] Unsafe path found in ZIP.")
                    return None

            archive.extractall(install_directory)

    except zipfile.BadZipFile:

        print("[ERROR] The downloaded file is not a valid ZIP.")
        return None

    except Exception as exc:

        print(f"[ERROR] Could not extract Kimiko: {exc}")
        return None

    print("[Kimiko] Extraction complete.")

    return find_executable(install_directory)


def create_start_menu_shortcut(exe_path):
    """
    Create a Start Menu shortcut using PowerShell.
    """

    start_menu = (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )

    start_menu.mkdir(
        parents=True,
        exist_ok=True
    )

    shortcut_path = (
        start_menu / f"{START_MENU_NAME}.lnk"
    )

    ps_script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{shortcut_path}'); "
        f"$shortcut.TargetPath = '{exe_path}'; "
        f"$shortcut.WorkingDirectory = '{exe_path.parent}'; "
        f"$shortcut.IconLocation = '{exe_path},0'; "
        "$shortcut.Save()"
    )

    try:

        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            check=True,
        )

        print("[Windows] Start Menu shortcut created:")
        print(f"          {shortcut_path}")

        return True

    except Exception as exc:

        print(
            f"[Windows] Could not create Start Menu shortcut: {exc}"
        )

        return False


def download_kimiko_release():
    """Download, extract, and install the latest Kimiko release."""

    print()
    print("[GitHub] Checking for the latest Kimiko release...")

    release = get_latest_github_release()

    if not release:
        return False

    print(
        f"[GitHub] Latest release: "
        f"{release.get('tag_name', 'unknown')}"
    )

    asset = choose_github_asset(release)

    if not asset:
        return False

    asset_name = asset.get(
        "name",
        KIMIKO_RELEASE_ASSET
    )

    download_url = asset.get(
        "browser_download_url"
    )

    if not download_url:

        print(
            "[GitHub] Release asset has no download URL."
        )

        return False

    install_directory = (
        Path(
            os.environ.get(
                "LOCALAPPDATA",
                tempfile.gettempdir()
            )
        )
        / "Kimiko"
    )

    install_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    destination = (
        install_directory / asset_name
    )

    if not download_file(
        download_url,
        destination
    ):
        return False

    print(
        f"[GitHub] Saved release to: "
        f"{destination}"
    )

    # Extract the ZIP.
    exe_path = extract_kimiko_zip(
        destination,
        install_directory
    )

    if not exe_path:

        print()
        print(
            "[ERROR] Kimiko executable was not "
            "found after extraction."
        )

        print(
            f"[ERROR] Expected: {KIMIKO_EXE_NAME}"
        )

        return False

    print("[Kimiko] Executable found:")
    print(f"         {exe_path}")

    # Create Start Menu shortcut.
    create_start_menu_shortcut(
        exe_path
    )

    # Remove ZIP after extraction.
    try:

        destination.unlink()

        print(
            "[Kimiko] Removed temporary ZIP package."
        )

    except OSError:
        pass

    # Launch Kimiko.
    print()
    print("[Kimiko] Starting Kimiko...")

    try:

        subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
        )

        print(
            "[Kimiko] Kimiko has been started."
        )

    except Exception as exc:

        print(
            f"[Kimiko] Could not start Kimiko: {exc}"
        )

        print(
            f"[Kimiko] You can launch it from "
            f"Windows Search as {START_MENU_NAME}."
        )

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print_header()

    if os.name != "nt":

        print(
            "[ERROR] This installer is currently "
            "the Windows version."
        )

        return 1

    # --------------------------------------------------------
    # STEP 1: Check for llmster
    # --------------------------------------------------------

    lms_path = find_lms()

    if lms_path:

        print("[LM Studio] Found lms:")
        print(f"             {lms_path}")

    else:

        if not install_llmster():
            return 1

        lms_path = find_lms()

        if not lms_path:

            print()
            print(
                "[ERROR] llmster appears to have installed, "
                "but 'lms' could not be found."
            )

            print()
            print(
                "Try closing and reopening the installer "
                "so Windows can refresh its PATH."
            )

            return 1

        print()
        print("[LM Studio] Found lms after installation:")
        print(f"             {lms_path}")

    # --------------------------------------------------------
    # STEP 2: Download and install Kimiko
    # --------------------------------------------------------

    if not download_kimiko_release():
        return 1

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("                 KIMIKO READY")
    print("=" * 60)
    print()

    print("Kimiko has been installed.")
    print()

    print(
        f"Open Windows Search and type: "
        f"{START_MENU_NAME}"
    )

    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())