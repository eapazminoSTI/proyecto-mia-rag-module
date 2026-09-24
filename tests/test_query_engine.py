from rag import query_engine


def test_build_index_se_construye_una_sola_vez(monkeypatch):
    calls = []

    def _fake_from_params(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(query_engine.PGVectorStore, "from_params", _fake_from_params)
    monkeypatch.setattr(query_engine.VectorStoreIndex, "from_vector_store",
                        lambda vector_store, embed_model: ("index", vector_store))
    query_engine._build_index.cache_clear()
    try:
        first = query_engine._build_index()
        second = query_engine._build_index()
    finally:
        query_engine._build_index.cache_clear()

    assert first is second
    assert len(calls) == 1
