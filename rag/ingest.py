from llama_index.core.ingestion import DocstoreStrategy, IngestionPipeline
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.storage.docstore.postgres import PostgresDocumentStore
from llama_index.vector_stores.postgres import PGVectorStore

from rag import config
from rag.n8n_reader import fetch_documents


def build_pipeline() -> IngestionPipeline:
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
    docstore = PostgresDocumentStore.from_params(
        database=db["database"],
        host=db["host"],
        password=db["password"],
        port=db["port"],
        user=db["user"],
        table_name=config.DOCSTORE_TABLE_NAME,
    )
    embed_model = OpenAIEmbedding(model=config.EMBED_MODEL, api_key=config.OPENAI_API_KEY)

    return IngestionPipeline(
        transformations=[embed_model],
        docstore=docstore,
        vector_store=vector_store,
        docstore_strategy=DocstoreStrategy.UPSERTS,
    )


def main():
    documents = fetch_documents()
    nodes = build_pipeline().run(documents=documents, show_progress=True)

    print(f"Leads leídos de N8N (linkedin_jobs): {len(documents)}")
    print(f"Nuevos/actualizados embebidos: {len(nodes)}")
    print(f"Sin cambios, omitidos: {len(documents) - len(nodes)}")


if __name__ == "__main__":
    main()
