FROM zhayujie/chatgpt-on-wechat:latest

# 把自定义插件复制进容器，挂载方式在官方镜像里有时不触发插件注册
COPY plugins/orchestrator_forwarder /app/plugins/orchestrator_forwarder

RUN pip install --no-cache-dir httpx==0.27.0