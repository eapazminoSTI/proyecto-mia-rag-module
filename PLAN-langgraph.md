# PLAN-langgraph — Agente mínimo con LangGraph sobre el módulo RAG (fase 1)

> **Objetivo:** un agente LangGraph **real, con tests en verde y CI**, construido sobre el motor RAG de este repo.
> **Tiempo estimado:** ~8–10 h (un fin de semana).
> **Alcance:** fases 1 + 2 + human-in-the-loop básico de un plan mayor. Las fases siguientes (PostgresSaver, API del agente, webhook de n8n) quedan en la sección 8.

---

## 0. Decisiones tomadas (2026-10-17)

| # | Decisión | Elegido | Por qué |
|---|----------|---------|---------|
| 1 | Dónde vive el código | **Módulo `agent/` dentro de `proyecto-mia-rag-module`** | Reutiliza CI, Docker, `.env` y tests existentes. No hay que montar un repo nuevo con el tiempo justo. |
| 2 | Acción final | **Archivo local** `output/shortlists/{thread_id}.json` | Cero dependencias externas. El webhook de n8n queda para después. |
| 3 | Punto de partida | **Directo a código** (fase 1), consultando la doc cuando haga falta | Aprender construyendo; el curso queda como consulta. |
| 4 | Separación del RAG | **`agent/` al lado de `rag/`** y tests en **`tests/agent/`** | `rag/` no se modifica; el agente solo importa `_build_index` y `_citation`. `tests/agent/` va **sin `__init__.py`** para que no tape al paquete `agent`. |
| 5 | Dependencias del agente | **Extra opcional `[agent]`** en `pyproject.toml`; `requirements-dev.txt` instala `-e .[agent]` | La imagen Docker de API/Streamlit no carga LangGraph. |
| 6 | Empaquetado | **`[tool.setuptools.packages.find]`** con `include = ["rag*", "agent*"]` en vez de `packages = ["rag", "agent"]` | El `Dockerfile` solo copia `rag/`; una lista fija con `agent` rompe `pip install -e .` dentro de Docker. |
| 7 | Identificar leads | `Lead` lleva `oportunidad_id`; el evaluador responde por **índice** del lead | `post_url` puede ser `None` y el LLM puede alterar URLs. La shortlist incluye texto, autor y URL. |

## 1. Alcance del fin de semana

**Entra:**
- Grafo `StateGraph` con estado tipado, 6 nodos, una **arista condicional con ciclo** (reformular búsqueda) y **human-in-the-loop con `interrupt()`**.
- Checkpointer **en memoria** (`InMemorySaver`) para pausar y retomar.
- Herramienta `buscar_oportunidades` que llama al motor RAG **existente**.
- Salida estructurada con Pydantic (`with_structured_output`).
- Tests con **LLM y RAG simulados** (sin gastar tokens en CI).
- CLI para correrlo: `python -m agent.run "..."`.
- README con diagrama y limitaciones honestas.

**No entra (queda para después; NO mencionarlo como hecho):**
- `PostgresSaver` (persistencia en Postgres).
- Webhook de n8n.
- Endpoints FastAPI `/agent/run` y `/agent/resume`.
- Servicio en docker-compose.
- Bedrock / Claude.
- Perfil de consultor desde `N8NTableClient` (en este recorte el perfil llega en la solicitud).

## 2. Diseño del grafo

```
START
  │
  ▼
[1] interpretar_solicitud ── LLM (salida estructurada) → criterios + consulta
  │
  ▼
[2] buscar_oportunidades ─── motor RAG existente → leads con post_url
  │
  ▼
[3] evaluar_encaje ───────── LLM (salida estructurada) → score 0-10 + razón por lead
  │
  ├── ¿< 2 leads con score ≥ 6 y intentos < 2? ──► [4] reformular_consulta ──► [2]
  ▼
[5] revision_humana ──────── interrupt() ⏸  aprobar / rechazar
  │
  ▼
[6] publicar ─────────────── si aprobado: escribe output/shortlists/{thread_id}.json
  │
  ▼
 END
```

**Conceptos de LangGraph que demuestra:** estado tipado, nodos, aristas condicionales, ciclos con límite, `interrupt()` + `Command(resume=...)`, checkpointer y `thread_id`, salida estructurada.

## 3. Estructura de archivos

```
proyecto-mia-rag-module/
├── agent/
│   ├── __init__.py
│   ├── state.py        # AgentState (TypedDict) + modelos Pydantic
│   ├── deps.py         # Protocolos LLM/Retriever + implementaciones reales
│   ├── nodes.py        # Las 6 funciones de nodo
│   ├── graph.py        # build_graph(deps, checkpointer)
│   └── run.py          # CLI: correr, pausar, aprobar/rechazar
├── tests/
│   └── agent/          # sin __init__.py
│       └── test_agent.py   # Fakes + 5 tests
├── output/shortlists/  # (agregar a .gitignore)
└── PLAN-langgraph.md   # este archivo
```

