from collections import defaultdict
import json

import requests
from llama_index.core import Document

from rag import config

ROW_LIMIT = 250


class N8NTableClient:
    def __init__(self, base_url: str = config.N8N_URL, api_key: str = config.N8N_API_KEY):
        self.base_url = base_url
        self.headers = {"X-N8N-API-KEY": api_key}
        self._table_ids = {}

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(f"{self.base_url}{path}", headers=self.headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _table_id(self, table_name: str) -> str:
        if not self._table_ids:
            data = self._get("/api/v1/data-tables", {"limit": ROW_LIMIT})["data"]
            self._table_ids = {t["name"]: t["id"] for t in data}
        return self._table_ids[table_name]

    def fetch_all_rows(self, table_name: str) -> list[dict]:
        table_id = self._table_id(table_name)
        rows, cursor = [], None
        while True:
            params = {"limit": ROW_LIMIT}
            if cursor:
                params["cursor"] = cursor
            page = self._get(f"/api/v1/data-tables/{table_id}/rows", params)
            rows.extend(page["data"])
            cursor = page.get("nextCursor")
            if not cursor:
                return rows


def _latest_matches_by_pair(resultados_match_rows: list[dict]) -> dict[tuple[str, str], dict]:
    # `todos_los_resultados` (schema plano: oportunidad_id/consultor_id/score_match/tipo_oportunidad)
    # y `top_10_matches` (schema anidado: ids.consultor/ids.oportunidad/score/tipo) tienen
    # estructuras distintas en la práctica — se normalizan ambas acá.
    latest: dict[tuple[str, str], dict] = {}
    runs = sorted(resultados_match_rows, key=lambda r: r.get("fecha_ejecucion") or "")
    for run in runs:
        raw = run.get("todos_los_resultados") or run.get("top_10_matches") or "[]"
        try:
            entries = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        for entry in entries:
            ids = entry.get("ids") or {}
            consultor_id = entry.get("consultor_id") or ids.get("consultor")
            oportunidad_id = entry.get("oportunidad_id") or ids.get("oportunidad")
            if not consultor_id or not oportunidad_id:
                continue
            latest[(str(consultor_id), str(oportunidad_id))] = {
                "score": entry.get("score_match", entry.get("score")),
                "tipo": entry.get("tipo_oportunidad", entry.get("tipo")),
                "decision": entry.get("decision"),
                "motivo": entry.get("motivo"),
                "fecha_ejecucion": run.get("fecha_ejecucion"),
            }
    return latest


def fetch_documents() -> list[Document]:
    client = N8NTableClient()

    jobs = client.fetch_all_rows("linkedin_jobs")
    posts_by_id = {p["post_id"]: p for p in client.fetch_all_rows("linkedin_posts")}
    consultores_by_id = {str(c["id"]): c for c in client.fetch_all_rows("Consultores")}
    matches_by_pair = _latest_matches_by_pair(client.fetch_all_rows("resultados_match"))

    ocr_by_post_id = defaultdict(list)
    for r in client.fetch_all_rows("linkedin_ocr_results"):
        if r.get("ocr_text"):
            ocr_by_post_id[r["post_id"]].append(r["ocr_text"])

    documents = []
    for job in jobs:
        oportunidad_id = str(job["id"])
        post = posts_by_id.get(job.get("post_id"), {})
        ocr_text = "\n".join(ocr_by_post_id.get(job.get("post_id"), []))

        content = "\n\n".join(filter(None, [
            f"Cargo: {job.get('cargo', '')}",
            f"Ubicación: {job.get('ciudad', '')} {job.get('pais', '')}".strip(),
            f"Objetivo del cargo: {job.get('objetivo_del_cargo', '')}",
            f"Prerrequisitos: {job.get('prerrequisitos', '')}",
            post.get("post_text", ""),
            ocr_text,
        ]))
        if not content.strip():
            continue

        matches = [
            {"consultor_id": cid, "nombre_consultor": consultores_by_id.get(cid, {}).get("nombre_consultor"), **info}
            for (cid, oid), info in matches_by_pair.items()
            if oid == oportunidad_id
        ]

        documents.append(Document(
            doc_id=f"linkedin_jobs:{oportunidad_id}",
            text=content,
            metadata={
                "oportunidad_id": oportunidad_id,
                "post_id": job.get("post_id"),
                "post_url": post.get("post_url"),
                "profile_url": post.get("profile_url"),
                "author_name": post.get("author_name"),
                "cargo": job.get("cargo"),
                "ciudad": job.get("ciudad"),
                "pais": job.get("pais"),
                "fecha_limite": job.get("fecha_limite"),
                "aplica_en": job.get("aplica_en"),
                "existing_matches": matches,
            },
        ))

    return documents
