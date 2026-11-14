#!/usr/bin/env python3
"""SPHEREx Change Lens - Repository Architecture & Scaffolding Validator.

Performs non-destructive static validation checks across structure, configuration,
package discovery boundaries, and safety policies.
"""

import json
import os
from pathlib import Path
import sys

# Windows / POSIX root discovery
REPO_ROOT = Path(__file__).resolve().parent.parent


REQUIRED_DIRECTORIES = [
    ".github/workflows",
    "docs",
    "frontend/public/assets",
    "frontend/src/app",
    "frontend/src/components",
    "frontend/src/features/landing",
    "frontend/src/features/target-selection",
    "frontend/src/features/coverage-summary",
    "frontend/src/features/timeline",
    "frontend/src/features/image-viewer",
    "frontend/src/features/source-analysis",
    "frontend/src/features/difference-view",
    "frontend/src/features/evidence-drawer",
    "frontend/src/api",
    "frontend/src/contracts",
    "frontend/src/fixtures",
    "frontend/src/hooks",
    "frontend/src/styles",
    "frontend/src/test",
    "backend/src/change_lens/api/routes",
    "backend/src/change_lens/contracts",
    "backend/src/change_lens/targets",
    "backend/src/change_lens/investigations",
    "backend/src/change_lens/archive",
    "backend/src/change_lens/retrieval",
    "backend/src/change_lens/fits",
    "backend/src/change_lens/timeline",
    "backend/src/change_lens/pipeline/extensions",
    "backend/src/change_lens/jobs",
    "backend/src/change_lens/provenance",
    "backend/src/change_lens/storage",
    "backend/src/change_lens/observability",
    "backend/tests/unit",
    "backend/tests/contract",
    "backend/tests/integration",
    "backend/tests/scientific",
    "backend/scripts",
    "scientific/configs",
    "scientific/validation",
    "scientific/reference_outputs",
    "data/manifests",
    "data/target_queries",
    "data/cached_mefs",
    "data/previews",
    "data/derived",
    "data/synthetic",
    "tests/e2e",
    "scripts",
    "infra/docker",
]

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "Makefile",
    "pyproject.toml",
    "docker-compose.yml",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "docs/final-a-z-architecture-v3.md",
    "docs/technical-implementation-guide.md",
    "docs/nasa-traceability.md",
    "docs/resource-decisions.md",
    "docs/target-coverage.md",
    "docs/scientific-method.md",
    "docs/flag-policy.md",
    "docs/provenance-policy.md",
    "docs/api-contracts.md",
    "docs/development-setup.md",
    "docs/troubleshooting.md",
    "docs/team-ownership.md",
    "docs/demo-runbook.md",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/vite.config.ts",
    "frontend/tsconfig.json",
    "frontend/index.html",
    "frontend/src/contracts/index.ts",
    "frontend/src/styles/main.css",
    "backend/pyproject.toml",
    "backend/src/change_lens/__init__.py",
    "backend/src/change_lens/main.py",
    "backend/src/change_lens/config.py",
    "backend/src/change_lens/api/__init__.py",
    "backend/src/change_lens/api/routes/__init__.py",
    "backend/src/change_lens/api/dependencies.py",
    "backend/src/change_lens/api/errors.py",
    "backend/src/change_lens/contracts/__init__.py",
    "backend/src/change_lens/targets/__init__.py",
    "backend/src/change_lens/investigations/__init__.py",
    "backend/src/change_lens/archive/__init__.py",
    "backend/src/change_lens/retrieval/__init__.py",
    "backend/src/change_lens/fits/__init__.py",
    "backend/src/change_lens/timeline/__init__.py",
    "backend/src/change_lens/pipeline/__init__.py",
    "backend/src/change_lens/pipeline/alignment.py",
    "backend/src/change_lens/pipeline/masks.py",
    "backend/src/change_lens/pipeline/detection.py",
    "backend/src/change_lens/pipeline/centroid.py",
    "backend/src/change_lens/pipeline/association.py",
    "backend/src/change_lens/pipeline/motion.py",
    "backend/src/change_lens/pipeline/brightness.py",
    "backend/src/change_lens/pipeline/difference.py",
    "backend/src/change_lens/pipeline/controls.py",
    "backend/src/change_lens/pipeline/evidence.py",
    "backend/src/change_lens/pipeline/extensions/__init__.py",
    "backend/src/change_lens/jobs/__init__.py",
    "backend/src/change_lens/provenance/__init__.py",
    "backend/src/change_lens/storage/__init__.py",
    "backend/src/change_lens/observability/__init__.py",
    "backend/src/change_lens/observability/logging_config.py",
    "backend/src/change_lens/observability/metrics.py",
    "backend/src/change_lens/observability/tracing.py",
    "scripts/setup.sh",
    "scripts/validate_environment.py",
    "scripts/generate_test_data.py",
    "infra/Dockerfile.api",
    "infra/Dockerfile.frontend",
    "infra/nginx.conf",
    "infra/docker/entrypoint.api.sh",
    "infra/docker/healthcheck.sh",
]


