import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const packageJson = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
const mainSource = await readFile(new URL('../electron/main.cjs', import.meta.url), 'utf8');
const viteConfig = await readFile(new URL('../vite.config.ts', import.meta.url), 'utf8');
const workflow = await readFile(new URL('../../.github/workflows/windows-installer.yml', import.meta.url), 'utf8');

test('Windows packaging scripts use Vite build and NSIS target', () => {
  assert.match(packageJson.scripts['dist:win'], /npm run build.*electron-builder --win nsis/);
  assert.equal(packageJson.build.win.target[0].target, 'nsis');
  assert.equal(packageJson.build.win.target[0].arch[0], 'x64');
  assert.equal(packageJson.build.nsis.oneClick, false);
});

test('Electron window uses hardened renderer preferences', () => {
  assert.match(mainSource, /nodeIntegration:\s*false/);
  assert.match(mainSource, /contextIsolation:\s*true/);
  assert.match(mainSource, /sandbox:\s*true/);
  assert.match(mainSource, /setWindowOpenHandler/);
  assert.match(mainSource, /loadFile/);
});

test('Vite uses relative paths for file-based desktop rendering', () => {
  assert.match(viteConfig, /base:\s*['"]\.\/['"]/);
});

test('Windows CI runs tests and uploads installer executable', () => {
  assert.match(workflow, /runs-on:\s*windows-latest/);
  assert.match(workflow, /npm test/);
  assert.match(workflow, /npm run build/);
  assert.match(workflow, /npx electron-builder --win nsis --x64/);
  assert.match(workflow, /frontend\/release\/\*\.exe/);
});

test('build checks Electron main-process syntax before bundling', () => {
  assert.match(packageJson.scripts.build, /npm run check:desktop.*tsc -b.*vite build/);
  assert.match(packageJson.scripts['check:desktop'], /node --check electron\/main\.cjs/);
});

test('Electron renderer only permits navigation to the packaged entry point', () => {
  assert.match(mainSource, /if \(url !== localIndex && !url\.startsWith\(`\$\{localIndex\}#`\)\) event\.preventDefault\(\)/);
  assert.doesNotMatch(mainSource, /!url\.startsWith\('file:\/\/'\)/);
});


test('Windows workflow diagnoses install, build, NSIS and artifact failures', () => {
  assert.match(workflow, /npm install --package-lock-only --ignore-scripts/);
  assert.match(workflow, /DEPENDENCY_INSTALL_FAILED/);
  assert.match(workflow, /PRODUCTION_BUILD_FAILED/);
  assert.match(workflow, /NSIS_PACKAGING_FAILED/);
  assert.match(workflow, /Get-ChildItem -Path release -Filter '\*\.exe'/);
  assert.match(workflow, /if-no-files-found:\s*error/);
  assert.match(workflow, /GITHUB_STEP_SUMMARY/);
  assert.match(workflow, /timeout-minutes:\s*30/);
});

test('Windows workflow runs renderer build separately before NSIS packaging', () => {
  const buildIndex = workflow.indexOf('name: Build renderer for production');
  const nsisIndex = workflow.indexOf('name: Create NSIS installer');
  const uploadIndex = workflow.indexOf('name: Upload installer artifacts');
  assert.ok(buildIndex >= 0 && nsisIndex > buildIndex && uploadIndex > nsisIndex);
  assert.match(workflow, /npm run build/);
  assert.match(workflow, /npx electron-builder --win nsis --x64/);
});

test('Windows workflow creates checksums and reports artifact upload failures explicitly', () => {
  assert.match(workflow, /name: Generate installer SHA-256 checksums/);
  assert.match(workflow, /Get-FileHash -Algorithm SHA256/);
  assert.match(workflow, /installer-sha256\.txt/);
  assert.match(workflow, /continue-on-error:\s*true/);
  assert.match(workflow, /name: Diagnose artifact upload failure/);
  assert.match(workflow, /ARTIFACT_UPLOAD_FAILED/);
  assert.match(workflow, /if: always\(\) && steps\.upload-installer\.outcome == 'failure'/);
});

test('Windows workflow artifact includes installer and checksum with explicit no-files failure', () => {
  const uploadBlock = workflow.slice(workflow.indexOf('name: Upload installer artifacts'), workflow.indexOf('name: Diagnose artifact upload failure'));
  assert.match(uploadBlock, /frontend\/release\/\*\.exe/);
  assert.match(uploadBlock, /frontend\/release\/installer-sha256\.txt/);
  assert.match(uploadBlock, /if-no-files-found:\s*error/);
  assert.match(uploadBlock, /retention-days:\s*14/);
});


test('Windows workflow validates package metadata before installing dependencies', () => {
  assert.match(workflow, /name: Validate desktop package configuration/);
  assert.match(workflow, /PACKAGE_PREFLIGHT_FAILED/);
  assert.match(workflow, /package-lock\.json/);
  assert.match(workflow, /required npm script/);
  assert.match(workflow, /electron-builder --win nsis --x64 --publish never/);
});

test('Windows workflow never publishes releases and verifies non-empty installer hashes', () => {
  assert.match(workflow, /electron-builder --win nsis --x64 --publish never/);
  assert.match(workflow, /installer\.Length -le 0/);
  assert.match(workflow, /SHA-256 verification failed/);
  assert.match(workflow, /steps\.upload-installer\.outputs\.artifact-url/);
});


test('Windows workflow caches npm by package manifest and publishes build provenance', () => {
  assert.match(workflow, /cache:\s*npm/);
  assert.match(workflow, /cache-dependency-path:\s*frontend\/package\.json/);
  assert.match(workflow, /name: Generate installer build manifest/);
  assert.match(workflow, /installer-build-info\.txt/);
  assert.match(workflow, /GITHUB_SHA/);
  assert.match(workflow, /GITHUB_RUN_ID/);
  const uploadBlock = workflow.slice(workflow.indexOf('name: Upload installer artifacts'), workflow.indexOf('name: Diagnose artifact upload failure'));
  assert.match(uploadBlock, /frontend\/release\/installer-build-info\.txt/);
});


test('Windows workflow generates a missing lockfile, installs with npm ci, and uploads the lockfile for review', () => {
  assert.match(workflow, /name: Generate package lockfile when missing/);
  assert.match(workflow, /npm install --package-lock-only --ignore-scripts --no-audit --no-fund --progress=false/);
  assert.match(workflow, /LOCKFILE_GENERATION_FAILED/);
  assert.match(workflow, /lockfileVersion/);
  assert.match(workflow, /ConvertFrom-Json -ErrorAction Stop/);
  assert.match(workflow, /ConvertFrom-Json -AsHashtable -ErrorAction Stop/);
  const lockStep = workflow.slice(workflow.indexOf('name: Generate package lockfile when missing'), workflow.indexOf('name: Upload package lockfile for review'));
  assert.match(lockStep, /\$pkg = Get-Content -Raw -LiteralPath package\.json/);
  assert.match(lockStep, /npm created a lockfile that is not valid JSON/);
  assert.match(workflow, /\$lock\.packages\[''\]/);
  assert.match(workflow, /lockfile root metadata does not match package\.json/);
  assert.match(workflow, /name: Install dependencies with npm ci/);
  assert.match(workflow, /npm ci --no-audit --no-fund --progress=false/);
  assert.match(workflow, /DEPENDENCY_INSTALL_FAILED/);
  assert.match(workflow, /registry\.npmjs\.org DNS\/network\/proxy access/);
  assert.match(workflow, /name: Upload package lockfile for review/);
  assert.match(workflow, /name: Diagnose package lockfile artifact upload failure/);
  assert.match(workflow, /path: frontend\/package-lock\.json/);
});
