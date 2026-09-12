# Módulo RAG — retrieval sobre leads indexados (Latinnova MIA)

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

`rag/schema.sql` solo habilita la extensión `pgvector` (`CREATE EXTENSION IF NOT EXISTS vector`) —
las tablas del vector store y del docstore las crea LlamaIndex automáticamente en el primer `ingest`.

### Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

Los tests no requieren N8N, Postgres ni OpenAI: cubren `_latest_matches_by_pair`
(la normalización de los dos schemas de `resultados_match`, ver §4) usando las
fixtures reales en `tests/fixtures/`.

## 7. Estructura del repositorio

```
proyecto-mia-rag-module/
├── README.md
├── .gitignore
├── requirements-dev.txt
├── rag/
│   ├── schema.sql          # Bootstrap: CREATE EXTENSION vector
│   ├── config.py           # Env vars (N8N_URL, DATABASE_URL, OPENAI_API_KEY, ...)
│   ├── n8n_reader.py       # N8N Data Tables API → LlamaIndex Document[]
│   ├── ingest.py           # IngestionPipeline (LlamaIndex): embeddings + upsert incremental
│   ├── query_engine.py     # Retrieval (PGVectorStore) + síntesis GPT-4o-mini + citación
│   └── requirements.txt
└── tests/
    ├── conftest.py         # Env vars dummy para poder importar rag.config sin credenciales reales
    ├── test_n8n_reader.py  # Tests de _latest_matches_by_pair (normalización de schemas)
    └── fixtures/           # Muestras reales de los dos schemas de resultados_match
        ├── resultados_match_entry_sample.json
        └── resultados_match_todos_los_resultados_raw_sample.json
```

## 8. Pendientes conocidos

- Cobertura de `post_url` al 70% — evaluar si ampliar en el pipeline original (WF2/WF3) o
  documentar como límite conocido.
- Enriquecimiento histórico de scoring limitado a ~15% de las evaluaciones por inestabilidad
  de IDs internos en las N8N Data Tables entre recargas.
- El caso `top_10_matches` (schema anidado) en `test_n8n_reader.py` es sintético — no se
  capturó una muestra real de ese campo durante el debugging original, solo de
  `todos_los_resultados`. Si aparece un caso real, reemplazar el fixture sintético.
- Sin interfaz de consulta más allá del CLI (`python -m rag.query_engine`); una página nueva
  en el dashboard Streamlit del proyecto original sería la extensión natural.

## Referencias

- Proyecto original: https://github.com/eapazminoSTI/proyecto-mia-matching-pipeline
- N8N: https://n8n.io
- OpenAI: https://platform.openai.com (modelos: `gpt-4o-mini-2024-07-18`, `text-embedding-3-small`)
