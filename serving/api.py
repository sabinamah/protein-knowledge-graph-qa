"""REST API over the protein knowledge-graph QA pipeline.

Endpoints:
  GET  /health   liveness + which backends are configured (for observability)
  POST /ask      {"question": "..."} -> answer + generated Cypher + evidence rows

Run (from the repo root):
  uvicorn serving.api:app --port 8080
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from serving.service import QAService

service = QAService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    service.close()


app = FastAPI(title="Protein KG QA", version="1.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", **service.config_summary()}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    try:
        return service.answer(req.question)
    except Exception as e:  # surface pipeline errors as 400s, not 500s
        raise HTTPException(status_code=400, detail=str(e))
