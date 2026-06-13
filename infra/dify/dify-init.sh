#!/usr/bin/env bash
# dify-init.sh — 首次启动 Dify 时执行数据库迁移
# 用法：在 docker compose up -d 之后运行一次
# ./infra/dify/dify-init.sh

set -e

echo "Waiting for dify-api to be ready..."
until curl -sf http://localhost:5001/v1/health > /dev/null 2>&1; do
  sleep 3
done

echo "Running Dify DB migrations..."
docker compose exec dify-api flask db upgrade

echo "Dify init complete. Now visit http://localhost/dify/ to finish setup."