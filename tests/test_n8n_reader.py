import json
from pathlib import Path

import pytest

from rag.n8n_reader import _latest_matches_by_pair

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def flat_schema_row() -> dict:
    """Fila real de `resultados_match` capturada de la instancia N8N del proyecto
    original: `todos_los_resultados` es un string JSON con 224 entradas en el
    schema plano (oportunidad_id/consultor_id/score_match/tipo_oportunidad)."""
    sample = _load_fixture("resultados_match_todos_los_resultados_raw_sample.json")
    return {
        "fecha_ejecucion": "2026-05-13T00:00:00Z",
        "todos_los_resultados": sample["todos_los_resultados_raw"],
        "top_10_matches": None,
    }


@pytest.fixture
def flat_schema_entries() -> list[dict]:
    sample = _load_fixture("resultados_match_todos_los_resultados_raw_sample.json")
    return json.loads(sample["todos_los_resultados_raw"])


def test_first_captured_entry_matches_standalone_debug_sample(flat_schema_entries):
    # resultados_match_entry_sample.json es la primera entrada de
    # resultados_match_todos_los_resultados_raw_sample.json, guardada aparte durante
    # el debugging original del parser dual. Si esto falla, las dos fixtures se
    # desincronizaron.
    assert flat_schema_entries[0] == _load_fixture("resultados_match_entry_sample.json")


def test_flat_schema_normalizes_real_captured_run(flat_schema_row):
    latest = _latest_matches_by_pair([flat_schema_row])

    entry = latest[("10", "33")]
    assert entry == {
        "score": 0.85,
        "tipo": "consultoria",
        "decision": "aplicar",
        "motivo": (
            "Consultor con sólida experiencia en metodologías ágiles y "
            "transformación digital, altamente relevante para consultoría."
        ),
        "fecha_ejecucion": "2026-05-13T00:00:00Z",
    }


def test_flat_schema_produces_one_entry_per_unique_pair(flat_schema_row, flat_schema_entries):
    latest = _latest_matches_by_pair([flat_schema_row])

    expected_pairs = {
        (str(e["consultor_id"]), str(e["oportunidad_id"])) for e in flat_schema_entries
    }
    assert set(latest.keys()) == expected_pairs


def test_nested_schema_top_10_matches_is_normalized():
    # No se capturó una muestra real de `top_10_matches` durante el debugging
    # (solo se guardó el raw de `todos_los_resultados`); este caso reproduce el
    # schema anidado documentado en README.md §4 (ids.consultor/ids.oportunidad,
    # score/tipo sin sufijo) para cubrir la otra rama del parser.
    row = {
        "fecha_ejecucion": "2026-04-20T00:00:00Z",
        "todos_los_resultados": None,
        "top_10_matches": json.dumps([
            {
                "ids": {"consultor": "7", "oportunidad": "42"},
                "score": 0.91,
                "tipo": "colaboracion",
                "decision": "aplicar",
                "motivo": "Alta afinidad temática.",
            }
        ]),
    }

    latest = _latest_matches_by_pair([row])

    assert latest[("7", "42")] == {
        "score": 0.91,
        "tipo": "colaboracion",
        "decision": "aplicar",
        "motivo": "Alta afinidad temática.",
        "fecha_ejecucion": "2026-04-20T00:00:00Z",
    }


def test_later_run_overwrites_earlier_run_for_same_pair():
    older_run = {
        "fecha_ejecucion": "2026-04-01T00:00:00Z",
        "todos_los_resultados": json.dumps([
            {"oportunidad_id": "1", "consultor_id": "2", "score_match": 0.5, "tipo_oportunidad": "empleo"}
        ]),
    }
    newer_run = {
        "fecha_ejecucion": "2026-05-01T00:00:00Z",
        "todos_los_resultados": json.dumps([
            {"oportunidad_id": "1", "consultor_id": "2", "score_match": 0.9, "tipo_oportunidad": "empleo"}
        ]),
    }

    # El orden de entrada es intencionalmente el inverso al cronológico: la función
    # debe ordenar por fecha_ejecucion internamente, no confiar en el orden de la lista.
    latest = _latest_matches_by_pair([newer_run, older_run])

    assert latest[("2", "1")]["score"] == 0.9
    assert latest[("2", "1")]["fecha_ejecucion"] == "2026-05-01T00:00:00Z"


def test_malformed_json_row_is_skipped_without_raising():
    rows = [
        {"fecha_ejecucion": "2026-04-01T00:00:00Z", "todos_los_resultados": "{not valid json"},
        {
            "fecha_ejecucion": "2026-04-02T00:00:00Z",
            "todos_los_resultados": json.dumps([
                {"oportunidad_id": "9", "consultor_id": "9", "score_match": 0.7, "tipo_oportunidad": "empleo"}
            ]),
        },
    ]

    latest = _latest_matches_by_pair(rows)

    assert ("9", "9") in latest
    assert len(latest) == 1


def test_entry_missing_ids_is_skipped():
    row = {
        "fecha_ejecucion": "2026-04-01T00:00:00Z",
        "todos_los_resultados": json.dumps([
            {"score_match": 0.8, "tipo_oportunidad": "empleo"},  # sin consultor_id/oportunidad_id
        ]),
    }

    assert _latest_matches_by_pair([row]) == {}


def test_no_rows_returns_empty_dict():
    assert _latest_matches_by_pair([]) == {}
