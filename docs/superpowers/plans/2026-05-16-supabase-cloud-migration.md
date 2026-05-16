# Supabase Cloud Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the S&P 500 heatmap from local file-based serving to a fully cloud architecture: GitHub Actions runs the pipeline and uploads `output.json` to Supabase Storage; GitHub Pages hosts the HTML; the HTML fetches data via `fetch()` with cache busting.

**Architecture:** Python pipeline runs unchanged in GitHub Actions on a daily cron schedule. The only new step is a `curl PUT` that uploads `data/output.json` to a public Supabase Storage bucket after the pipeline succeeds. The HTML migrates from reading `window.SP500_DATA` (script tag injection, `file://`-only) to an async `fetch()` with cache busting, with explicit loading and error states.

**Tech Stack:** Python 3.11, GitHub Actions, Supabase Storage REST API, GitHub Pages, `curl`, Python `unittest`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.gitignore` | Create | Exclude `.venv/`, `data/cache/`, `data/output.json`, `data/data.js` |
| `.github/workflows/pipeline.yml` | Create | Cron schedule + pipeline compute + Supabase upload |
| `pipeline/aggregate.py` | Modify | Remove `data.js` generation from `write_outputs()` |
| `config.json` | Modify | Remove `js_path` key from `output` block |
| `docs/sp500-heatmap.html` | Create (moved) | HTML with fetch-based data loading, loading/error states |
| `sp500-heatmap.html` | Delete | Replaced by `docs/sp500-heatmap.html` |
| `data/data.js` | Delete | No longer generated |
| `actualizar_scheduler.bat` | Delete | Replaced by GitHub Actions |
| `tests/test_aggregate.py` | Create | Unit test for `write_outputs()` |

---

## Task 1: Initialize git repository and .gitignore

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Initialize git repo**

Run from the project root:
```powershell
git init
git branch -M main
```

Expected: `Initialized empty Git repository in ...`

- [ ] **Step 2: Create .gitignore**

Create `.gitignore` at the project root with this exact content:
```
.venv/
__pycache__/
*.pyc
data/cache/
data/output.json
data/data.js
```

- [ ] **Step 3: Delete files that should not be committed**

```powershell
Remove-Item -Force "data\data.js" -ErrorAction SilentlyContinue
Remove-Item -Force "actualizar_scheduler.bat" -ErrorAction SilentlyContinue
```

- [ ] **Step 4: Stage and commit everything except ignored files**

```powershell
git add .gitignore config.json requirements.txt run_all.py actualizar.bat CLAUDE.md
git add pipeline\ data\schwab_manual.json docs\
git commit -m "chore: initial commit — local pipeline baseline before cloud migration"
```

Expected: commit succeeds, `.venv/` and `data/cache/` are NOT staged.

---

## Task 2: Create Supabase project and public bucket (manual setup)

**Files:** none — this is UI-only setup. Record the outputs for use in Tasks 3 and 6.

- [ ] **Step 1: Create a Supabase project**

  Go to https://supabase.com → New project. Choose a region close to you (e.g., `us-east-1`). Wait for the project to provision (~2 min).

- [ ] **Step 2: Create the storage bucket**

  In the Supabase dashboard: Storage → New bucket
  - Name: `heatmap-data`
  - Public bucket: **ON** (toggle must be green)
  - Click "Save"

- [ ] **Step 3: Record the two values you need**

  Project Settings → API:
  - **Project URL** → looks like `https://abcxyzabcxyz.supabase.co` → save as `SUPABASE_URL`
  - **service_role** key (under "Project API keys", click "Reveal") → save as `SUPABASE_SERVICE_ROLE_KEY`

  Store these somewhere safe temporarily. They go into GitHub secrets in Task 3.

- [ ] **Step 4: Verify the public read URL**

  The URL that the HTML will use:
  ```
  https://<your-project-ref>.supabase.co/storage/v1/object/public/heatmap-data/output.json
  ```
  This URL will return 404 until the first pipeline run. That is expected.

---

## Task 3: Create GitHub repository and configure environment secrets (manual setup)

**Files:** none — this is UI-only setup.

