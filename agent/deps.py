from dataclasses import dataclass
from typing import Protocol

from agent.state import Criterios, Evaluaciones, Lead

TOP_K = 5
# Recorte del texto de cada lead en el prompt del evaluador, para acotar tokens.
MAX_CHARS_LEAD = 1500


class Interprete(Protocol):
    def __call__(self, solicitud: str) -> Criterios: ...


class Evaluador(Protocol):
    def __call__(self, perfil: str, leads: list[Lead]) -> Evaluaciones: ...


class Reformulador(Protocol):
    def __call__(self, consulta: str, perfil: str) -> str: ...


class Buscador(Protocol):
    def __call__(self, consulta: str) -> list[Lead]: ...


# Los nodos solo conocen este objeto: en los tests se arma con fakes deterministas y
# nunca se importa OpenAI ni LlamaIndex.
@dataclass
class Deps:
    interpretar: Interprete
    evaluar: Evaluador
    reformular: Reformulador
    buscar: Buscador
    output_dir: str = "output/shortlists"


def listar_leads(leads: list[Lead]) -> str:
    return "\n\n".join(
        f"[{i}] autor={lead.author_name or '-'} | url={lead.post_url or '-'}\n{lead.texto[:MAX_CHARS_LEAD]}"
        for i, lead in enumerate(leads, start=1)
    )


def deps_reales() -> Deps:
    # Imports diferidos: rag.config exige variables de entorno al importarse.
    from langchain_openai import ChatOpenAI

    from rag import config
    from rag.query_engine import _build_index, _citation

    llm = ChatOpenAI(model=config.LLM_MODEL, api_key=config.OPENAI_API_KEY, temperature=0)
    llm_criterios = llm.with_structured_output(Criterios)
    llm_evaluaciones = llm.with_structured_output(Evaluaciones)

    def interpretar(solicitud: str) -> Criterios:
        return llm_criterios.invoke(
            "Eres un asistente que busca oportunidades laborales/consultoría de LinkedIn para "
            "consultores de Latinnova. De la siguiente solicitud, extrae un resumen del perfil del "
            "consultor, sus temas de interés y una consulta de búsqueda semántica concisa.\n\n"
            f"Solicitud: {solicitud}"
        )

    def evaluar(perfil: str, leads: list[Lead]) -> Evaluaciones:
        if not leads:
            return Evaluaciones(items=[])
        return llm_evaluaciones.invoke(
            f"Perfil del consultor:\n{perfil}\n\n"
            "Puntúa de 0 a 10 el encaje de CADA una de estas oportunidades con el perfil y explica "
            "por qué en una o dos frases. Identifica cada una por su número entre corchetes.\n\n"
            f"{listar_leads(leads)}"
        )

    def reformular(consulta: str, perfil: str) -> str:
        respuesta = llm.invoke(
            f"La búsqueda '{consulta}' dio pocos resultados buenos para el perfil '{perfil}'. "
            "Propón UNA consulta alternativa más amplia. Responde solo con la consulta."
        )
        return respuesta.content.strip()

    def buscar(consulta: str) -> list[Lead]:
        nodes = _build_index().as_retriever(similarity_top_k=TOP_K).retrieve(consulta)
        leads = []
        for node in nodes:
            cita = _citation(node)
            leads.append(Lead(
                texto=node.get_content(),
                oportunidad_id=cita["oportunidad_id"],
                post_url=cita["post_url"],
                author_name=cita["author_name"],
            ))
        return leads

    return Deps(interpretar=interpretar, evaluar=evaluar, reformular=reformular, buscar=buscar)
