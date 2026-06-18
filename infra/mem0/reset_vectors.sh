#!/usr/bin/env bash
# Mem0 向量表维度重置脚本
#
# 用途：切换 embedding 模型后（如 xinference 1536 维 → bge-m3 1024 维），
# 旧的 mem0_vectors 表维度与新模型不匹配，写入会报
# "expected 1536 dimensions, not 1024"。本脚本 DROP 掉旧表，
# mem0 下次写入时会自动按新的 EMBEDDING_DIMS 重建。
#
# ⚠️ 会清空所有已存记忆向量，不可逆。仅在切换 embedding 模型时使用。
#
# 用法（主目录执行）：
#     bash infra/mem0/reset_vectors.sh
# 然后重启 mem0：
#     docker compose restart mem0

set -euo pipefail

# 从 .env 读 postgres 连接信息（脚本在主目录运行，.env 在主目录）
ENV_FILE="${ENV_FILE:-.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "找不到 $ENV_FILE，请在主目录（含 .env）执行本脚本" >&2
  exit 1
fi

# 提取变量（只取等号后内容，忽略注释行）
PG_USER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | head -1 | cut -d= -f2-)
PG_DB=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | head -1 | cut -d= -f2-)
PG_USER="${PG_USER:-familyagent}"
PG_DB="${PG_DB:-familyagent}"

echo "═══════════════════════════════════════════════════════════"
echo " Mem0 向量表重置"
echo "  数据库：$PG_DB    用户：$PG_USER    表：mem0_vectors"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "⚠️  此操作将 DROP TABLE mem0_vectors，清空所有已存记忆向量，不可逆。"
read -r -p "确认继续？输入 yes 执行：" CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "已取消。"
  exit 0
fi

# 通过运行中的 postgres 容器执行 DROP（容器名 familyagent-postgres-1）
PG_CONTAINER="${PG_CONTAINER:-familyagent-postgres-1}"

if ! docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
  echo "找不到运行中的 postgres 容器 $PG_CONTAINER" >&2
  echo "可用 PG_CONTAINER=<容器名> bash infra/mem0/reset_vectors.sh 指定" >&2
  docker ps --format '  {{.Names}}' | grep -i postgres || true
  exit 1
fi

echo ""
echo "DROP TABLE mem0_vectors ..."
docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" \
  -c "DROP TABLE IF EXISTS mem0_vectors;"

echo ""
echo "✓ 已删除 mem0_vectors。下一步重启 mem0，让它按新维度自动重建："
echo "    docker compose restart mem0"