- [ ] **Step 1: Create a GitHub repository**

  Go to https://github.com/new
  - Repository name: `heatmap-sp500`
  - Visibility: Public (required for free GitHub Pages)
  - Do NOT initialize with README (the repo already has files)

- [ ] **Step 2: Add the remote and push**

  ```powershell
  git remote add origin https://github.com/<your-username>/heatmap-sp500.git
  git push -u origin main
  ```

- [ ] **Step 3: Create the `production` environment**

  In GitHub: repo → Settings → Environments → New environment
  - Name: `production`
  - Click "Configure environment"
  - No protection rules needed — leave defaults

- [ ] **Step 4: Add environment secrets**

  Still in the `production` environment page → "Environment secrets" → "Add secret":

  | Secret name | Value |
  |---|---|
  | `SUPABASE_URL` | The Project URL from Task 2 Step 3 |
  | `SUPABASE_SERVICE_ROLE_KEY` | The service_role key from Task 2 Step 3 |

---

## Task 4: Remove data.js generation from pipeline

**Files:**
- Modify: `pipeline/aggregate.py`
- Modify: `config.json`
- Create: `tests/test_aggregate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_aggregate.py`:
```python
import json
import tempfile
import unittest
from pathlib import Path


class TestWriteOutputsNoDataJs(unittest.TestCase):
    def test_does_not_write_data_js(self):
        from pipeline.aggregate import write_outputs

        data = {
            "meta": {"updated_at": "2026-05-16T22:00:00"},
            "indices": {},
            "sectors": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "output": {
                    "json_path": f"{tmpdir}/output.json",
                    "cache_dir": f"{tmpdir}/cache",
                    "news_in_output": 5,
                }
            }
            write_outputs(data, cfg)

            self.assertTrue(
                Path(f"{tmpdir}/output.json").exists(),
                "output.json debe existir",
            )
            self.assertFalse(
                Path(f"{tmpdir}/data.js").exists(),
                "data.js NO debe existir",
            )

    def test_output_json_is_valid(self):
        from pipeline.aggregate import write_outputs

        data = {
            "meta": {"updated_at": "2026-05-16T22:00:00", "run_status": "success"},
            "indices": {"SPY": {"ytd": 5.2, "daily_change": 0.3}},
            "sectors": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = {
                "output": {
                    "json_path": f"{tmpdir}/output.json",
                    "cache_dir": f"{tmpdir}/cache",
                    "news_in_output": 5,
                }
            }
            write_outputs(data, cfg)

            with open(f"{tmpdir}/output.json", encoding="utf-8") as f:
                loaded = json.load(f)

            self.assertEqual(loaded["meta"]["updated_at"], "2026-05-16T22:00:00")
            self.assertEqual(loaded["indices"]["SPY"]["ytd"], 5.2)
```

- [ ] **Step 2: Run the test — expect it to FAIL**

```powershell
.venv\Scripts\python -m unittest tests.test_aggregate -v
```

Expected: `FAIL: test_does_not_write_data_js` — because `write_outputs` still writes `data.js`.

- [ ] **Step 3: Remove data.js generation from aggregate.py**

In `pipeline/aggregate.py`, find the `write_outputs` function and replace it entirely with:

```python
def write_outputs(data: dict, cfg: dict):
    """Escribe data/output.json. Consumido por el HTML via fetch() desde Supabase Storage."""
    json_path = Path(cfg["output"]["json_path"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Escrito: {json_path}")
```

The exact old block to replace (lines 196–219 in the original file):
```python
def write_outputs(data: dict, cfg: dict):
    """
    Escribe data/output.json (legible) y data/data.js (consumido por el HTML).
    data.js usa window.SP500_DATA para funcionar sin servidor (file:// protocol).
    """
    # output.json
    json_path = Path(cfg["output"]["json_path"])
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Escrito: {json_path}")

    # data.js
    js_path = Path(cfg["output"]["js_path"])
    js_path.parent.mkdir(parents=True, exist_ok=True)
    json_inline = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js_content  = (
        f"// Auto-generado por aggregate.py — {data['meta']['updated_at']}\n"
        f"// NO editar manualmente\n"
        f"window.SP500_DATA = {json_inline};\n"
    )
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js_content)
    logger.info(f"Escrito: {js_path}")
```