> **Cómo se conecta con el RAG existente (revisado 2026-10-17):** `rag/query_engine.py:76` `query(perfil, top_k)` arma el retriever con `_build_index()`, **llama al LLM** y devuelve `{"answer", "citations"}`. Las citas solo traen metadata (`oportunidad_id`, `cargo`, `post_url`, `author_name`, `similarity_score`), **sin el texto del lead**. Por eso el agente **no usa `query()`**: usa directamente `_build_index().as_retriever(similarity_top_k=k).retrieve(consulta)` y reutiliza `_citation(node)` para la metadata y `node.get_content()` para el texto. Así se evita una llamada al LLM por búsqueda y el evaluador del agente recibe el texto completo. No duplicar lógica de LlamaIndex fuera de `deps.py`.
>
> **Empaquetado:** `pyproject.toml` declara `packages = ["rag"]`. Agregar `"agent"` a esa lista para que `pip install -e .` lo incluya.

## 4. Implementación paso a paso

### Paso 1 — Dependencias (15 min)

```bash
pip install langgraph langchain-openai
pip freeze | grep -E "langgraph|langchain-openai"
```

Este repo maneja dependencias en `pyproject.toml` (núcleo RAG) y `requirements-*.txt` (`-api`, `-app`, `-dev`). Agregar `langgraph>=X` y `langchain-openai>=Y` (con las versiones instaladas) a la lista `dependencies` de `pyproject.toml`, para que CI las instale con `pip install -e .` vía `requirements-dev.txt`. Agregar también `"agent"` a `packages`. Verificar que CI siga en verde **antes** de escribir código del agente.

### Paso 2 — Estado y modelos (`agent/state.py`, 30 min)

```python
from typing import TypedDict, Literal
from pydantic import BaseModel, Field


class Criterios(BaseModel):
    consulta: str = Field(description="Consulta para el motor RAG")
    perfil: str = Field(description="Resumen del perfil del consultor")
    temas: list[str] = Field(default_factory=list)


class Lead(BaseModel):
    texto: str
    post_url: str | None = None
    author_name: str | None = None


class Evaluacion(BaseModel):
    post_url: str | None
    score: int = Field(ge=0, le=10)
    razon: str


class Evaluaciones(BaseModel):
    items: list[Evaluacion]


class AgentState(TypedDict, total=False):
    solicitud: str
    criterios: Criterios
    leads: list[Lead]
    evaluaciones: list[Evaluacion]
    intentos: int
    decision: Literal["aprobar", "rechazar"]
    archivo: str | None
```

### Paso 3 — Dependencias inyectables (`agent/deps.py`, 45 min)

La clave para testear sin tokens: **los nodos no importan OpenAI ni LlamaIndex directamente**, reciben un objeto `Deps`.

```python
from dataclasses import dataclass
from typing import Protocol
from agent.state import Criterios, Lead, Evaluaciones


class Interprete(Protocol):
    def __call__(self, solicitud: str) -> Criterios: ...

class Evaluador(Protocol):
    def __call__(self, perfil: str, leads: list[Lead]) -> Evaluaciones: ...

class Reformulador(Protocol):
    def __call__(self, consulta: str, perfil: str) -> str: ...

class Buscador(Protocol):
    def __call__(self, consulta: str) -> list[Lead]: ...


@dataclass
class Deps:
    interpretar: Interprete
    evaluar: Evaluador
    reformular: Reformulador
    buscar: Buscador
    output_dir: str = "output/shortlists"


def deps_reales() -> Deps:
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def interpretar(solicitud):
        return llm.with_structured_output(Criterios).invoke(
            f"Extrae perfil, temas y una consulta de búsqueda de: {solicitud}")

    def evaluar(perfil, leads):
        listado = "\n".join(f"- [{l.post_url}] {l.texto[:500]}" for l in leads)
        return llm.with_structured_output(Evaluaciones).invoke(
            f"Perfil: {perfil}\nPuntúa de 0 a 10 el encaje de cada oportunidad y explica por qué:\n{listado}")

    def reformular(consulta, perfil):
        return llm.invoke(
            f"La búsqueda '{consulta}' dio pocos resultados buenos para el perfil '{perfil}'. "
            "Propón UNA consulta alternativa más amplia. Responde solo la consulta.").content.strip()

    def buscar(consulta, top_k: int = 5):
        from rag.query_engine import _build_index, _citation
        nodes = _build_index().as_retriever(similarity_top_k=top_k).retrieve(consulta)
        return [
            Lead(texto=n.get_content(),
                 post_url=_citation(n)["post_url"],
                 author_name=_citation(n)["author_name"])
            for n in nodes
        ]

    return Deps(interpretar, evaluar, reformular, buscar)
```

