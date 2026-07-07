# build for the judging VM: docker buildx build --platform linux/amd64 ...
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

COPY paperflow/ paperflow/
COPY ui/ ui/
COPY synthetic/ synthetic/

EXPOSE 8080
CMD ["uvicorn", "paperflow.api:app", "--host", "0.0.0.0", "--port", "8080"]