- [ ] **Step 4: Remove js_path from config.json**

In `config.json`, find the `output` block and remove the `js_path` line:

```json
  "output": {
    "json_path": "data/output.json",
    "cache_dir": "data/cache",
    "news_in_output": 5
  }
```

- [ ] **Step 5: Run the tests — expect both to PASS**

```powershell
.venv\Scripts\python -m unittest tests.test_aggregate -v
```

Expected output:
```
test_does_not_write_data_js (tests.test_aggregate.TestWriteOutputsNoDataJs) ... ok
test_output_json_is_valid (tests.test_aggregate.TestWriteOutputsNoDataJs) ... ok
----------------------------------------------------------------------
Ran 2 tests in 0.XXXs
OK
```

- [ ] **Step 6: Verify the pipeline still runs end-to-end locally**

```powershell
$env:PYTHONIOENCODING = "utf-8"; .venv\Scripts\python run_all.py
```

Expected: pipeline completes, `data/output.json` is written, no mention of `data.js` in the logs.

- [ ] **Step 7: Commit**

```powershell
git add pipeline\aggregate.py config.json tests\test_aggregate.py
git commit -m "feat: remove data.js generation, pipeline now writes only output.json"
```

---

## Task 5: Create GitHub Actions workflow

**Files:**
- Create: `.github/workflows/pipeline.yml`

- [ ] **Step 1: Create the workflow directory**

```powershell
New-Item -ItemType Directory -Force ".github\workflows"
```

- [ ] **Step 2: Create the workflow file**

Create `.github/workflows/pipeline.yml` with this exact content:

```yaml
name: S&P 500 Heatmap — Pipeline

on:
  schedule:
    # 21:30 UTC = 4:30 PM ET (invierno/EST) | 5:30 PM ET (verano/EDT)
    # Mercado cierra 4:00 PM ET — mínimo 30 min de margen en ambas zonas horarias
    - cron: '30 21 * * 1-5'
  workflow_dispatch:

jobs:
  pipeline:
    runs-on: ubuntu-latest
    environment: production

    env:
      HF_HUB_CACHE: /home/runner/.cache/huggingface/hub
      PYTHONIOENCODING: utf-8

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Cache HuggingFace models
        uses: actions/cache@v4
        with:
          path: ${{ env.HF_HUB_CACHE }}
          key: hf-${{ hashFiles('config.json') }}

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run pipeline
        run: python run_all.py
        # sys.exit(1) on status=failed cancels the upload step

      - name: Upload output.json to Supabase Storage
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: |
          curl -fsS -X PUT \
            "${SUPABASE_URL}/storage/v1/object/heatmap-data/output.json" \
            -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
            -H "Content-Type: application/json" \
            -H "x-upsert: true" \
            -H "Cache-Control: no-cache, no-store, must-revalidate" \
            --data-binary @data/output.json
```

- [ ] **Step 3: Commit**

```powershell
git add .github\workflows\pipeline.yml
git commit -m "feat: add GitHub Actions workflow with cron schedule and Supabase upload"
```

---

## Task 6: Migrate HTML and move to docs/

**Files:**
- Create: `docs/sp500-heatmap.html` (migrated from root)
- Delete: `sp500-heatmap.html` (root copy)

**Prerequisite:** You need the Supabase Project URL from Task 2 Step 3. Replace every occurrence of `YOUR_PROJECT_REF` below with your actual project reference (the subdomain part of the URL, e.g., `abcxyzabcxyz`).

- [ ] **Step 1: Create the docs/ directory and move the HTML**

```powershell
New-Item -ItemType Directory -Force "docs"
git mv sp500-heatmap.html docs\sp500-heatmap.html
```

- [ ] **Step 2: Remove the data.js script tag (lines 10–11)**

In `docs/sp500-heatmap.html`, remove these two lines from the `<head>`:
```html
  <!-- data.js es generado por run_all.py — expone window.SP500_DATA -->
  <script src="data/data.js"></script>
```

- [ ] **Step 3: Add DATA_URL constant and loadData() helper**

