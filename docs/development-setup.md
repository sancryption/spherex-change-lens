# Local Development Setup Guide

**Status:** `Scaffold Active`  
**Audience:** All Development Team Members

---

## 1. System Requirements
- **Operating System:** Linux, macOS, or Windows (WSL2 / PowerShell)
- **Python:** 3.11 or newer
- **Node.js:** 20.x or newer (npm or pnpm)
- **Git:** 2.40 or newer
- **Docker & Compose:** (Recommended for integration testing)

---

## 2. Step-by-Step Initialization

### 2.1 Clone and Environment Setup
```bash
# Clone the repository
git clone <repository-url> spherex-change-lens
cd spherex-change-lens

# Copy the development environment template
cp .env.example .env
```

### 2.2 Backend Environment Setup
```bash
cd backend
python -m venv .venv

# Activate virtualenv:
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# Install backend in editable mode with development dependencies
pip install --upgrade pip
pip install -e ".[dev]"
```

### 2.3 Frontend Environment Setup
```bash
cd ../frontend
npm install
```

### 2.4 Scaffold Verification Check
Return to the project root and execute the verification utility:
```bash
python scripts/validate_environment.py
```

---

## 3. Running Local Servers (Once Implemented)
- **Backend API:**
  ```bash
  uvicorn change_lens.main:app --reload --port 8000
  ```
  Real SPHEREx data (demo): `SPHEREX_ARCHIVE_MOCK_MODE=false uvicorn change_lens.main:app --port 8000`, after `make prewarm` (see `docs/demo-runbook.md`).
- **Frontend Development Server:**
  ```bash
  cd frontend && npm run dev
  ```
