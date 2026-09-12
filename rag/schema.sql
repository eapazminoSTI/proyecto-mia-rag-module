-- =============================================================
-- Bootstrap Postgres para el módulo RAG (pgvector)
-- Ejecutar una vez, con un rol que tenga privilegio para crear extensiones.
--
-- Las tablas de datos (vector store + docstore de LlamaIndex) NO se crean
-- aquí: rag/ingest.py las crea automáticamente en su primer run vía
-- PGVectorStore y PostgresDocumentStore (IngestionPipeline con
-- DocstoreStrategy.UPSERTS, que ya maneja el hash de contenido para
-- evitar reembeber documentos sin cambios).
-- =============================================================

CREATE EXTENSION IF NOT EXISTS vector;