Immediately after the opening `<script>` tag (the one that opens the main script block, before `const STATIC = {`), insert:

```javascript
const DATA_URL = "https://YOUR_PROJECT_REF.supabase.co/storage/v1/object/public/heatmap-data/output.json";

async function loadData(bustCache = true) {
  const url = bustCache ? `${DATA_URL}?v=${Date.now()}` : DATA_URL;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

```

- [ ] **Step 4: Replace the init() IIFE with the async fetch-based version**

Find and replace the entire `(function init() { ... })();` block (from `(function init()` through the final `})();` that closes it). Replace it with:

```javascript
(async function init() {
  const grid  = document.getElementById('sector-grid');
  const badge = document.getElementById('update-badge');

  grid.innerHTML = `
    <div class="no-data-state" style="grid-column:1/-1">
      <h2>Cargando datos...</h2>
      <p>Obteniendo datos desde Supabase Storage.</p>
    </div>`;

  let data;
  try {
    data = await loadData();
  } catch (err) {
    grid.innerHTML = `
      <div class="no-data-state" style="grid-column:1/-1">
        <h2>Error al cargar datos</h2>
        <p>No fue posible obtener <code>output.json</code> desde Supabase Storage.</p>
        <p style="margin-top:16px;font-size:12px;color:var(--text-dim)">Verificá tu conexión o que el bucket <code>heatmap-data</code> sea público.</p>
      </div>`;
    if (badge) badge.textContent = '⚠ Error al cargar datos';
    return;
  }

  const meta   = data.meta || {};
  const status = meta.run_status || 'unknown';

  if (badge) {
    const dt = meta.updated_at ? meta.updated_at.replace('T', ' ').slice(0, 16) : '—';
    badge.innerHTML = `&#128197; ${dt} <span class="run-status-badge ${status}">${status}</span>`;
  }

  renderIndices(data.indices || {});
  allSectors = data.sectors || [];
  applySort('ytd');

  document.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', () => applySort(btn.dataset.sort));
  });

  (function() {
    const INTERVAL_SECONDS = 300;
    const TOAST_HIDE_MS    = 5000;

    let _lastUpdatedAt = meta.updated_at ?? null;
    let _countdown     = INTERVAL_SECONDS;
    let _countdownTimer;
    let _checkPending  = false;
    let _toastTimer;

    const elCountdown = document.getElementById('countdown-val');
    const elStatus    = document.getElementById('reload-status');
    const elNow       = document.getElementById('reload-now-btn');

    function showToast(msg) {
      const toast = document.getElementById('update-toast');
      if (!toast) return;
      toast.querySelector('.toast-msg').textContent = msg;
      toast.classList.add('visible');
      clearTimeout(_toastTimer);
      _toastTimer = setTimeout(() => toast.classList.remove('visible'), TOAST_HIDE_MS);
    }

    async function checkForUpdates() {
      if (_checkPending) return;
      _checkPending = true;
      setStatus('Verificando...');
      try {
        const freshData = await loadData();
        const newTs = freshData?.meta?.updated_at ?? null;
        if (newTs && newTs !== _lastUpdatedAt) {
          _lastUpdatedAt = newTs;
          renderIndices(freshData.indices || {});
          allSectors = freshData.sectors || [];
          applySort(currentSort);
          const _badge = document.getElementById('update-badge');
          if (_badge) {
            const _dt = (freshData.meta.updated_at || '').replace('T', ' ').slice(0, 16);
            const _st = freshData.meta.run_status || 'success';
            _badge.innerHTML = `&#128197; ${_dt} <span class="run-status-badge ${_st}">${_st}</span>`;
          }
          setStatus('Actualizado', true);
          showToast('Datos actualizados · ' + (freshData.meta.updated_at || '').replace('T', ' ').slice(11, 16));
        } else {
          setStatus('Sin cambios');
        }
      } catch (e) {
        setStatus('Error de lectura');
      } finally {
        _checkPending = false;
        scheduleNext();
      }
    }

    function setStatus(txt, highlight) {
      if (!elStatus) return;
      elStatus.textContent = txt;
      elStatus.className   = 'reload-status' + (highlight ? ' updated' : '');
      if (highlight) setTimeout(() => { elStatus.className = 'reload-status'; }, 3000);
    }

    function scheduleNext() {
      _countdown = INTERVAL_SECONDS;
      clearInterval(_countdownTimer);
      _countdownTimer = setInterval(function() {
        _countdown--;
        if (elCountdown) elCountdown.textContent = _countdown + 's';
        if (_countdown <= 0) {
          clearInterval(_countdownTimer);
          checkForUpdates();
        }
      }, 1000);
    }

    if (elNow) elNow.addEventListener('click', function() {
      clearInterval(_countdownTimer);
      _countdown = 0;
      checkForUpdates();
    });

    scheduleNext();
  })();
})();
```

- [ ] **Step 5: Verify the DATA_URL is correct**

In `docs/sp500-heatmap.html`, confirm that `DATA_URL` matches exactly:
```
https://<your-project-ref>.supabase.co/storage/v1/object/public/heatmap-data/output.json
```
The path must include `/public/` — this is what makes the read unauthenticated.

- [ ] **Step 6: Test locally with a dev server**

```powershell
.venv\Scripts\python -m http.server 8000
```

Open `http://localhost:8000/docs/sp500-heatmap.html` in a browser (with internet active).