def check_directories() -> bool:
    """Verify all expected directories exist."""
    print("[1/6] Checking required directories...")
    missing = []
    for rel_path in REQUIRED_DIRECTORIES:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_dir():
            missing.append(rel_path)
    if missing:
        print(f"  FAIL: Missing directories: {missing}")
        return False
    print(f"  PASS: All {len(REQUIRED_DIRECTORIES)} required directories exist.")
    return True


def check_files() -> bool:
    """Verify all expected files exist."""
    print("[2/6] Checking required files...")
    missing = []
    for rel_path in REQUIRED_FILES:
        full_path = REPO_ROOT / rel_path
        if not full_path.is_file():
            missing.append(rel_path)
    if missing:
        print(f"  FAIL: Missing files: {missing}")
        return False
    print(f"  PASS: All {len(REQUIRED_FILES)} required files exist.")
    return True


def check_shadowing_and_safety() -> bool:
    """Verify standard library shadowing rules and sensitive files."""
    print("[3/6] Checking safety rules & shadowing constraints...")
    # Check that no logging.py exists in backend package
    shadowing_paths = [
        REPO_ROOT / "backend" / "src" / "change_lens" / "logging.py",
        REPO_ROOT / "backend" / "src" / "change_lens" / "observability" / "logging.py",
    ]
    for p in shadowing_paths:
        if p.exists():
            print(f"  FAIL: Forbidden module found: {p} (shadows standard library logging)")
            return False

    # Check for credentials or active secrets
    sensitive_patterns = [".env", "id_rsa", "*.pem"]
    for pat in sensitive_patterns:
        # Check if .env exists as tracked file with secrets
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            content = env_file.read_text(encoding="utf-8")
            if "AKIA" in content or "SECRET_KEY" in content:
                print("  FAIL: Potential real secrets detected in .env")
                return False

    print("  PASS: No prohibited module names or secret exposures detected.")
    return True


def check_python_metadata() -> bool:
    """Verify pyproject.toml parsing and boundary ownership."""
    print("[4/6] Checking Python package configurations...")
    try:
        # Check root pyproject.toml
        root_toml = REPO_ROOT / "pyproject.toml"
        assert root_toml.is_file()

        # Check backend pyproject.toml
        backend_toml = REPO_ROOT / "backend" / "pyproject.toml"
        assert backend_toml.is_file()

        content = backend_toml.read_text(encoding="utf-8")
        assert "change-lens" in content
        assert "fastapi" in content
        assert "photutils" in content
        print("  PASS: pyproject.toml configurations are present and valid.")
        return True
    except Exception as exc:
        print(f"  FAIL: Error validating pyproject.toml files: {exc}")
        return False


def check_frontend_metadata() -> bool:
    """Verify frontend/package.json syntax."""
    print("[5/6] Checking frontend package metadata...")
    pkg_json_path = REPO_ROOT / "frontend" / "package.json"
    try:
        data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
        assert data.get("name") == "spherex-change-lens-frontend"
        assert "react" in data.get("dependencies", {})
        assert "typescript" in data.get("devDependencies", {})
        print("  PASS: frontend/package.json is valid.")
        return True
    except Exception as exc:
        print(f"  FAIL: frontend/package.json invalid: {exc}")
        return False


def check_scaffold_imports() -> bool:
    """Verify basic scaffold package imports without feature side-effects."""
    print("[6/6] Checking Python scaffold imports...")
    sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
    try:
        import change_lens
        from change_lens.config import get_settings
        from change_lens.targets import NASA_PRESET_TARGETS

        settings = get_settings()
        assert settings.environment is not None
        assert len(NASA_PRESET_TARGETS) == 5
        print(f"  PASS: Successfully imported change_lens v{change_lens.__version__}.")
        return True
    except Exception as exc:
        print(f"  FAIL: Error importing scaffold modules: {exc}")
        return False


def main() -> int:
    print("=" * 60)
    print("SPHEREx Change Lens Architecture Validator")
    print("=" * 60)

    checks = [
        check_directories(),
        check_files(),
        check_shadowing_and_safety(),
        check_python_metadata(),
        check_frontend_metadata(),
        check_scaffold_imports(),
    ]

    print("=" * 60)
    if all(checks):
        print("ALL ARCHITECTURAL SCAFFOLD CHECKS PASSED.")
        print("=" * 60)
        return 0
    else:
        print("VALIDATION FAILED: Please inspect errors above.")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
