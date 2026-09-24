#!/bin/zsh
# 智能交易工作台 · Pipeline 服务启动脚本
# 用法: sh scripts/run_pipeline_server.sh
# 依赖: fastapi / uvicorn / websocket-client / httpx (已装在 .venv)

cd "$(dirname "$0")/.." || exit 1

PY=.venv/bin/python

# 代理探测:系统代理环境变量存在则先 ping Binance;不通则本轮禁用代理直连
if [ -n "$HTTPS_PROXY" ] || [ -n "$https_proxy" ]; then
  if ! curl -s -m 6 -o /dev/null -w "" "https://fapi.binance.com/fapi/v1/ping" 2>/dev/null; then
    echo "[启动器] 检测到系统代理不可达,本轮改直连(清空代理变量)"
    unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
  fi
fi

echo "[启动器] 服务地址: http://127.0.0.1:8788"
echo "[启动器] Ctrl+C 停止"
exec "$PY" -m binance_quant.pipeline.server "$@"
