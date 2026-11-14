# Troubleshooting & Common Issues

**Status:** `Scaffold Active`  
**Reference:** Common developer environment and configuration resolutions

---

## 1. Environment & Setup Issues

### 1.1 Python Package Compilation (`astropy`, `scipy`)
- **Problem:** Building wheels for `scipy` or `astropy` fails during `pip install`.
- **Solution:** Ensure modern `pip` (`pip install --upgrade pip setuptools wheel`). Pre-compiled wheels are available for Python 3.11/3.12/3.13 on standard platforms.

### 1.2 Module Shadowing Warning
- **Problem:** Python standard library `logging` errors or conflicts.
- **Rule:** Never name a module `logging.py`. SPHEREx Change Lens uses `change_lens/observability/logging_config.py` to prevent standard library collisions.

### 1.3 Windows Path & Symlink Constraints
- **Problem:** Scripts failing on forward/backward slash handling.
- **Solution:** Use `pathlib.Path` consistently across Python scripts; avoid raw string concatenations for file paths.

---

## 2. Docker & Container Issues

### 2.1 File Permissions on Mounted Volumes
- **Problem:** SQLite database in `data/change_lens.db` returns read-only or permission denied.
- **Solution:** Verify host permissions for `data/` directory.

### 2.2 Frontend Hot-Reloading in Docker
- **Problem:** Vite changes not detected inside Docker.
- **Solution:** Add `usePolling: true` in `vite.config.ts` if running on Docker Desktop on Windows.
