from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class Criterios(BaseModel):
    consulta: str = Field(description="Consulta de búsqueda para el motor RAG")
    perfil: str = Field(description="Resumen del perfil del consultor")
    temas: list[str] = Field(default_factory=list, description="Temas o áreas de interés")


class Lead(BaseModel):
    texto: str
    oportunidad_id: str | None = None
    post_url: str | None = None
    author_name: str | None = None


# El evaluador identifica cada lead por su número en el listado del prompt ([1], [2], ...)
# y no por post_url: la URL puede venir vacía y el LLM puede alterarla al copiarla.
class Evaluacion(BaseModel):
    indice: int = Field(ge=1, description="Número del lead tal como aparece en el listado: [1], [2], ...")
    score: int = Field(ge=0, le=10, description="Encaje del lead con el perfil, de 0 a 10")
    razon: str = Field(description="Por qué ese score, en una o dos frases")


class Evaluaciones(BaseModel):
    items: list[Evaluacion]


class AgentState(TypedDict, total=False):
    solicitud: str
    criterios: Criterios
    leads: list[Lead]
    evaluaciones: list[Evaluacion]
    intentos: int
    decision: Literal["aprobar", "rechazar"]
    archivo: str | None
