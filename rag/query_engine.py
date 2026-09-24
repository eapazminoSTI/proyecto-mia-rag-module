import functools
import sys

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.vector_stores.postgres import PGVectorStore

from rag import config

QUERY_PROMPT = """Eres un asistente que ayuda a encontrar oportunidades laborales/consultoría de LinkedIn \
que coinciden con el perfil de un consultor de Latinnova.

Perfil consultado:
{perfil}

A continuación tienes leads recuperados por similitud semántica, cada uno con su score de relevancia \
y, cuando existe, el historial de evaluaciones previas del pipeline de scoring (WF4).

{leads_context}

Responde en español: ¿cuáles de estos leads matchean mejor con el perfil y por qué? Para cada lead que \
recomiendes, cita explícitamente su número [Lead N] y explica el motivo basándote en el contenido del \
lead y, si existe, el historial de scoring. Si ningún lead es un buen match, dilo directamente."""


# Se construye una sola vez por proceso (API/Streamlit) en vez de en cada consulta. El índice
# solo apunta a la tabla de pgvector, así que sigue viendo los leads que agregue `rag.ingest`.
@functools.lru_cache(maxsize=1)
def _build_index() -> VectorStoreIndex:
    db = config.parsed_database_url()
    vector_store = PGVectorStore.from_params(
        database=db["database"],
        host=db["host"],
        password=db["password"],
        port=db["port"],
        user=db["user"],
        table_name=config.VECTOR_TABLE_NAME,
        embed_dim=config.EMBED_DIM,
    )
    embed_model = OpenAIEmbedding(model=config.EMBED_MODEL, api_key=config.OPENAI_API_KEY)
    return VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)


def _format_lead(i: int, node: NodeWithScore) -> str:
    md = node.metadata
    header = (
        f"[Lead {i}] score_similitud={node.score:.3f} | cargo={md.get('cargo')} | "
        f"{md.get('ciudad', '')} {md.get('pais', '')}".strip()
    )
    lines = [header, node.text.strip()]

    matches = md.get("existing_matches") or []
    if matches:
        lines.append("Historial de scoring previo (WF4):")
        for m in matches:
            lines.append(
                f"  - {m.get('nombre_consultor')}: score={m.get('score')}, "
                f"decisión={m.get('decision')} — {m.get('motivo')}"
            )
    return "\n".join(lines)


def _citation(node: NodeWithScore) -> dict:
    md = node.metadata
    return {
        "oportunidad_id": md.get("oportunidad_id"),
        "cargo": md.get("cargo"),
        "post_url": md.get("post_url"),
        "author_name": md.get("author_name"),
        "similarity_score": round(node.score, 4) if node.score is not None else None,
    }


def query(perfil: str, top_k: int = 5) -> dict:
    retriever = _build_index().as_retriever(similarity_top_k=top_k)
    nodes = retriever.retrieve(perfil)

    if not nodes:
        return {"answer": "No se encontraron leads indexados todavía.", "citations": []}

    leads_context = "\n\n".join(_format_lead(i + 1, n) for i, n in enumerate(nodes))
    llm = OpenAI(model=config.LLM_MODEL, api_key=config.OPENAI_API_KEY, temperature=0)
    response = llm.complete(QUERY_PROMPT.format(perfil=perfil, leads_context=leads_context))

    return {"answer": str(response), "citations": [_citation(n) for n in nodes]}


if __name__ == "__main__":
    perfil_arg = " ".join(sys.argv[1:]) or "Consultor especializado en transformación digital y metodologías ágiles"
    result = query(perfil_arg)
    print(result["answer"])
    print("\nCitas:")
    for c in result["citations"]:
        print(" -", c)
