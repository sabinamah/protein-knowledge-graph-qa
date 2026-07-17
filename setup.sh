#!/usr/bin/env bash
# Reproducible setup for the protein knowledge graph.
# Assumes Neo4j is installed and running (see README step 1).
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Python environment"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
  echo "==> Creating .env from template"
  cp .env.example .env
fi

echo "==> Building dataset (PaxDB + STRING + UniProt)"
./venv/bin/python src/build_dataset.py

echo "==> Loading graph into Neo4j"
./venv/bin/python src/load_graph.py

echo "==> Done. Try:  ./venv/bin/python src/ask.py \"what does gapA interact with?\""
