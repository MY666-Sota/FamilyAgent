FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.111.0 uvicorn[standard]==0.30.1 httpx==0.27.0 pydantic==2.7.4

COPY app.py .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
