import json
import os

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from agent.deps import Deps
from agent.state import AgentState

UMBRAL, MIN_BUENOS, MAX_INTENTOS = 6, 2, 2


def armar_shortlist(state: AgentState) -> list[dict]:
    """Une cada evaluación con su lead (por índice) y deja solo las que llegan al umbral.

    Descarta índices fuera de rango y evaluaciones repetidas del mismo lead: el LLM puede
    equivocarse en ambas cosas.
    """
    leads = state.get("leads", [])
    shortlist, vistos = [], set()
    for ev in state.get("evaluaciones", []):
        if ev.score < UMBRAL or not 1 <= ev.indice <= len(leads) or ev.indice in vistos:
            continue
        vistos.add(ev.indice)
        lead = leads[ev.indice - 1]
        shortlist.append({**lead.model_dump(), "score": ev.score, "razon": ev.razon})
    return sorted(shortlist, key=lambda item: item["score"], reverse=True)


def make_nodes(deps: Deps) -> dict:
    def interpretar_solicitud(state: AgentState):
        return {"criterios": deps.interpretar(state["solicitud"]), "intentos": 0}

    def buscar_oportunidades(state: AgentState):
        return {"leads": deps.buscar(state["criterios"].consulta)}

    def evaluar_encaje(state: AgentState):
        evaluaciones = deps.evaluar(state["criterios"].perfil, state["leads"])
        return {"evaluaciones": evaluaciones.items}

    def reformular_consulta(state: AgentState):
        criterios = state["criterios"]
        nueva = deps.reformular(criterios.consulta, criterios.perfil)
        return {
            "criterios": criterios.model_copy(update={"consulta": nueva}),
            "intentos": state.get("intentos", 0) + 1,
        }

    def revision_humana(state: AgentState):
        # interrupt() pausa el grafo y guarda el estado en el checkpointer; al retomar con
        # Command(resume=...) este nodo se vuelve a ejecutar e interrupt() devuelve ese valor.
        decision = interrupt({
            "consulta": state["criterios"].consulta,
            "shortlist": armar_shortlist(state),
            "pregunta": "¿aprobar o rechazar?",
        })
        return {"decision": decision}

    def publicar(state: AgentState, config: RunnableConfig):
        if state.get("decision") != "aprobar":
            return {"archivo": None}
        os.makedirs(deps.output_dir, exist_ok=True)
        ruta = os.path.join(deps.output_dir, f"{config['configurable']['thread_id']}.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "solicitud": state["solicitud"],
                    "consulta": state["criterios"].consulta,
                    "shortlist": armar_shortlist(state),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        return {"archivo": ruta}

    return {
        "interpretar_solicitud": interpretar_solicitud,
        "buscar_oportunidades": buscar_oportunidades,
        "evaluar_encaje": evaluar_encaje,
        "reformular_consulta": reformular_consulta,
        "revision_humana": revision_humana,
        "publicar": publicar,
    }


def ruta_tras_evaluar(state: AgentState) -> str:
    if len(armar_shortlist(state)) < MIN_BUENOS and state.get("intentos", 0) < MAX_INTENTOS:
        return "reformular_consulta"
    return "revision_humana"
