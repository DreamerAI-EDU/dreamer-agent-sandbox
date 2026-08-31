"""Docker 容器入口：aiohttp CLI 會塞 argv 入 factory，build_app() 係零參，所以要呢個 wrapper。"""
from aiohttp import web
from auth.api import build_app
if __name__ == "__main__":
    web.run_app(build_app(), host="0.0.0.0", port=8000)