### Paso 4 — Nodos (`agent/nodes.py`, 1 h)

```python
import json, os
from langgraph.types import interrupt
from agent.state import AgentState

UMBRAL, MIN_BUENOS, MAX_INTENTOS = 6, 2, 2


def make_nodes(deps):
    def interpretar_solicitud(state: AgentState):
        return {"criterios": deps.interpretar(state["solicitud"]), "intentos": 0}

    def buscar_oportunidades(state: AgentState):
        return {"leads": deps.buscar(state["criterios"].consulta)}

    def evaluar_encaje(state: AgentState):
        ev = deps.evaluar(state["criterios"].perfil, state["leads"])
        return {"evaluaciones": ev.items}

    def reformular_consulta(state: AgentState):
        c = state["criterios"]
        nueva = deps.reformular(c.consulta, c.perfil)
        return {"criterios": c.model_copy(update={"consulta": nueva}),
                "intentos": state.get("intentos", 0) + 1}

    def revision_humana(state: AgentState):
        buenos = [e.model_dump() for e in state["evaluaciones"] if e.score >= UMBRAL]
        decision = interrupt({"shortlist": buenos, "pregunta": "¿aprobar o rechazar?"})
        return {"decision": decision}

    def publicar(state: AgentState, config):
        if state.get("decision") != "aprobar":
            return {"archivo": None}
        os.makedirs(deps.output_dir, exist_ok=True)
        thread_id = config["configurable"]["thread_id"]
        ruta = os.path.join(deps.output_dir, f"{thread_id}.json")
        buenos = [e.model_dump() for e in state["evaluaciones"] if e.score >= UMBRAL]
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump({"solicitud": state["solicitud"], "shortlist": buenos}, f,
                      ensure_ascii=False, indent=2)
        return {"archivo": ruta}

    return locals()


def ruta_tras_evaluar(state: AgentState) -> str:
    buenos = sum(1 for e in state["evaluaciones"] if e.score >= UMBRAL)
    if buenos < MIN_BUENOS and state.get("intentos", 0) < MAX_INTENTOS:
        return "reformular_consulta"
    return "revision_humana"
```

> Nota: `publicar` recibe `config` como segundo argumento (LangGraph lo inyecta) para leer el `thread_id`. Si la versión instalada exige tipo explícito, anotar `config: RunnableConfig` (`from langchain_core.runnables import RunnableConfig`).

### Paso 5 — Grafo (`agent/graph.py`, 30 min)

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from agent.state import AgentState
from agent.nodes import make_nodes, ruta_tras_evaluar


