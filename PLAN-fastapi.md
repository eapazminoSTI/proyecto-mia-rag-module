# Plan: API REST con FastAPI sobre el módulo RAG

> Estado: **ejecutado** (redactado 2026-09-24 sobre `7100b5b`; implementado en `098d859`…`dd890b1`).
> Decisión §1: `_build_index()` se cachea con `functools.lru_cache` (`dd890b1`).

**Objetivo:** exponer una API REST junto a Streamlit (no lo reemplaza) que reutilice
`rag.query_engine.query()` tal cual, cerrando el gap de FastAPI con código real, tests,
Docker y CI.

## 1. Código nuevo — `rag/api.py`

- **`POST /query`**
  - Request: `{ "perfil": str (no vacío), "top_k": int (1–10, default 5) }`
  - Response: `{ "answer": str, "citations": [Citation] }`
  - Modelos Pydantic: `QueryRequest`, `QueryResponse`, `Citation`
    (`oportunidad_id`, `cargo`, `post_url`, `author_name`, `similarity_score` — los mismos
    campos que ya devuelve `_citation()`).
  - Endpoint `def` (no `async def`): `query()` es bloqueante (LlamaIndex/OpenAI/psycopg2
    síncronos) → FastAPI lo corre en threadpool.
  - Errores: fallo de DB/OpenAI → **503** con mensaje claro; input inválido → **422** automático.
- **`GET /health`** — `SELECT 1` contra Postgres, sin llamar a OpenAI (para healthcheck Docker).
- **`/docs`** (Swagger) viene incluido — útil como captura para portafolio.
- `rag/query_engine.py` no se modifica.
  - Opcional: cachear `_build_index()` (p. ej. `functools.lru_cache`) para no reconstruirlo
    en cada request. Decidir antes de ejecutar.

## 2. Dependencias

- Nuevo `requirements-api.txt`: `-e .`, `fastapi`, `uvicorn[standard]`.
- `requirements-dev.txt`: agregar `fastapi` y `httpx` (requerido por `TestClient`).

## 3. Tests — `tests/test_api.py` (cero tokens)

`TestClient` + monkeypatch de `query()`:

- consulta válida → 200 y esquema correcto
- `top_k` fuera de rango → 422
- `perfil` vacío → 422
- `query()` lanza excepción → 503
- `/health` con conexión a DB mockeada → 200

`tests/conftest.py` ya setea variables dummy, así que `rag.config` importa sin problemas.

## 4. Docker

- Nuevo servicio `api` en `docker-compose.yml`:
  - misma imagen (`build: .`), env `<<: *rag-env`
  - `entrypoint: ["uvicorn", "rag.api:app", "--host", "0.0.0.0", "--port", "8000"]`
    (sobrescribe el ENTRYPOINT de Streamlit, igual que ya hace `ingest`)
  - puerto `8000:8000`, `depends_on: db (service_healthy)`
  - healthcheck contra `http://localhost:8000/health`
- `Dockerfile`: instalar también `requirements-api.txt`. El ENTRYPOINT de Streamlit se mantiene.

## 5. CI (`.github/workflows/tests.yml`)

- Job `pytest`: ya corre los tests nuevos al instalar `requirements-dev.txt`.
- Job `docker-build`: ya valida el compose (`docker compose config -q`). No hace falta job nuevo.

## 6. README

Nueva sección "API REST":
- cómo levantarla: `docker compose up api`
- ejemplo `curl -X POST localhost:8000/query -H "Content-Type: application/json" -d '{"perfil": "...", "top_k": 5}'`
- enlace a `http://localhost:8000/docs`

## 7. Verificación

- [x] `pytest tests/ -v` local en verde
- [ ] CI verde en GitHub
- [x] `docker compose up api` con claves dummy → `/health` 200 y `/docs` carga
- [ ] **Opcional (gasta tokens OpenAI, pedir confirmación):** `/query` real — requiere
      haber corrido antes `docker compose --profile ingest run ingest` con claves reales

## 8. Commits sugeridos

1. `feat: agregar API REST con FastAPI sobre el query engine`
2. `test: cubrir endpoints de la API con TestClient`
3. `feat: servicio api en docker-compose con healthcheck`
4. `docs: documentar la API REST en el README`

## 9. Después — en Career-Ops (otra sesión, con confirmación)

- Agregar FastAPI a `cv.md` (skills + descripción del proyecto) y a `modes/_profile.md`.
- Actualizar la memoria del módulo RAG: FastAPI → cerrado.
- `upskill.mjs` dejará de reportar FastAPI como gap en la próxima corrida.

**Esfuerzo estimado:** 1–2 sesiones cortas.
