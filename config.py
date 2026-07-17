"""Central configuration, loaded from environment / .env.

Everything the scripts need to know (Neo4j connection, which organism to
build, which LLM backend to use) is resolved here so the rest of the code
stays declarative.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"

load_dotenv(ROOT / ".env")

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "thesisgraph123")

# --- Dataset scope ---
# 511145 = Escherichia coli K-12 MG1655 (the best-annotated model bacterium).
TAXID = int(os.getenv("TAXID", "511145"))
SPECIES_NAME = os.getenv("SPECIES_NAME", "Escherichia coli")
# Keep the graph small and legible: the N most-abundant proteins.
TOP_N = int(os.getenv("TOP_N", "200"))
# STRING combined-score cutoff (0-1000). 700 = "high confidence".
STRING_SCORE_MIN = int(os.getenv("STRING_SCORE_MIN", "700"))

# Path to the PaxDB abundance CSV already produced by the ~/RWTH pipeline.
# The build script copies the needed slice into this repo's data/ folder,
# so the repo stays self-contained after the first build.
PAXDB_SOURCE_CSV = os.getenv(
    "PAXDB_SOURCE_CSV",
    str(Path.home() / "RWTH" / "data" / "processed" / f"{TAXID}_abundance.csv"),
)

# --- LLM backend ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "template").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
