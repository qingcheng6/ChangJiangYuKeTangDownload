"""Prepare a project-local Windows environment, then launch the real GUI."""

import importlib.metadata
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def pinned_requirements(path):
    return [tuple(line.strip().split("==", 1)) for line in path.read_text("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def run_setup(command, message):
    print(message, flush=True)
    # Installer diagnostics can contain local proxy/index configuration. Keep
    # them out of application logs; show a fixed, actionable message on failure.
    completed = subprocess.run(command, cwd=str(ROOT), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    return completed.returncode == 0


def main():
    if os.name != "nt" or sys.version_info < (3, 9) or struct.calcsize("P") != 8:
        print("This tool requires 64-bit Python 3.9+ on Windows.")
        return 1
    target = ROOT / ".venv" / "Scripts" / "python.exe"
    if not target.is_file():
        if not run_setup([sys.executable, "-m", "venv", str(ROOT / ".venv")],
                         "Creating a local Python environment..."):
            print("Cannot create .venv. Move the project to a writable folder and try again.")
            return 1
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        return subprocess.call([str(target), str(ROOT / "bootstrap.py")] + sys.argv[1:], cwd=str(ROOT))
    missing = False
    for name, expected in pinned_requirements(ROOT / "requirements.txt"):
        try:
            missing |= importlib.metadata.version(name) != expected
        except importlib.metadata.PackageNotFoundError:
            missing = True
    if missing:
        if not run_setup([str(target), "-m", "pip", "install", "--only-binary=:all:",
                          "-r", str(ROOT / "requirements.txt")], "Installing pinned dependencies..."):
            print("Dependency installation failed. Check the network and Python version; see README.md.")
            return 1
    try:
        import tkinter
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            installed = Path(pw.chromium.executable_path).is_file()
        if not installed:
            if not run_setup([str(target), "-m", "playwright", "install", "chromium"],
                             "Installing Chromium for the first launch..."):
                print("Chromium could not be installed. The app will try an installed Chrome browser.")
    except ImportError:
        print("Python is missing Tkinter or Playwright. Repair the Python installation; see README.md.")
        return 1
    return subprocess.call([str(target), str(ROOT / "main.py"), "--gui"] + sys.argv[1:], cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
