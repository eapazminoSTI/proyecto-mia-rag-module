"""
API REST (FastAPI) sobre rag.query_engine — misma consulta que app.py y el CLI,
expuesta por HTTP para que otros servicios (p. ej. un workflow N8N vía HTTP Request)
puedan consultar el índice sin importar Python.

    uvicorn rag.api:app --host 0.0.0.0 --port 8000
"""
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from rag import config, query_engine

app = FastAPI(
    title="Latinnova RAG API",
    description="Retrieval semántico sobre leads indexados con citación de fuente.",
    version="0.1.0",
)


class QueryRequest(BaseModel):
    perfil: str = Field(..., min_length=1, description="Descripción del perfil o la búsqueda")
    top_k: int = Field(5, ge=1, le=10, description="Cantidad de leads a recuperar")


class Citation(BaseModel):
    oportunidad_id: str | None = None
    cargo: str | None = None
    post_url: str | None = None
    author_name: str | None = None
    similarity_score: float | None = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]


def _ping_db() -> None:
    db = config.parsed_database_url()
    conn = psycopg2.connect(
        host=db["host"], port=db["port"], dbname=db["database"],
        user=db["user"], password=db["password"], connect_timeout=3,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    finally:
        conn.close()


@app.get("/health")
def health() -> dict:
    # SELECT 1 contra Postgres, sin llamar a OpenAI (usado por el healthcheck de Docker).
    try:
        _ping_db()
    except Exception as ex:
        raise HTTPException(status_code=503, detail=f"Postgres no disponible: {ex}") from ex
    return {"status": "ok", "database": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> dict:
    # `def` (no `async def`): query_engine.query es bloqueante y FastAPI lo corre en su threadpool.
    perfil = req.perfil.strip()
    if not perfil:
        raise HTTPException(status_code=422, detail="perfil no puede estar vacío")
    try:
        return query_engine.query(perfil, top_k=req.top_k)
    except Exception as ex:
        raise HTTPException(status_code=503, detail=f"Error ejecutando la consulta RAG: {ex}") from ex
