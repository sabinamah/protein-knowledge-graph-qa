"""MCP server exposing the knowledge-graph QA pipeline as a tool.

Any MCP-compatible client (an agent framework, an IDE assistant, a coding
harness) can call `ask_protein_graph` and receive the grounded answer together
with the generated Cypher and the evidence rows.

Run (from the repo root):
  python -m serving.mcp_server
"""
from mcp.server.fastmcp import FastMCP

from serving.service import QAService

mcp = FastMCP("protein-kg-qa")
_service = QAService()


@mcp.tool()
def ask_protein_graph(question: str) -> dict:
    """Answer a question about the E. coli protein interaction graph.

    Returns the answer, the generated Cypher query, and the evidence rows the
    answer was grounded in, so the result stays traceable.
    """
    return _service.answer(question)


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
