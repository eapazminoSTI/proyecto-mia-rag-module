import pytest
from fastapi.testclient import TestClient

from rag import api, query_engine

client = TestClient(api.app)

FAKE_RESULT = {
    "answer": "El [Lead 1] matchea por experiencia en transformación digital.",
    "citations": [{
        "oportunidad_id": "42",
        "cargo": "Consultor de transformación digital",
        "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:1",
        "author_name": "Autor",
        "similarity_score": 0.5123,
    }],
}


@pytest.fixture
def fake_query(monkeypatch):
    calls = []

    def _fake(perfil, top_k=5):
        calls.append((perfil, top_k))
        return FAKE_RESULT

    monkeypatch.setattr(query_engine, "query", _fake)
    return calls


def test_health_con_db_disponible(monkeypatch):
    monkeypatch.setattr(api, "_ping_db", lambda: None)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


def test_health_con_db_caida_devuelve_503(monkeypatch):
    def _boom():
        raise ConnectionError("connection refused")

    monkeypatch.setattr(api, "_ping_db", _boom)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert "connection refused" in resp.json()["detail"]


def test_query_devuelve_respuesta_y_citas(fake_query):
    resp = client.post("/query", json={"perfil": "  Consultor senior ágil  ", "top_k": 3})
    assert resp.status_code == 200
    assert resp.json() == FAKE_RESULT
    assert fake_query == [("Consultor senior ágil", 3)]


def test_query_top_k_por_defecto(fake_query):
    client.post("/query", json={"perfil": "Consultor"})
    assert fake_query == [("Consultor", 5)]


@pytest.mark.parametrize("body", [
    {},
    {"perfil": ""},
    {"perfil": "   "},
    {"perfil": "x", "top_k": 0},
    {"perfil": "x", "top_k": 11},
])
def test_query_valida_entrada(fake_query, body):
    assert client.post("/query", json=body).status_code == 422
    assert fake_query == []


def test_query_error_del_motor_devuelve_503(monkeypatch):
    def _boom(perfil, top_k=5):
        raise RuntimeError("Postgres no disponible")

    monkeypatch.setattr(query_engine, "query", _boom)
    resp = client.post("/query", json={"perfil": "Consultor"})
    assert resp.status_code == 503
    assert "Postgres no disponible" in resp.json()["detail"]
