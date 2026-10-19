"""CLI del agente: python -m agent.run "oportunidades para una consultora en evaluación de impacto"

Corre el grafo hasta la revisión humana, muestra la shortlist y pide aprobar o rechazar.
El checkpointer es en memoria, así que la pausa y la decisión ocurren en el mismo proceso.
"""
import argparse
import sys
import uuid

from langgraph.types import Command

from agent.graph import build_graph

RESPUESTAS = {"a": "aprobar", "aprobar": "aprobar", "r": "rechazar", "rechazar": "rechazar"}


def mostrar_shortlist(pausa: dict) -> None:
    print(f"\nConsulta usada: {pausa['consulta']}")
    shortlist = pausa["shortlist"]
    if not shortlist:
        print("No hay oportunidades con encaje suficiente.")
        return
    print(f"Shortlist ({len(shortlist)}):")
    for i, item in enumerate(shortlist, start=1):
        print(f"\n  {i}. score {item['score']}/10 · {item.get('author_name') or 'autor desconocido'}")
        print(f"     {item.get('post_url') or 'sin URL'}")
        print(f"     {item['razon']}")


def pedir_decision(input_fn=input) -> str:
    while True:
        respuesta = input_fn("\n¿Aprobar o rechazar? [a/r]: ").strip().lower()
        if respuesta in RESPUESTAS:
            return RESPUESTAS[respuesta]
        print("Responde 'a' (aprobar) o 'r' (rechazar).")


def main(argv=None, deps=None, input_fn=input) -> dict:
    parser = argparse.ArgumentParser(prog="python -m agent.run", description="Agente LangGraph sobre el motor RAG")
    parser.add_argument("solicitud", nargs="+", help="Qué oportunidades buscar y para qué perfil")
    parser.add_argument("--thread-id", default=None, help="Identificador de la corrida (por defecto, uno aleatorio)")
    args = parser.parse_args(argv)

    if deps is None:
        from agent.deps import deps_reales
        deps = deps_reales()

    graph = build_graph(deps)
    config = {"configurable": {"thread_id": args.thread_id or uuid.uuid4().hex[:8]}}

    print("Buscando y evaluando oportunidades...")
    resultado = graph.invoke({"solicitud": " ".join(args.solicitud)}, config)
    while "__interrupt__" in resultado:
        mostrar_shortlist(resultado["__interrupt__"][0].value)
        resultado = graph.invoke(Command(resume=pedir_decision(input_fn)), config)

    if resultado.get("archivo"):
        print(f"\nShortlist guardada en {resultado['archivo']}")
    else:
        print("\nRechazado: no se guardó nada.")
    return resultado


if __name__ == "__main__":
    # La consola de Windows no usa UTF-8 por defecto y rompería tildes y "ñ".
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
