"""
Setup script for TikTok Scheduler.

Used by RUN.bat to verify and install dependencies automatically.
"""

import subprocess
import sys


REQUIRED_PACKAGES = [
    "playwright",
    "PyQt6",
    "pydantic",
    "python-dateutil",
    "qtawesome"
]


def check_package(package: str) -> bool:
    """Return True if *package* is importable."""
    import importlib

    # Map pip names → importable names
    import_map = {
        "PyQt6": "PyQt6",
        "python-dateutil": "dateutil",
        "playwright": "playwright",
        "pydantic": "pydantic",
    }
    mod = import_map.get(package, package)
    try:
        importlib.import_module(mod)
        return True
    except ImportError:
        return False


def install_packages() -> None:
    """Install missing pip packages from requirements.txt."""
    missing = [p for p in REQUIRED_PACKAGES if not check_package(p)]
    if missing:
        print(f"[setup] Installing missing packages: {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        )
    else:
        print("[setup] All Python packages are installed.")


def check_playwright_chromium() -> bool:
    """Return True if Playwright Chromium browser is installed."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path:
                print(f"[setup] Chromium found: {path}")
                return True
    except Exception:
        pass
    return False


def install_playwright_chromium() -> None:
    """Install Playwright Chromium browser."""
    print("[setup] Installing Playwright Chromium...")
    subprocess.check_call(
        [sys.executable, "-m", "playwright", "install", "chromium"],
    )
    print("[setup] Playwright Chromium installed.")


def main() -> None:
    """Run all checks and install missing dependencies."""
    print("=" * 50)
    print("  TikTok Scheduler — Dependency Setup")
    print("=" * 50)
    print()

    # Step 1: Python packages
    install_packages()
    print()

    # Step 2: Playwright Chromium
    if not check_playwright_chromium():
        install_playwright_chromium()
    print()

    print("[setup] All dependencies are ready!")


if __name__ == "__main__":
    main()
