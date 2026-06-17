#!/usr/bin/env bash
# FamilyAgent 对外契约接口端到端冒烟测试
#
# 用途：每次启动 docker compose 后，一键验证所有对外接口是否就绪。
# 用法（在主目录 F:\AI_Asset_Library\02_Projects_AI\FamilyAgent 下直接跑）：
#     bash infra/smoke_test.sh
#
# 注意：本机配了代理会拦截 localhost，所有 curl 均加 --noproxy localhost。

set -u

# 颜色（终端不支持时自动降级为空）
if [ -t 1 ]; then
  G='\033[0;32m'; R='\033[0;31m'; Y='\033[0;33m'; N='\033[0m'
else
  G=''; R=''; Y=''; N=''
fi

PASS=0
FAIL=0

# check <名称> <期望码> <curl 参数...>
check() {
  local name="$1"; local want="$2"; shift 2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --noproxy localhost --max-time 10 "$@" 2>/dev/null)
  if [ "$code" = "$want" ]; then
    printf "${G}PASS${N}  %-40s [HTTP %s]\n" "$name" "$code"
    PASS=$((PASS+1))
  else
    printf "${R}FAIL${N}  %-40s [HTTP %s, 期望 %s]\n" "$name" "${code:-无响应}" "$want"
    FAIL=$((FAIL+1))
  fi
}

echo "═══════════════════════════════════════════════════════════"
echo " FamilyAgent 对外契约接口冒烟测试"
echo "═══════════════════════════════════════════════════════════"

echo ""
echo "── Mem0 记忆层（契约一.2）─────────────────────────────────"
check "Mem0 健康检查 /healthz"            200 "http://localhost:8082/healthz"
check "Mem0 读记忆 /v1/memory/test_user"  200 "http://localhost:8082/v1/memory/test_user"

echo ""
echo "── RAG 检索 / dify-adapter（契约一.1）─────────────────────"
check "dify-adapter 健康检查 /healthz"     200 "http://localhost:5001/healthz"

echo ""
echo "── Dify 控制台（B4-2 直连暴露）────────────────────────────"
# Dify 控制台前端返回 200；后端健康端点确认 API 已暴露
check "Dify 控制台前端 :3000"              200 "http://localhost:3000"
check "Dify-api 控制台后端 :5002/health"   200 "http://localhost:5002/health"

echo ""
echo "═══════════════════════════════════════════════════════════"
printf " 结果：${G}%d PASS${N} / ${R}%d FAIL${N}\n" "$PASS" "$FAIL"
echo "═══════════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo -e "${Y}提示${N}："
  echo "  - 全部 FAIL：确认主目录已 docker compose up，8 个容器在跑"
  echo "  - :3000 / :5002 FAIL：需在主目录 git pull 后 docker compose up -d dify-web dify-api"
  echo "  - RAG 查询返回 502：正常，需先在 Dify 控制台建知识库并回填 .env"
  echo "    （详见 infra/B4_STARTUP_REPORT.md）"
  exit 1
fi

echo ""
echo -e "${G}全部接口就绪。${N}"
exit 0
