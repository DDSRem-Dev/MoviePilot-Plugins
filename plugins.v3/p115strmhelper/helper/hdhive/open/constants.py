"""
HDHive Open API 与 OAuth 常量
"""

HDHIVE_OPEN_BASE_URL = "https://hdhive.com/api/open"

# 集中 OAuth 中转（公网 HTTPS）；authorize 由 broker 生成
HDHIVE_OAUTH_BROKER_BASE = "https://hdhive-auth.example.com"

DEFAULT_OAUTH_SCOPES = "query unlock"
TOKEN_EXPIRY_BUFFER_SEC = 60
PLUGIN_DATA_KEY_OAUTH = "hdhive_oauth"