Expected before the first pipeline run: the loading state appears briefly, then an error state is shown ("Error al cargar datos") because `output.json` doesn't exist in Supabase yet. This is correct — the error state is working.

- [ ] **Step 7: Commit**

```powershell
git add docs\sp500-heatmap.html
git commit -m "feat: migrate HTML to fetch-based data loading from Supabase Storage"
```

---

## Task 7: Configure GitHub Pages (manual) and push

**Files:** none — this is UI configuration + a git push.

- [ ] **Step 1: Push all commits to GitHub**

```powershell
git push origin main
```

- [ ] **Step 2: Configure GitHub Pages**

In the GitHub repo: Settings → Pages
- Source: "Deploy from a branch"
- Branch: `main`
- Folder: `/docs`
- Click "Save"

Wait ~1 minute. GitHub will show the Pages URL: `https://<your-username>.github.io/heatmap-sp500/`

The heatmap URL will be: `https://<your-username>.github.io/heatmap-sp500/sp500-heatmap.html`

---

## Task 8: First run and end-to-end verification

**Files:** none — verification only.

- [ ] **Step 1: Trigger the pipeline manually**

In GitHub: repo → Actions → "S&P 500 Heatmap — Pipeline" → "Run workflow" → "Run workflow"

- [ ] **Step 2: Monitor the run**

Watch the workflow in real time. Each step should show green. Expected durations:
- Cache HuggingFace models: ~3 min first time, <10s with cache
- Install dependencies: ~1-2 min
- Run pipeline: ~5-8 min (FinBERT inference on 11 sectors)
- Upload to Supabase: ~5s

If any step fails, click it to read the logs.

- [ ] **Step 3: Verify output.json in Supabase Storage**

In Supabase dashboard: Storage → heatmap-data → verify `output.json` appears. Click it and confirm it's valid JSON with `meta.updated_at` set to today's timestamp.

- [ ] **Step 4: Verify the heatmap loads**

Open `https://<your-username>.github.io/heatmap-sp500/sp500-heatmap.html`

Expected:
- Loading state appears briefly ("Cargando datos...")
- Heatmap renders with 11 sector cards
- Date badge shows today's date with run status badge (success/partial)
- Auto-reload countdown starts at 300s

- [ ] **Step 5: Verify cache busting**

Open browser DevTools → Network tab → reload the page. Filter for `output.json`. Confirm the request URL has a `?v=<timestamp>` parameter and the response headers include `Cache-Control: no-cache`.

- [ ] **Step 6: Verify auto-reload mechanics**

With DevTools open on the Network tab, wait for or click "Verificar ahora". A new request to `output.json?v=<new-timestamp>` should appear. If `meta.updated_at` matches the previous value, the status shows "Sin cambios" — correct.

- [ ] **Step 7: Final commit if any fixes were made**

If you made any fixes during verification:
```powershell
git add -p   # stage only the fixes
git commit -m "fix: <describe what was fixed>"
git push origin main
```
