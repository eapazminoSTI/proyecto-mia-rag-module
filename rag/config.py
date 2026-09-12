import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

N8N_URL = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
N8N_API_KEY = os.environ["N8N_API_KEY"]

DATABASE_URL = os.environ["DATABASE_URL"]  # postgresql://user:pass@host:port/dbname

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "text-embedding-3-small")
EMBED_DIM = int(os.environ.get("RAG_EMBED_DIM", "1536"))
LLM_MODEL = os.environ.get("RAG_LLM_MODEL", "gpt-4o-mini")

VECTOR_TABLE_NAME = os.environ.get("RAG_VECTOR_TABLE", "rag_leads")
DOCSTORE_TABLE_NAME = os.environ.get("RAG_DOCSTORE_TABLE", "rag_leads_docstore")


def parsed_database_url():
    p = urlparse(DATABASE_URL)
    return {
        "host": p.hostname,
        "port": p.port or 5432,
        "database": p.path.lstrip("/"),
        "user": p.username,
        "password": p.password,
    }
