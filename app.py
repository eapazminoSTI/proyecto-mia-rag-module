"""
App Streamlit independiente para el módulo RAG (retrieval semántico sobre
leads del pipeline Latinnova MIA). No depende del dashboard del repo original
ni de ninguna carpeta fuera de este repo — vive junto a rag/ y solo importa
rag.query_engine directamente (mismo repo, sin instalar nada vía pip).
"""
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # antes de leer os.environ — rag.config también lo hace, pero recién al importarse

st.set_page_config(page_title="Consulta RAG — Latinnova", layout="wide", page_icon="🔎")

st.title("🔎 Consulta RAG sobre Leads")
st.caption(
    "Retrieval semántico (no el matching determinístico de WF4 del pipeline original): "
    "responde \"¿qué leads matchean con este perfil y por qué?\" con citación de fuente."
)

missing = [
    name for name in ("N8N_API_KEY", "DATABASE_URL", "OPENAI_API_KEY")
    if not os.environ.get(name)
]

if missing:
    st.info(
        "💡 **Módulo RAG no configurado.** Faltan estas variables de entorno: "
        f"`{'`, `'.join(missing)}`.\n\n"
        "Créalas en `.env` (ver README.md sección 6) o expórtalas antes de correr "
        "`streamlit run app.py`. Sin un Postgres+pgvector ya indexado y una API key "
        "de OpenAI válidas no hay resultados de similitud que mostrar — esta app no "
        "tiene modo demo."
    )
    st.stop()

try:
    from rag.query_engine import query as rag_query
except Exception as ex:
    st.error(f"❌ No se pudo importar rag.query_engine: {ex}")
    st.stop()

with st.form("form_rag_query"):
    perfil = st.text_area(
        "Describe el perfil o la búsqueda",
        placeholder="Ej: Consultor senior con experiencia en transformación digital y metodologías ágiles",
        height=100,
    )
    top_k = st.slider("Cantidad de leads a recuperar", min_value=1, max_value=10, value=5)
    submitted = st.form_submit_button("🔎 Buscar")

if submitted:
    if not perfil.strip():
        st.warning("Escribe una descripción de perfil antes de buscar.")
    else:
        with st.spinner("Buscando leads por similitud semántica y generando respuesta..."):
            try:
                result = rag_query(perfil, top_k=top_k)
            except Exception as ex:
                st.error(f"❌ Error ejecutando la consulta RAG: {ex}")
                result = None

        if result is not None:
            st.subheader("🧠 Respuesta")
            st.markdown(result["answer"])

            st.subheader("📎 Citas")
            citations = result["citations"]
            if not citations:
                st.info("Sin citas — no se encontraron leads indexados todavía.")
            for i, c in enumerate(citations, start=1):
                post_url = c.get("post_url")
                cargo = c.get("cargo") or "(sin cargo registrado)"
                author = c.get("author_name") or "Autor desconocido"
                score = c.get("similarity_score")
                link = f" — [ver post original]({post_url})" if post_url else " — post_url no disponible"
                st.markdown(f"**[Lead {i}]** {cargo} · {author} · similitud={score}{link}")

st.divider()
st.caption(
    "Capa de solo lectura sobre las N8N Data Tables del pipeline original — "
    "no modifica linkedin_jobs, Consultores ni resultados_match."
)
