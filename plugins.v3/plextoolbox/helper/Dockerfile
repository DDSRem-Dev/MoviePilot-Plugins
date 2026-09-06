FROM python:3.12-alpine

# Plex MediaInfo Helper —— 在 Plex 所在机器本地安全写库的小服务
# 仅依赖 Python 标准库，无需 pip 安装任何包

WORKDIR /app
COPY plex_mediainfo_helper.py /app/plex_mediainfo_helper.py

# 默认端口，可用环境变量 PTH_PORT 覆盖
EXPOSE 9001

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python3 -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PTH_PORT','9001')+'/health',timeout=4)" || exit 1

ENTRYPOINT ["python3", "/app/plex_mediainfo_helper.py"]