def build_graph(deps, checkpointer=None):
    n = make_nodes(deps)
    g = StateGraph(AgentState)
    for nombre in ["interpretar_solicitud", "buscar_oportunidades", "evaluar_encaje",
                   "reformular_consulta", "revision_humana", "publicar"]:
        g.add_node(nombre, n[nombre])

    g.add_edge(START, "interpretar_solicitud")
    g.add_edge("interpretar_solicitud", "buscar_oportunidades")
    g.add_edge("buscar_oportunidades", "evaluar_encaje")
    g.add_conditional_edges("evaluar_encaje", ruta_tras_evaluar,
                            ["reformular_consulta", "revision_humana"])
    g.add_edge("reformular_consulta", "buscar_oportunidades")
    g.add_edge("revision_humana", "publicar")
    g.add_edge("publicar", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
```

> Si el import `InMemorySaver` falla en la versión instalada, usar `from langgraph.checkpoint.memory import MemorySaver` (nombre anterior).

### Paso 6 — Tests (`tests/test_agent.py`, 1.5 h) — **el corazón del fin de semana**

Fakes deterministas, cero tokens:

```python
from langgraph.types import Command
from agent.deps import Deps
from agent.graph import build_graph
from agent.state import Criterios, Lead, Evaluacion, Evaluaciones


def fake_deps(tmp_path, scores_por_ronda):
    rondas = iter(scores_por_ronda)
    llamadas = {"buscar": 0}

    def buscar(consulta):
        llamadas["buscar"] += 1
        return [Lead(texto=f"lead {i}", post_url=f"https://x/{i}") for i in range(3)]

    def evaluar(perfil, leads):
        scores = next(rondas)
        return Evaluaciones(items=[Evaluacion(post_url=l.post_url, score=s, razon="test")
                                   for l, s in zip(leads, scores)])

    deps = Deps(
        interpretar=lambda s: Criterios(consulta="evaluación de impacto", perfil="M&E"),
        evaluar=evaluar,
        reformular=lambda c, p: c + " ampliada",
        buscar=buscar,
        output_dir=str(tmp_path),
    )
    return deps, llamadas
```

Tests mínimos (los 5 deben pasar):

| # | Test | Qué verifica |
|---|------|--------------|
| 1 | `test_se_pausa_en_revision_humana` | Con scores `[8, 7, 2]`, `invoke` se detiene y el resultado trae `__interrupt__` con 2 leads en la shortlist. |
| 2 | `test_aprobar_escribe_archivo` | Tras `invoke(Command(resume="aprobar"), config)`, existe el JSON en `tmp_path` con 2 leads. |
| 3 | `test_rechazar_no_escribe` | Con `resume="rechazar"`, `archivo` es `None` y la carpeta está vacía. |
| 4 | `test_reformula_si_hay_pocos_buenos` | Con scores `[[2,3,1], [8,7,6]]`, `buscar` se llama 2 veces y la consulta final termina en "ampliada". |
| 5 | `test_tope_de_reformulaciones` | Con 3 rondas malas, `buscar` se llama 3 veces (1 + 2 reintentos) y luego pasa a revisión igual. |

Patrón de invocación en los tests:

```python
config = {"configurable": {"thread_id": "t1"}}
graph = build_graph(deps)
r = graph.invoke({"solicitud": "oportunidades para María, evaluación de impacto"}, config)
assert "__interrupt__" in r
r = graph.invoke(Command(resume="aprobar"), config)
```

Correr `pytest` local y confirmar que **CI sigue en verde** con los tests nuevos.

### Paso 7 — CLI (`agent/run.py`, 30 min)

```bash
python -m agent.run "oportunidades para una consultora en evaluación de impacto"
# muestra la shortlist y pregunta: ¿aprobar/rechazar?
```

Usa `deps_reales()`. **Requiere `OPENAI_API_KEY` y la base con datos ingeridos.** Costo estimado: centavos con `gpt-4o-mini`.

### Paso 8 — Conectar el RAG real (1 h)

`buscar` ya llama al retriever real (paso 3). Prueba manual con 2–3 consultas reales; requiere la base levantada (`docker compose up db`) y datos ingeridos. Anotar en el README qué tal funcionó, incluso si los resultados son pobres (53 leads es poco).

### Paso 9 — README y diagrama (45 min)

Sección nueva "Agente LangGraph (fase 1)":
- Diagrama del grafo. Opcional: generarlo con `graph.get_graph().draw_mermaid()` y pegar el Mermaid.
- Cómo correrlo: CLI y tests.
- **Limitaciones honestas:** checkpointer en memoria (se pierde al reiniciar), 53 leads, sin API ni Docker para el agente todavía, sin evaluación formal de calidad.
- Próximos pasos: PostgresSaver, endpoints FastAPI, webhook de n8n.

### Paso 10 — Usar OpenCode en parte del trabajo (paralelo, ~1 h)

Hacer al menos los pasos 7 o 9 con **OpenCode** en lugar de Claude Code. Anotar 3 diferencias concretas que notes (flujo, modelos, permisos, velocidad).

## 5. Cronograma sugerido

| Bloque | Pasos | Entregable |
|--------|-------|-----------|
| Sábado mañana (3 h) | 1–5 | Grafo compilando |
| Sábado tarde (2 h) | 6 | 5 tests en verde, commit y push, CI verde |
| Domingo mañana (2.5 h) | 7–8 (+10) | Corrida real con el RAG |
| Domingo tarde (1 h) | 9 | README, push final |

**Regla:** si el sábado a la noche no hay tests en verde, el domingo se dedica solo a terminarlos. Un agente con fakes y tests vale más que uno real a medias.

## 6. Commits sugeridos

1. `chore: agregar langgraph y langchain-openai`
2. `feat(agent): estado, nodos y grafo con ciclo de reformulación`
3. `test(agent): 5 tests con LLM y RAG simulados`
4. `feat(agent): interrupt para revisión humana y publicación en archivo`
5. `feat(agent): conectar buscador al motor RAG existente + CLI`
6. `docs: sección del agente LangGraph con diagrama y limitaciones`

## 7. Siguientes fases

- Continuar con la fase 3 del plan mayor (PostgresSaver) y la fase 4 (webhook de n8n).

## Recursos

- [LangGraph — documentación oficial](https://langchain-ai.github.io/langgraph/)
- [Human-in-the-loop con `interrupt`](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/)
- [Introduction to LangGraph (LangChain Academy)](https://academy.langchain.com/courses/intro-to-langgraph): módulos 1 y 3, solo si te trabas.
