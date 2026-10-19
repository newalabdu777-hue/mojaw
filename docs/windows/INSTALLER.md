# Windows desktop installer (prototype)

This repository has an Electron desktop wrapper and an NSIS installer build path. It packages the React/Vite frontend as a Windows x64 desktop app. Direct dependency versions are pinned in `frontend/package.json`. **It does not bundle or install the FastAPI backend, Python, a database service, or production credentials.** The backend must be started separately and reachable at the API URL baked into the frontend build. By default, the UI uses `http://127.0.0.1:8000`.

## Build on Windows

Requirements: Node.js 22, npm, and network access to the npm registry.

```powershell
cd frontend
npm install --no-audit --no-fund
npm test
npm run check:desktop
npm run build
npx electron-builder --win nsis --x64
```

Expected output: `frontend/release/School-Management-System-Setup-0.1.0-x64.exe` (the exact filename follows `package.json` version and builder output). `npm run dist:win:dir` creates an unpacked directory for smoke testing instead of the NSIS installer.

To point the desktop UI at a separately hosted API, set `VITE_API_BASE_URL` before building, for example:

```powershell
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run build
npx electron-builder --win nsis --x64
```

The value is compiled into the renderer at build time; do not place secrets in `VITE_*` variables. The app window disables Node integration, enables context isolation and sandboxing, and opens ordinary HTTP(S) links externally rather than navigating the packaged app to them.

## GitHub Actions workflow

The workflow at `.github/workflows/windows-installer.yml` runs on `workflow_dispatch` and tags matching `desktop-v*`. It uses Node.js 22, retries dependency installation once after npm's configured network retries, runs frontend tests and Electron syntax checks, builds the Vite renderer in a separate step, and then creates the x64 NSIS installer. Each failure stage emits a searchable diagnostic (`DEPENDENCY_INSTALL_FAILED`, `FRONTEND_TESTS_FAILED`, `ELECTRON_SYNTAX_CHECK_FAILED`, `PRODUCTION_BUILD_FAILED`, or `NSIS_PACKAGING_FAILED`). It checks that `dist/index.html` and at least one `.exe` exist before uploading. It generates a SHA-256 checksum file alongside the installer. Artifact upload is configured to fail if files are missing; upload-service failures are converted into the explicit `ARTIFACT_UPLOAD_FAILED` diagnostic, and the workflow summary reports success/failure and points to the run logs. The installer, SHA-256 checksum, and `installer-build-info.txt` provenance manifest (package version, commit SHA, Actions run ID, Node/npm versions, UTC build time, installer size, and hashes) are uploaded as a run-numbered artifact for 14 days. The package lockfile is uploaded separately as `school-management-package-lock-*` before dependency installation. npm caching is keyed from `frontend/package.json` because a lockfile is not yet committed.

The workflow uses a committed `frontend/package-lock.json` when available. If it is missing, it first runs `npm install --package-lock-only --ignore-scripts` with npm registry retries, validates that the generated lockfile is valid JSON, has a supported lockfile version and package map, and matches the root package name/version before installing exclusively with `npm ci`. The generated lockfile is uploaded as its own run artifact before installation, so it can still be reviewed if a later build step fails; until committed, separate runs may resolve newer transitive versions, so fully reproducible releases still require checking in the reviewed lockfile. Both lockfile generation and `npm ci` retry once after npm's configured network retries. The workflow checks that installation created `node_modules`.

## Dependency/build troubleshooting

- `LOCKFILE_GENERATION_FAILED`: when no lockfile is committed, npm could not resolve package metadata, or the generated lockfile is malformed/inconsistent with `package.json`. Inspect registry errors and verify network/DNS/proxy access to `https://registry.npmjs.org/`; do not create a lockfile by hand.
- `LOCKFILE_ARTIFACT_UPLOAD_FAILED`: lockfile generation succeeded but the separate lockfile review artifact could not be stored; check Actions artifact service and repository permissions.
- `DEPENDENCY_INSTALL_FAILED`: inspect the npm error above the diagnostic. The workflow installs with `npm ci` after lockfile generation.
- `FRONTEND_TESTS_FAILED`: fix the reported Node test failure before packaging.
- `ELECTRON_SYNTAX_CHECK_FAILED`: inspect `frontend/electron/main.cjs`.
- `PRODUCTION_BUILD_FAILED`: review the first TypeScript/Vite compiler error; confirm `node_modules` exists and any configured `VITE_API_BASE_URL` is valid. The workflow separately checks for `frontend/dist/index.html`.
- `NSIS_PACKAGING_FAILED`: inspect electron-builder output, ensure the runner has disk space, and verify the target configuration. If no `.exe` exists despite a successful builder exit, the workflow fails instead of uploading an empty artifact.
- `ARTIFACT_PREPARATION_FAILED`: no `.exe` was available when checksums were generated; inspect the NSIS step and release directory.
- `ARTIFACT_UPLOAD_FAILED`: installer creation succeeded but GitHub could not store the artifact; check Actions artifact service availability, repository permissions, and run logs.
- Artifact upload fails if the `.exe`, checksum file, or build manifest is missing, rather than silently succeeding.

Local note: this workspace has previously been unable to reach the npm registry (`EAI_AGAIN`), so a full dependency install and real TypeScript/Vite/Electron packaging run cannot be claimed from that environment. The Windows GitHub Actions run is required to verify actual `.exe` generation.

## Release checklist

- Test install, launch, upgrade, uninstall, Start Menu/Desktop shortcuts, and clean-machine behavior on supported Windows versions.
- Confirm the API is running and CORS permits requests from the packaged `file://` renderer; verify the API's security model before using real records.
- Sign the installer and configure update delivery before distributing it broadly.
- The current backend intentionally blocks production mode. This installer is a development prototype and must not be used for real student or financial data.
