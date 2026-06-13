FROM python:3.11-slim

WORKDIR /app

# psycopg2 需要 libpq
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi==0.111.0 \
    uvicorn[standard]==0.30.1 \
    mem0ai==0.1.29 \
    psycopg2-binary==2.9.9 \
    pydantic==2.7.4

COPY app.py .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082"]
