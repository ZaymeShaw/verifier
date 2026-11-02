"""python -m impl.tool_loop_lab --port 8030：独立运行，不启动评测服务或 tracing relay。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import router


def create_app():
    app = FastAPI(title='ToolLoop Lab')
    app.include_router(router)
    app.mount('/frontend', StaticFiles(directory=str(Path(__file__).resolve().parents[1] / 'frontend')), name='frontend')

    @app.get('/')
    def index():
        return RedirectResponse('/frontend/tool_loop_lab.html')
    return app


def main():
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8030)
    args = parser.parse_args()
    uvicorn.run(create_app(), host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
