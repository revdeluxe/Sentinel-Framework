
import os
import sys
import subprocess
import hashlib
import json
from datetime import datetime
import shutil
import zipfile
import tempfile

REQUIREMENTS = os.path.join("src", "requirements.txt")
LOG_FILE = os.path.join("logs", "run_log.json")
PACKAGES_MARKER = os.path.join("logs", "packages_installed.json")
SRC_DIR = "src"

os.makedirs("logs", exist_ok=True)


def install_packages(force_install: bool = False):
    """Install packages from requirements unless already installed and up-to-date.
    Uses a marker file to skip repeated installs. Pass force_install=True to re-run pip install."""
    req_hash = None
    try:
        with open(REQUIREMENTS, "rb") as f:
            req_hash = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        req_hash = None

    # Check marker
    if not force_install and os.path.exists(PACKAGES_MARKER):
        try:
            with open(PACKAGES_MARKER, "r", encoding="utf-8") as fm:
                marker = json.load(fm)
            if req_hash and marker.get("requirements_hash") == req_hash:
                print("Packages appear already installed and requirements unchanged — skipping pip install.")
                return
        except Exception:
            pass

    print("Installing required packages...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS])
        # record marker with pip freeze and requirements hash
        try:
            freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"]).decode("utf-8")
        except Exception:
            freeze = ""
        marker = {"timestamp": datetime.now().isoformat(), "requirements_hash": req_hash, "pip_freeze": freeze}
        with open(PACKAGES_MARKER, "w", encoding="utf-8") as fm:
            json.dump(marker, fm, indent=2)
        print("Package installation complete; marker written.")
    except subprocess.CalledProcessError as e:
        print("\n[ERROR] Package installation failed.")
        if "No such file or directory" in str(e):
            print("\nPossible cause: Windows Long Path support is not enabled.\n")
            print("To fix this, enable Long Path support:")
            print("  1. Open Registry Editor (Win+R → regedit)")
            print("  2. Navigate to HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Control\\FileSystem")
            print("  3. Set 'LongPathsEnabled' to 1 (DWORD)")
            print("  4. Restart your computer.")
        if sys.version_info >= (3, 13):
            print("\nTensorFlow does not support Python 3.13 yet. Please use Python 3.10 or 3.11 for best compatibility.")
        print("\nFor more help, see: https://pip.pypa.io/warnings/enable-long-paths\n")
        sys.exit(1)


def copy_adminlte_assets(force_download: bool = False):
    """
    Download AdminLTE 4 assets (CSS/JS) from a CDN into src/static if not present.
    """
    css_url = "https://cdn.jsdelivr.net/npm/admin-lte@4.2.0/dist/css/adminlte.min.css"
    js_url = "https://cdn.jsdelivr.net/npm/admin-lte@4.2.0/dist/js/adminlte.min.js"
    dest_css = os.path.join('src', 'static', 'css')
    dest_js = os.path.join('src', 'static', 'js')
    os.makedirs(dest_css, exist_ok=True)
    os.makedirs(dest_js, exist_ok=True)
    css_path = os.path.join(dest_css, 'adminlte.min.css')
    js_path = os.path.join(dest_js, 'adminlte.min.js')
    # If files already exist and non-empty and not forced, skip download
    if not force_download and os.path.exists(css_path) and os.path.exists(js_path):
        try:
            if os.path.getsize(css_path) > 0 and os.path.getsize(js_path) > 0:
                print("AdminLTE assets already present locally — skipping download.")
                return
        except Exception:
            pass
    try:
        # Try downloading from CDN
        import urllib.request
        print(f"Downloading AdminLTE CSS from {css_url}...")
        urllib.request.urlretrieve(css_url, css_path)
        print(f"Downloading AdminLTE JS from {js_url}...")
        urllib.request.urlretrieve(js_url, js_path)
        print("AdminLTE assets downloaded to src/static.")
    except Exception as e:
        print(f"[WARNING] Failed to download AdminLTE assets from CDN: {e}")
        # As a fallback, try copying from an installed package if available
        tried = False
        try:
            import adminlte4
            adminlte_path = os.path.dirname(adminlte4.__file__)
            static_css = os.path.join(adminlte_path, 'static', 'css')
            static_js = os.path.join(adminlte_path, 'static', 'js')
            for f in os.listdir(static_css):
                shutil.copy2(os.path.join(static_css, f), dest_css)
            for f in os.listdir(static_js):
                shutil.copy2(os.path.join(static_js, f), dest_js)
            print("AdminLTE assets copied from installed package to src/static.")
            tried = True
        except Exception as e2:
            print(f"[WARNING] Fallback copy also failed: {e2}")

        if not tried:
            # Try GitHub release ZIP as a last resort
            gh_zip_url = "https://github.com/ColorlibHQ/AdminLTE/releases/download/v4.2.0/AdminLTE-4.2.0.zip"
            try:
                print(f"Attempting to download AdminLTE release ZIP from {gh_zip_url}...")
                tmpfd, tmpname = tempfile.mkstemp(suffix=".zip")
                os.close(tmpfd)
                urllib.request.urlretrieve(gh_zip_url, tmpname)
                with zipfile.ZipFile(tmpname, 'r') as z:
                    # Find adminlte assets inside the zip and extract
                    found_css = None
                    found_js = None
                    for info in z.infolist():
                        name = info.filename
                        if name.endswith('adminlte.min.css'):
                            found_css = name
                        if name.endswith('adminlte.min.js'):
                            found_js = name
                    if found_css:
                        with z.open(found_css) as fh, open(css_path, 'wb') as out:
                            out.write(fh.read())
                    if found_js:
                        with z.open(found_js) as fh, open(js_path, 'wb') as out:
                            out.write(fh.read())
                os.remove(tmpname)
                print("AdminLTE assets extracted from GitHub release ZIP to src/static.")
            except Exception as e3:
                print(f"[WARNING] GitHub ZIP fallback failed: {e3}")
                print("You can manually download AdminLTE v4 assets and place them in src/static/css and src/static/js.")


def checksum_src():
    print("Checksumming src/ directory...")
    checksums = {}
    for root, _, files in os.walk(SRC_DIR):
        for f in files:
            path = os.path.join(root, f)
            with open(path, "rb") as file:
                data = file.read()
                checksums[path] = hashlib.sha256(data).hexdigest()
    return checksums


def validate_src():
    """Ensure required source files and assets exist before launching the server."""
    required = [
        "main.py",
        "database.py",
        "table.py",
        os.path.join("templates", "base.html"),
        os.path.join("templates", "index.html"),
        os.path.join("templates", "login.html"),
        os.path.join("templates", "scan.html"),
        os.path.join("templates", "success.html"),
        os.path.join("static", "css", "adminlte.min.css"),
        os.path.join("static", "css", "style.css"),
        os.path.join("static", "js", "adminlte.min.js"),
    ]
    missing = []
    for rel in required:
        p = os.path.join(SRC_DIR, rel)
        if not os.path.exists(p):
            missing.append(rel)

    if missing:
        print("\n[ERROR] Required files are missing in src/:")
        for m in missing:
            print(f" - {m}")
        print("\nPlease restore the missing files or run with --skip-validate to bypass this check.")
        return False
    print("Source check passed: all required files present.")
    return True


def save_log(mode, checksums):
    log = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "checksums": checksums
    }
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)
    print(f"Log saved to {LOG_FILE}")


def run_app(mode):
    if mode == "dev":
        print("Running in development mode...")
        subprocess.run([sys.executable, "-m", "uvicorn", "src.main:app", "--reload"])
    elif mode == "pro":
        print("Running in production mode...")
        subprocess.run([sys.executable, "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "80"])
    else:
        print("Unknown mode. Use 'dev' or 'pro'.")
        sys.exit(1)


def main():
    # Default to development mode when no arguments are provided to make
    # `python run.py` behave like `python run.py dev` for convenience.
    if len(sys.argv) < 2:
        mode = "dev"
        flags = []
        print("No mode specified — defaulting to 'dev'. Use --help for options.")
    else:
        mode = sys.argv[1]
        flags = sys.argv[2:]
    force_install = '--force-install' in flags
    force_download = '--force-download' in flags
    skip_validate = '--skip-validate' in flags
    install_packages(force_install=force_install)
    copy_adminlte_assets(force_download=force_download)
    if not skip_validate:
        ok = validate_src()
        if not ok:
            sys.exit(1)
    checksums = checksum_src()
    save_log(mode, checksums)
    run_app(mode)


if __name__ == "__main__":
    main()

