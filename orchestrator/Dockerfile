FROM python:3.13-slim

WORKDIR /app

# 依赖先装，利用 Docker layer 缓存
COPY orchestrator/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 复制 orchestrator 包和共享契约
COPY orchestrator/ orchestrator/
COPY shared/ shared/

# 非 root 运行
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8081

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "-m", "orchestrator.server"]
