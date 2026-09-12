import os

# rag.config lee estas variables al importarse (os.environ[...] sin default).
# Los tests solo ejercitan _latest_matches_by_pair, que no habla con N8N/Postgres/
# OpenAI, así que valores dummy son suficientes para poder importar rag.n8n_reader.
os.environ.setdefault("N8N_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
