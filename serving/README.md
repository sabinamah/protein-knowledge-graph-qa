# Serving layer

Turns the knowledge-graph QA pipeline in [`../src`](../src) into a running
service: a **REST API**, an **MCP server**, and a **Docker Compose** stack. Both
interfaces call the same pipeline (`service.py` wraps `src/ask.py` +
`src/nl2cypher.py`), so there is no duplicated logic.

The NL->Cypher backend is selected with `LLM_BACKEND` (see the repo's
`.env.example`): `template` (rule-based, no model), `anthropic`, `ollama`, or
`openai` — the OpenAI-compatible backend, which talks to any
`/v1/chat/completions` endpoint such as a self-managed **vLLM** server or an
inference gateway.

## Files
```
serving/
  service.py       shared wrapper around the src/ pipeline
  api.py           FastAPI REST API  (GET /health, POST /ask)
  mcp_server.py    MCP server exposing the pipeline as a tool
  test_service.py  pytest suite (runs with no DB and no model server)
  Dockerfile
  requirements.txt
```

## Run the API (needs a running Neo4j with the graph loaded)
```bash
pip install -r requirements.txt -r serving/requirements.txt
uvicorn serving.api:app --port 8080

curl localhost:8080/health
curl -X POST localhost:8080/ask -H 'content-type: application/json' \
     -d '{"question": "what does gapA interact with?"}'
```
Each answer comes back with the generated Cypher and the evidence rows, so it
stays traceable to the graph.

## Run the MCP server
```bash
python -m serving.mcp_server
```
Exposes one tool, `ask_protein_graph`, over stdio for any MCP-compatible client.

## Run the tests (no database needed)
```bash
pytest -q serving/test_service.py
```

## Docker Compose (API + Neo4j)
```bash
docker compose up --build
# LLM_BACKEND defaults to "template"; set LLM_BACKEND=openai and OPENAI_BASE_URL
# to use a self-managed vLLM / gateway.
```
