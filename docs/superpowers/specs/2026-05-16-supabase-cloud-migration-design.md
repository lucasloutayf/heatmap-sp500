# Spec: Migración a arquitectura cloud con Supabase

**Fecha:** 2026-05-16
**Estado:** Aprobado — listo para plan de implementación

---

## Contexto

El proyecto S&P 500 Heatmap corre actualmente de forma local en Windows: el pipeline Python es disparado por Task Scheduler, escribe `data/data.js` (con `window.SP500_DATA`), y el HTML lo lee vía `<script>` tag en `file://`. El objetivo es migrar a una arquitectura 100% cloud donde el HTML esté deployado y lea datos desde una URL pública.

---

## Componentes y roles

| Componente | Rol |
|---|---|
| **GitHub repository** | Fuente de verdad: código Python, `schwab_manual.json`, HTML |
| **GitHub Actions** | Orquestación + compute efímero + upload |
| **Supabase Storage** | Serving del JSON público (`output.json`) |
| **GitHub Pages** | Hosting del HTML estático |

Supabase se usa **exclusivamente como Storage**. No se usan Edge Functions ni pg_cron: el schedule y el compute quedan completamente en GitHub Actions.

---

## Flujo de extremo a extremo

```
21:30 UTC, lun–vie (= 4:30 PM ET invierno/EST | 5:30 PM ET verano/EDT)
│
├─ GitHub Actions: checkout del repo
├─ pip install con cache de FinBERT en HF_HUB_CACHE explícito
├─ python run_all.py  →  data/output.json  (sin credenciales cloud)
│   └─ si status=failed → sys.exit(1) → el step de upload no corre
│
└─ curl PUT  →  Supabase Storage  (service_role key, environment secret)
      Header: Cache-Control: no-cache, no-store, must-revalidate
      Header: x-upsert: true

Browser (desde GitHub Pages)
│
├─ carga inicial: loadData(bustCache=true)
│       → loading state visible mientras el fetch está en vuelo
│       → error visible si el fetch falla (no hay datos embebidos de fallback)
│       → render(data)
│
└─ cada 5 min: checkForUpdate()
      loadData() → validar data?.meta?.updated_at
      si cambió → render() + toast "Datos actualizados"
      si falla  → silencioso, mantiene los últimos datos cargados
```

---

## GitHub Actions workflow

Archivo: `.github/workflows/pipeline.yml`

### Schedule

```yaml
on:
  schedule:
    # 21:30 UTC = 4:30 PM ET (invierno/EST) | 5:30 PM ET (verano/EDT)
    # Mercado cierra 4:00 PM ET — mínimo 30 min de margen en ambas zonas
    - cron: '30 21 * * 1-5'
  workflow_dispatch:  # trigger manual desde la UI de GitHub
```

### Job

```yaml
jobs:
  pipeline:
    runs-on: ubuntu-latest
    environment: production          # secrets a nivel de environment, no de repo
    env:
      HF_HUB_CACHE: /home/runner/.cache/huggingface/hub
```

### Steps en orden

1. `actions/checkout@v4`
2. `actions/setup-python@v5` → Python 3.11
3. `actions/cache@v4` → path: `${{ env.HF_HUB_CACHE }}`, key: `hf-${{ hashFiles('config.json') }}`
   - La cache se invalida automáticamente si cambia el modelo en `config.json`
4. `pip install -r requirements.txt`
5. `python run_all.py` con `PYTHONIOENCODING: utf-8`
   - Si el pipeline termina en `status=failed`, hace `sys.exit(1)` → el step 6 no corre
6. Upload a Supabase Storage (único step con acceso a secretos):

```bash
curl -fsS -X PUT \
  "${SUPABASE_URL}/storage/v1/object/heatmap-data/output.json" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -H "x-upsert: true" \
  -H "Cache-Control: no-cache, no-store, must-revalidate" \
  --data-binary @data/output.json
```

`-fsS` en curl: falla con exit code ≠ 0 ante errores HTTP, silencioso en stdout, muestra errores.

### Estimado de minutos de GitHub Actions

Primera corrida: ~10-12 min (descarga de FinBERT ~440 MB). Corridas siguientes con cache: ~6-8 min. Con 20 días hábiles/mes: ~160 min — dentro del free tier de 2000 min/mes para Ubuntu.

---

## Supabase Storage

### Setup (una sola vez, manual en el dashboard)

1. Crear proyecto → anotar `Project URL` (ej: `https://abcxyz.supabase.co`)
2. Storage → New bucket:
   - Nombre: `heatmap-data`
   - Public bucket: **ON**
3. Project Settings → API → copiar `service_role` key

### URLs

| Operación | URL | Auth |
|---|---|---|
| Escritura (GitHub Actions) | `{SUPABASE_URL}/storage/v1/object/heatmap-data/output.json` | service_role key |
| Lectura (browser/HTML) | `{SUPABASE_URL}/storage/v1/object/public/heatmap-data/output.json` | ninguna |

El prefijo `/public/` en la URL de lectura es el mecanismo estándar de Supabase para servir objetos de buckets públicos sin autenticación. CORS funciona por defecto para GET en buckets públicos — no requiere configuración manual.

> **Dependencia operativa:** la URL pública de lectura solo funciona mientras el bucket `heatmap-data` esté marcado como **Public** en Supabase. Si el bucket se cambia a privado, todos los fetches del HTML devolverán 403. El bucket debe permanecer público para que el heatmap funcione.

### schwab_manual.json

Sin cambios. El archivo vive en el repo; GitHub Actions lo tiene disponible tras el checkout. Para actualizar ratings mensuales: editar el JSON, commit, push. El siguiente run lo toma automáticamente.

