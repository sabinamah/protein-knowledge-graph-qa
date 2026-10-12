# Container for the REST API. Build context is the repo root so the image
# includes both the pipeline (src/, config.py) and the serving layer.
FROM python:3.11-slim
WORKDIR /srv

COPY requirements.txt ./root-requirements.txt
COPY serving/requirements.txt ./serving-requirements.txt
RUN pip install --no-cache-dir -r root-requirements.txt -r serving-requirements.txt

COPY config.py ./config.py
COPY src ./src
COPY serving ./serving

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status==200 else 1)"

CMD ["uvicorn", "serving.api:app", "--host", "0.0.0.0", "--port", "8080"]
