# Módulo RAG — retrieval sobre leads indexados (Latinnova MIA)

[![Tests](https://github.com/eapazminoSTI/proyecto-mia-rag-module/actions/workflows/tests.yml/badge.svg)](https://github.com/eapazminoSTI/proyecto-mia-rag-module/actions/workflows/tests.yml)

> **Estado:** primera pieza de la rama de mejoras post-tesis (portafolio) del proyecto
> [proyecto-mia-matching-pipeline](https://github.com/eapazminoSTI/proyecto-mia-matching-pipeline).
> Añade retrieval semántico real con citación de fuente sobre los leads ya scrapeados por
> ese pipeline — hasta ahora el pipeline solo clasificaba y hacía matching por score, sin
> un mecanismo de consulta tipo "¿qué leads matchean con este perfil y por qué?".
> Este repo **no reemplaza ni modifica** el pipeline N8N ni el dashboard Streamlit del
> proyecto original — es una capa nueva, de solo lectura, sobre las N8N Data Tables existentes.

---

## 1. Objetivo

Responder consultas en lenguaje natural del tipo *"¿qué leads matchean con este perfil y
por qué?"* recuperando los leads más relevantes por similitud semántica (no solo por el
matching determinístico de WF4 del pipeline original) y citando siempre la fuente original
(URL del post de LinkedIn).

## 2. Stack

| Componente | Elección | Razón |
|---|---|---|
| Vector store | **Postgres + pgvector** | Las N8N Data Tables no soportan búsqueda vectorial; se añade como infraestructura nueva y aislada, sin tocar el storage actual |
| Orquestación de indexado/retrieval | **LlamaIndex** (`IngestionPipeline`, `PGVectorStore`, `PostgresDocumentStore`) | Framework de orquestación dedicado en vez de lógica hecha a mano; `DocstoreStrategy.UPSERTS` maneja el hash de contenido y evita reembeber leads sin cambios |
| Embeddings | `text-embedding-3-small` (OpenAI) | GPT-4o-mini no genera embeddings; este es el modelo de embeddings equivalente, mismo proveedor que el resto del pipeline |
| Síntesis de respuesta | `gpt-4o-mini` | Consistente con el modelo ya usado en WF3/WF4/WF5 del pipeline original |

## 3. Flujo de datos

```
N8N Data Tables (fuente de verdad, sin modificar — instancia del proyecto original)
   linkedin_jobs + linkedin_posts + linkedin_ocr_results + Consultores + resultados_match
        │  lectura vía N8N REST API (rag/n8n_reader.py)
        ▼
  LlamaIndex Document[]  (1 documento = 1 fila de linkedin_jobs, enriquecida)
        │  rag/ingest.py → IngestionPipeline (embeddings + upsert incremental por hash)
        ▼
  Postgres + pgvector  (tablas data_rag_leads, data_rag_leads_docstore)
        │  rag/query_engine.py → retriever (top-k similitud) + GPT-4o-mini
        ▼
  Respuesta en lenguaje natural + citas [Lead N] con post_url/author_name reales
```

## 4. Mapeo de campos (confirmado contra la instancia N8N real, no solo documentación)

- **Contenido embebido** por lead: `cargo + ciudad + país + objetivo_del_cargo + prerrequisitos`
  (de `linkedin_jobs`) + `post_text` (de `linkedin_posts`, join por `post_id`) + `ocr_text`
  (de `linkedin_ocr_results`, join por `post_id`).
- **Citación de fuente**: `linkedin_posts.post_url` + `author_name` — **no** `linkedin_jobs.url`
  (ese campo es la imagen del post, no la fuente). En la validación real, 37 de 53 leads (70%)
  resolvieron `post_url`; el resto son huecos genuinos del pipeline (`post_id` sin fila
  correspondiente en `linkedin_posts`).
- **Enriquecimiento con scoring histórico de WF4**: `resultados_match` no tiene una fila por par
  consultor-oportunidad — es un snapshot por corrida con dos campos JSON serializados como string,
  con **schemas distintos entre sí**: `todos_los_resultados` usa campos planos
  (`oportunidad_id`, `consultor_id`, `score_match`, `tipo_oportunidad`), mientras que
  `top_10_matches` los anida bajo `ids.consultor`/`ids.oportunidad`. `rag/n8n_reader.py` normaliza
  ambos formatos. Ver `tests/fixtures/` para muestras reales de ambos schemas.
- **Limitación conocida**: los `id` internos de `linkedin_jobs`/`Consultores` referenciados en
  corridas históricas de `resultados_match` no son estables en el tiempo (la tabla se recargó entre
  experimentos) — de las 545 evaluaciones históricas disponibles, solo ~15% coinciden con leads
  actualmente presentes en `linkedin_jobs`. El join es seguro (nunca cruza el historial de un lead
  con otro por error), pero el enriquecimiento con score/motivo histórico es parcial por diseño,
  no un bug pendiente.

## 5. Validación real (no solo pruebas unitarias)

Ejecutado de punta a punta contra la instancia N8N real del proyecto original, un
Postgres+pgvector de prueba y la API de OpenAI:

| Métrica | Resultado |
|---|---|
| Leads leídos de `linkedin_jobs` | 53 |
| Leads con `post_url` resuelto | 37 (70%) |
| Leads con historial de scoring WF4 enriquecido | 8 |
| Leads embebidos en la primera ingesta | 53/53 |
| Consulta de ejemplo | *"Consultor senior con experiencia en transformación digital y metodologías ágiles"* → recuperó 5 leads (similitud 0.49–0.53), identificó y citó explícitamente los 2 más relevantes con `post_url` real de LinkedIn |

## 6. Cómo correr localmente

### Con Docker (recomendado)

`docker-compose.yml` levanta todo el stack sin instalar Python ni Postgres localmente:

- `db` — Postgres 16 + pgvector (`pgvector/pgvector:pg16`); `rag/schema.sql` se ejecuta
  al crear el volumen y habilita la extensión `vector`. Tiene healthcheck (`pg_isready`).
- `app` — la interfaz Streamlit (`Dockerfile`, `python:3.11-slim`), que arranca solo
  cuando `db` reporta healthy. Healthcheck contra `/_stcore/health`.
- `api` — la API REST FastAPI (`rag/api.py`, misma imagen), en `http://localhost:8000`.
  Healthcheck contra `/health` (hace `SELECT 1` en Postgres).
- `ingest` — ejecuta `python -m rag.ingest` bajo demanda (perfil `ingest`, no arranca con `up`).

```bash
cp .env.example .env          # completar N8N_API_KEY y OPENAI_API_KEY
docker compose up -d --build  # db + app → http://localhost:8501, api → http://localhost:8000
docker compose --profile ingest run --rm ingest   # sincroniza N8N → pgvector
```

`DATABASE_URL` no se define en `.env`: el compose la arma apuntando al servicio `db`.
`N8N_URL` usa `host.docker.internal` por defecto para alcanzar un N8N corriendo en el host.

### Sin Docker

Variables de entorno requeridas (`rag/.env`, no versionar):

```bash
N8N_URL=http://localhost:5678
N8N_API_KEY=...            # Settings → n8n API en la instancia N8N del proyecto original
DATABASE_URL=postgresql://usuario:password@localhost:5432/nombre_db
OPENAI_API_KEY=sk-...
```

```bash
pip install -r rag/requirements.txt
python -m rag.ingest          # sincroniza N8N → pgvector (incremental)
python -m rag.query_engine "Consultor senior en transformación digital"
```

### Instalación como paquete (para otros proyectos)

Este repo se puede instalar directamente con pip (usa `pyproject.toml`, no necesita
clonarse aparte) si en algún momento otro proyecto necesita importar `rag.query_engine`
sin clonar este repo. `app.py` (sección siguiente) **no** usa este mecanismo — al vivir
en el mismo repo, importa `rag` directamente:

```bash
pip install git+https://github.com/eapazminoSTI/proyecto-mia-rag-module.git@master
```

```python
from rag.query_engine import query
resultado = query("Consultor senior en transformación digital")
```

El consumidor debe proveer las mismas variables de entorno de la sección anterior
(`N8N_URL`/`N8N_API_KEY`, `DATABASE_URL`, `OPENAI_API_KEY`) antes de importar `rag.config`
— se leen con `os.environ[...]` al importar el paquete, sin valores por defecto para las
credenciales.

`rag/schema.sql` solo habilita la extensión `pgvector` (`CREATE EXTENSION IF NOT EXISTS vector`) —
las tablas del vector store y del docstore las crea LlamaIndex automáticamente en el primer `ingest`.

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

Los tests no requieren N8N, Postgres ni OpenAI: cubren `_latest_matches_by_pair`
(la normalización de los dos schemas de `resultados_match`, ver §4) usando las
fixtures reales en `tests/fixtures/`, y los endpoints de `rag/api.py` con
`query_engine.query` reemplazado por un doble de prueba. Los de `tests/agent/` corren el
grafo LangGraph completo (pausa, aprobar/rechazar, ciclo de reformulación y su tope) con
LLM y buscador simulados.

**CI:** corren automáticamente en cada push/PR vía GitHub Actions
(`.github/workflows/tests.yml`) — ver el badge al inicio de este README. El mismo
workflow construye la imagen Docker (`docker build`) para detectar si el `Dockerfile` se rompe.

### Interfaz Streamlit (`app.py`)

App de una sola página para hacer consultas sin usar el CLI. Vive en este mismo
repo — importa `rag.query_engine` directamente (import local, no instala nada vía
pip) — y no depende del dashboard del proyecto original ni de ninguna otra carpeta.

```bash
pip install -r requirements-app.txt
streamlit run app.py
# Abre en http://localhost:8501
```

Sin `N8N_API_KEY`/`DATABASE_URL`/`OPENAI_API_KEY` configuradas (`.env` en la raíz de
este repo), la app muestra qué variables faltan y no ofrece un formulario — no tiene
modo demo, igual que `rag.query_engine`: sin un índice real poblado no hay resultados
de similitud que simular.

### API REST (`rag/api.py`, FastAPI)

Expone la misma consulta que `app.py` y el CLI por HTTP, para que otros servicios
(p. ej. un workflow N8N con un nodo HTTP Request) consulten el índice sin importar Python.
No reemplaza a Streamlit: ambas reutilizan `rag.query_engine.query()` tal cual.

```bash
docker compose up -d api      # levanta db + api
# o sin Docker:
pip install -r requirements-api.txt
uvicorn rag.api:app --reload --port 8000
```

Documentación interactiva (Swagger): http://localhost:8000/docs

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | `SELECT 1` contra Postgres (sin llamar a OpenAI) — `503` si la DB no responde |
| `POST` | `/query` | Body `{"perfil": str, "top_k": int (1–10, por defecto 5)}` → `{"answer", "citations"}` |

```bash
curl -X POST http://localhost:8000/query -H "Content-Type: application/json"   -d '{"perfil": "Consultor senior en transformación digital", "top_k": 5}'
```

Errores: `422` si `perfil` está vacío o `top_k` fuera de rango; `503` si falla el motor
RAG (Postgres, OpenAI). Igual que `rag.query_engine`, requiere las variables de entorno
de la sección anterior al arrancar. La ingesta **no** se expone por HTTP a propósito
(reembebe vía OpenAI con costo) — sigue siendo `python -m rag.ingest`.

## 7. Agente LangGraph (fase 1)

Agente sobre el motor RAG de este repo: interpreta una solicitud en lenguaje natural, busca
leads, los puntúa contra el perfil, reformula la búsqueda si hay pocos buenos y **pausa para
que una persona apruebe** la shortlist antes de publicarla. Vive en `agent/`, al lado de `rag/`,
sin modificarlo: solo importa `_build_index` y `_citation` de `rag.query_engine`. El plan
completo y las decisiones de diseño están en `PLAN-langgraph.md`.

```mermaid
graph TD;
	__start__([START]) --> interpretar_solicitud;
	interpretar_solicitud["interpretar_solicitud<br/><small>LLM → criterios + consulta</small>"] --> buscar_oportunidades;
	buscar_oportunidades["buscar_oportunidades<br/><small>retriever pgvector, top-5</small>"] --> evaluar_encaje;
	evaluar_encaje["evaluar_encaje<br/><small>LLM → score 0-10 + razón</small>"] -.->|"&lt; 2 buenos y intentos &lt; 2"| reformular_consulta;
	reformular_consulta["reformular_consulta<br/><small>LLM → consulta más general</small>"] --> buscar_oportunidades;
	evaluar_encaje -.->|"≥ 1 bueno"| revision_humana;
	evaluar_encaje -.->|"0 buenos tras 2 reintentos"| __end__;
	revision_humana["revision_humana<br/><small>interrupt() ⏸ aprobar / rechazar</small>"] --> publicar;
	publicar["publicar<br/><small>output/shortlists/{thread_id}.json</small>"] --> __end__([END]);
```

"Bueno" = lead con score ≥ 6 (`UMBRAL`, `MIN_BUENOS` y `MAX_INTENTOS` en `agent/nodes.py`).

**Conceptos de LangGraph que usa:** estado tipado (`TypedDict` + modelos Pydantic), arista
condicional con ciclo acotado, human-in-the-loop con `interrupt()` + `Command(resume=...)`,
checkpointer (`InMemorySaver`) con `thread_id`, y salida estructurada (`with_structured_output`).
Los nodos reciben sus dependencias (LLM y buscador) inyectadas en un objeto `Deps`
(`agent/deps.py`), así que los tests corren con fakes deterministas sin gastar tokens.

### Cómo correrlo

Requiere el extra `[agent]` (LangGraph no entra en la imagen Docker), Postgres con los leads
ya ingeridos (§6) y `OPENAI_API_KEY`:

```bash
pip install -e ".[agent]"
docker compose up -d db
# DATABASE_URL apunta al Postgres del compose expuesto en el host
DATABASE_URL=postgresql://rag:rag@localhost:5432/rag \
  python -m agent.run "oportunidades para una consultora en evaluación de impacto"
```

El CLI muestra la shortlist y pregunta `¿Aprobar o rechazar? [a/r]`. Al aprobar escribe
`output/shortlists/{thread_id}.json` (ignorado por git) con la solicitud, la consulta final y
cada lead con su texto, autor, `post_url`, score y razón. Costo por corrida: centavos con
`gpt-4o-mini`.

### Prueba manual contra el RAG real (2026-10-20)

Cuatro solicitudes contra los 53 leads ingeridos:

| Solicitud | Reformulaciones | Shortlist (score ≥ 6) | Resultado |
|---|---|---|---|
| Consultor senior en transformación digital y metodologías ágiles | 0 | 2 | IICA Ecuador (8), VVOB Ecuador (7) |
| Consultora en evaluación de impacto | 0 | 2 | ConQuito – empleabilidad (9), HIAS – inclusión económica (8) |
| Consultorías en finanzas públicas para un economista | 0 | 3 | HIAS (8), ConQuito (7), HIAS – analista de programas **sin URL** (6) |
| Especialista en ciberseguridad industrial con certificación OT | 2 (tope) | 0 | Termina sin revisión humana: no hay leads de ese dominio |

Observaciones:

- El flujo completo funciona: ciclo de reformulación, tope de reintentos, pausa y publicación.
- Con 53 leads los resultados se **repiten**: "evaluación de impacto" y "finanzas públicas"
  devolvieron casi los mismos dos leads.
- El evaluador es **generoso**: en "finanzas públicas" le dio 8 a un lead justificándolo con
  "políticas públicas", algo que el texto del lead no menciona. La revisión humana existe
  justamente para esto.
- La primera versión del reformulador hacía la consulta **más larga** en cada ronda (y dejaba
  comillas literales); se corrigió el prompt para pedir una consulta más corta y general.

### Limitaciones

- **Checkpointer en memoria:** la pausa y la decisión ocurren en el mismo proceso; un hilo
  pausado se pierde al reiniciar.
- **Corpus chico** (53 leads, ~30% sin `post_url`): muchas solicitudes no tienen ningún lead
  afín, y los que no tienen URL pueden entrar a la shortlist.
- **El reformulador solo ve la última consulta:** puede repetir la misma consulta en dos
  rondas seguidas y gastar una búsqueda en vano.
- **Sin evaluación formal de calidad** de los scores: solo la prueba manual de arriba.
- Sin API ni servicio Docker para el agente todavía.

### Próximos pasos

- `PostgresSaver` para persistir hilos pausados entre procesos.
- Endpoints FastAPI `/agent/run` y `/agent/resume`.
- Webhook de N8N como acción de `publicar`.

## 8. Estructura del repositorio

```
proyecto-mia-rag-module/
├── README.md
├── .gitignore
├── .dockerignore
├── .env.example         # Plantilla de variables para docker compose
├── Dockerfile           # Imagen de app.py y rag/api.py (python:3.11-slim + healthcheck)
├── docker-compose.yml   # db (Postgres+pgvector) + app (Streamlit) + api (FastAPI) + ingest (bajo demanda)
├── .github/
│   └── workflows/
│       └── tests.yml    # CI: pytest + docker build en cada push/PR
├── pyproject.toml       # Empaquetado (pip install git+...)
├── requirements-dev.txt
├── requirements-app.txt # Dependencias de app.py (-e . + streamlit)
├── requirements-api.txt # Dependencias de rag/api.py (-e . + fastapi + uvicorn)
├── app.py               # Interfaz Streamlit de una sola página (independiente)
├── rag/
│   ├── schema.sql          # Bootstrap: CREATE EXTENSION vector
│   ├── config.py           # Env vars (N8N_URL, DATABASE_URL, OPENAI_API_KEY, ...)
│   ├── n8n_reader.py       # N8N Data Tables API → LlamaIndex Document[]
│   ├── ingest.py           # IngestionPipeline (LlamaIndex): embeddings + upsert incremental
│   ├── query_engine.py     # Retrieval (PGVectorStore) + síntesis GPT-4o-mini + citación
│   ├── api.py              # API REST FastAPI: GET /health, POST /query
│   └── requirements.txt
├── agent/               # Agente LangGraph (§7), extra opcional [agent]
│   ├── state.py            # AgentState + modelos Pydantic (Criterios, Lead, Evaluacion)
│   ├── deps.py             # Deps inyectables + implementaciones reales (OpenAI + retriever RAG)
│   ├── nodes.py            # Los 6 nodos y la ruta condicional tras evaluar
│   ├── graph.py            # build_graph(deps, checkpointer)
│   └── run.py              # CLI: python -m agent.run "..."
├── PLAN-langgraph.md    # Plan y decisiones del agente
└── tests/
    ├── agent/              # Tests del grafo con LLM y RAG simulados (sin __init__.py)
    ├── conftest.py         # Env vars dummy para poder importar rag.config sin credenciales reales
    ├── test_n8n_reader.py  # Tests de _latest_matches_by_pair (normalización de schemas)
    ├── test_api.py         # Tests de los endpoints FastAPI (sin N8N/Postgres/OpenAI)
    └── fixtures/           # Muestras reales de los dos schemas de resultados_match
        ├── resultados_match_entry_sample.json
        ├── resultados_match_todos_los_resultados_raw_sample.json
        ├── resultados_match_top_10_matches_entry_sample.json
        └── resultados_match_top_10_matches_raw_sample.json
```

## 9. Pendientes conocidos

- Cobertura de `post_url` al 70% — evaluar si ampliar en el pipeline original (WF2/WF3) o
  documentar como límite conocido.
- Enriquecimiento histórico de scoring limitado a ~15% de las evaluaciones por inestabilidad
  de IDs internos en las N8N Data Tables entre recargas.
- `app.py` es independiente a propósito (no está integrada al dashboard del proyecto
  original) para no mezclar el historial de git de ambos repos — ver nota en la
  cabecera de este README.

## Referencias

- Proyecto original: https://github.com/eapazminoSTI/proyecto-mia-matching-pipeline
- N8N: https://n8n.io
- OpenAI: https://platform.openai.com (modelos: `gpt-4o-mini-2024-07-18`, `text-embedding-3-small`)
