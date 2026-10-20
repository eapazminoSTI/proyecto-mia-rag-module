from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from agent.deps import Deps
from agent.nodes import make_nodes, ruta_tras_evaluar
from agent.state import AgentState, Criterios, Evaluacion, Lead

# El checkpointer serializa el estado con msgpack y solo debería reconstruir clases
# registradas; sin esta lista, LangGraph avisa (y en versiones futuras bloquea) al
# leer Criterios/Lead/Evaluacion de un checkpoint.
SERDE = JsonPlusSerializer(
    allowed_msgpack_modules=[(cls.__module__, cls.__name__) for cls in (Criterios, Lead, Evaluacion)]
)


def build_graph(deps: Deps, checkpointer=None):
    g = StateGraph(AgentState)
    for nombre, nodo in make_nodes(deps).items():
        g.add_node(nombre, nodo)

    g.add_edge(START, "interpretar_solicitud")
    g.add_edge("interpretar_solicitud", "buscar_oportunidades")
    g.add_edge("buscar_oportunidades", "evaluar_encaje")
    # Ciclo con límite: si hay pocos leads buenos, reformula y vuelve a buscar.
    g.add_conditional_edges("evaluar_encaje", ruta_tras_evaluar,
                            ["reformular_consulta", "revision_humana", END])
    g.add_edge("reformular_consulta", "buscar_oportunidades")
    g.add_edge("revision_humana", "publicar")
    g.add_edge("publicar", END)
    # interrupt() necesita un checkpointer para guardar el estado mientras espera la decisión.
    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=SERDE))
