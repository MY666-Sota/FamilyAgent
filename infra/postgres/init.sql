-- 在 postgres 启动时运行，创建 pgvector 扩展供 Mem0 使用
CREATE EXTENSION IF NOT EXISTS vector;