---

## Secretos

Dos secretos, almacenados en el **environment `production`** de GitHub (Settings → Environments → production → Environment secrets):

| Secret | Valor |
|---|---|
| `SUPABASE_URL` | `https://abcxyz.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJ...` (service role key) |

Reglas:
- Nunca en código, nunca en el HTML, nunca commiteados
- El `anon` key no se usa en ningún lado (bucket es público para lectura, service_role para escritura)
- La URL pública de lectura va hardcodeada en el HTML — **no es un secreto**

---

## Cambios en sp500-heatmap.html

### Qué se elimina

```html
<!-- Eliminar: -->
<script src="data/data.js"></script>
```

Y toda referencia a `window.SP500_DATA`.

### Qué se agrega

**Constante de configuración** (único lugar en el archivo con la URL):
```js
const DATA_URL = "https://abcxyz.supabase.co/storage/v1/object/public/heatmap-data/output.json";
```

**Helper de carga con cache busting encapsulado:**
```js
async function loadData(bustCache = true) {
  const url = bustCache ? `${DATA_URL}?v=${Date.now()}` : DATA_URL;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
```

`bustCache=true` por defecto. El parámetro hace explícita la intención y permite desactivarlo en tests. El doble mecanismo (`?v=timestamp` + `cache: 'no-store'`) cubre la CDN de Supabase y el cache del browser.

**Inicialización asíncrona con loading state y error visible:**
```js
// Al cargar la página — ya no hay datos embebidos
mostrarLoading();
loadData()
  .then(data => {
    currentUpdatedAt = data.meta.updated_at;
    render(data);
  })
  .catch(err => mostrarError(err));  // error visible, no silencioso
```

**Auto-reload con validación de meta:**
```js
async function checkForUpdate() {
  try {
    const data = await loadData();
    if (data?.meta?.updated_at && data.meta.updated_at !== currentUpdatedAt) {
      currentUpdatedAt = data.meta.updated_at;
      render(data);
      showToast("Datos actualizados");
    }
  } catch (e) {
    console.warn("Auto-reload falló silenciosamente:", e);
    // No interrumpe al usuario — sigue mostrando los últimos datos cargados
  }
}

setInterval(checkForUpdate, 5 * 60 * 1000);
```

### Lo que no cambia en el HTML

Toda la lógica de render, los estilos, el layout de sectores, el toast, y la lógica de comparación de datos son internos a `render()` y no se tocan.

---

## Cambios en el pipeline Python

### aggregate.py

Eliminar la escritura de `data/data.js` y el patrón `window.SP500_DATA`. Solo se escribe `output.json`.

```python
# Eliminar de write_outputs():
# js_path = Path(cfg["output"]["js_path"])
# ... todo el bloque de generación de data.js
```

### config.json

Eliminar la key `js_path` del bloque `output` (ya no se genera `data.js`):

```json
"output": {
  "json_path": "data/output.json",
  "cache_dir": "data/cache",
  "news_in_output": 5
}
```

### Todo lo demás

Sin cambios:
- `pipeline/fetch_prices.py`
- `pipeline/fetch_news.py`
- `pipeline/sentiment.py`
- `run_all.py`
- `actualizar.bat` (sigue funcionando para correr el pipeline localmente)

---

## Eliminaciones

| Antes | Reemplazado por |
|---|---|
| `data/data.js` | `data/output.json` via fetch |
| `window.SP500_DATA` | variable local desde fetch |
| Task Scheduler de Windows | GitHub Actions cron |
| `actualizar_scheduler.bat` | `.github/workflows/pipeline.yml` |

---

## GitHub Pages

El HTML se publica desde la carpeta `/docs` del branch principal. Pasos de setup:

1. Mover `sp500-heatmap.html` (y cualquier asset que referencie) a `docs/`
2. Settings → Pages → Branch: `main`, Folder: `/docs`

URL resultante: `https://<username>.github.io/heatmap-sp500/sp500-heatmap.html`

Este enfoque es el más simple: no requiere steps extra en el workflow ni actions adicionales de deploy. Todos los demás archivos del repo (config.json, requirements.txt, código Python) quedan fuera del directorio publicado.

> **Alternativa:** publicar vía GitHub Actions (`actions/upload-pages-artifact` + `actions/deploy-pages`) da más flexibilidad si en el futuro se necesita un paso de build. Para esta arquitectura no hay build, por lo que `/docs` es suficiente.

---

## Desarrollo local

El pipeline Python sigue corriendo sin cambios con `python run_all.py` o `actualizar.bat`. Para visualizar el heatmap localmente después de la migración, `file://` ya no funciona porque `fetch()` está diseñado para HTTP/HTTPS y `file://` tiene restricciones de origen opaco en browsers modernos. La alternativa práctica: `python -m http.server 8000` y abrir `localhost:8000/sp500-heatmap.html` con acceso a internet activo (el HTML sigue haciendo fetch a Supabase).

---

## Checklist de setup inicial (una sola vez)

- [ ] Crear proyecto en supabase.com
- [ ] Crear bucket `heatmap-data` (public ON)
- [ ] Copiar `Project URL` y `service_role` key
- [ ] En GitHub: Settings → Environments → New environment → `production`
- [ ] Agregar `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` como environment secrets
- [ ] Habilitar GitHub Pages desde branch principal, directorio raíz
- [ ] Actualizar `DATA_URL` en el HTML con la URL real del proyecto Supabase
- [ ] Ejecutar `workflow_dispatch` manualmente para verificar el primer run end-to-end
