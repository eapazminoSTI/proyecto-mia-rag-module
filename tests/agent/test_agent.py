import json

from langgraph.types import Command

from agent.deps import Deps
from agent.graph import build_graph
from agent.nodes import armar_shortlist
from agent.run import main
from agent.state import Criterios, Evaluacion, Evaluaciones, Lead

SOLICITUD = {"solicitud": "oportunidades para María, evaluación de impacto"}


def fake_deps(tmp_path, scores_por_ronda):
    """Deps deterministas: 3 leads por búsqueda y una lista de scores por cada evaluación."""
    rondas = iter(scores_por_ronda)
    consultas = []

    def buscar(consulta):
        consultas.append(consulta)
        return [Lead(texto=f"lead {i}", oportunidad_id=str(i), post_url=f"https://x/{i}") for i in range(3)]

    def evaluar(perfil, leads):
        scores = next(rondas)
        return Evaluaciones(items=[
            Evaluacion(indice=i, score=s, razon="test") for i, s in enumerate(scores, start=1)
        ])

    deps = Deps(
        interpretar=lambda s: Criterios(consulta="evaluación de impacto", perfil="M&E"),
        evaluar=evaluar,
        reformular=lambda c, p: c + " ampliada",
        buscar=buscar,
        output_dir=str(tmp_path),
    )
    return deps, consultas


def config(thread_id="t1"):
    return {"configurable": {"thread_id": thread_id}}


def test_se_pausa_en_revision_humana(tmp_path):
    deps, _ = fake_deps(tmp_path, [[8, 7, 2]])
    r = build_graph(deps).invoke(SOLICITUD, config())

    assert "__interrupt__" in r
    shortlist = r["__interrupt__"][0].value["shortlist"]
    assert [item["oportunidad_id"] for item in shortlist] == ["0", "1"]


def test_aprobar_escribe_archivo(tmp_path):
    deps, _ = fake_deps(tmp_path, [[8, 7, 2]])
    graph = build_graph(deps)
    graph.invoke(SOLICITUD, config())
    r = graph.invoke(Command(resume="aprobar"), config())

    assert r["archivo"] == str(tmp_path / "t1.json")
    contenido = json.loads((tmp_path / "t1.json").read_text(encoding="utf-8"))
    assert contenido["solicitud"] == SOLICITUD["solicitud"]
    assert [item["score"] for item in contenido["shortlist"]] == [8, 7]


def test_rechazar_no_escribe(tmp_path):
    deps, _ = fake_deps(tmp_path, [[8, 7, 2]])
    graph = build_graph(deps)
    graph.invoke(SOLICITUD, config())
    r = graph.invoke(Command(resume="rechazar"), config())

    assert r["archivo"] is None
    assert list(tmp_path.iterdir()) == []


def test_reformula_si_hay_pocos_buenos(tmp_path):
    deps, consultas = fake_deps(tmp_path, [[2, 3, 1], [8, 7, 6]])
    r = build_graph(deps).invoke(SOLICITUD, config())

    assert consultas == ["evaluación de impacto", "evaluación de impacto ampliada"]
    assert r["criterios"].consulta.endswith("ampliada")
    assert len(r["__interrupt__"][0].value["shortlist"]) == 3


def test_tope_de_reformulaciones(tmp_path):
    deps, consultas = fake_deps(tmp_path, [[2, 3, 1]] * 3)
    r = build_graph(deps).invoke(SOLICITUD, config())

    # 1 búsqueda inicial + MAX_INTENTOS reformulaciones; después pasa a revisión aunque no haya buenos.
    assert len(consultas) == 3
    assert r["intentos"] == 2
    assert r["__interrupt__"][0].value["shortlist"] == []


def test_shortlist_descarta_indices_invalidos_y_duplicados():
    leads = [Lead(texto=f"lead {i}", oportunidad_id=str(i)) for i in range(2)]
    evaluaciones = [
        Evaluacion(indice=1, score=7, razon="ok"),
        Evaluacion(indice=1, score=9, razon="duplicado"),
        Evaluacion(indice=5, score=10, razon="fuera de rango"),
        Evaluacion(indice=2, score=9, razon="ok"),
    ]
    shortlist = armar_shortlist({"leads": leads, "evaluaciones": evaluaciones})

    assert [(item["oportunidad_id"], item["razon"]) for item in shortlist] == [("1", "ok"), ("0", "ok")]


def test_cli_insiste_hasta_respuesta_valida_y_aprueba(tmp_path, capsys):
    deps, _ = fake_deps(tmp_path, [[8, 7, 2]])
    respuestas = iter(["quizás", "a"])
    r = main(["evaluación", "de", "impacto", "--thread-id", "cli"], deps=deps, input_fn=lambda _: next(respuestas))

    assert r["archivo"] == str(tmp_path / "cli.json")
    salida = capsys.readouterr().out
    assert "Shortlist (2)" in salida
    assert "Responde 'a' (aprobar) o 'r' (rechazar)." in salida
