"""Read API served by the agent on the database server."""

from __future__ import annotations

import hmac
import threading
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agent.localstore import AgentStore
from collector.store import now_text


class RetentionItem(BaseModel):
    data_kind: str
    keep_days: int = Field(ge=0, le=3650)
    enabled: bool = True


class RetentionBody(BaseModel):
    save_interval_sec: int = Field(ge=2, le=86400)
    purge_interval_sec: int = Field(ge=15, le=86400)
    policies: list[RetentionItem]


def create_agent_app(store: AgentStore, token: str) -> FastAPI:
    app = FastAPI(title="OKEDBMON Agent")

    def authorized(x_agent_token: str | None) -> None:
        supplied = x_agent_token or ""
        if len(supplied) != len(token) or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="에이전트 토큰이 올바르지 않습니다.")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "agent_alias": store.alias, "store_path": str(store.path)}

    @app.get("/api/sessions/active")
    def active_sessions(x_agent_token: str | None = Header(default=None)):
        authorized(x_agent_token)
        rows = store.current_sessions()
        return {"collect_tm": rows[0]["agent_collect_tm"] if rows else None, "sessions": rows}

    @app.get("/api/sessions/history")
    def session_history(
        start: str | None = None,
        end: str | None = None,
        sql_id: str = "",
        x_agent_token: str | None = Header(default=None),
    ):
        authorized(x_agent_token)
        end_text = end or now_text()
        start_text = start or now_text(datetime.now() - timedelta(hours=1))
        return {"sessions": store.session_history(start_text, end_text, sql_id)}

    @app.get("/api/sql")
    def sql_list(q: str = "", limit: int = 80, x_agent_token: str | None = Header(default=None)):
        authorized(x_agent_token)
        return {"sql": store.sql_catalog(q, limit=max(1, min(limit, 200)))}

    @app.get("/api/retention")
    def retention(x_agent_token: str | None = Header(default=None)):
        authorized(x_agent_token)
        return store.retention_status()

    @app.put("/api/retention")
    def put_retention(body: RetentionBody, x_agent_token: str | None = Header(default=None)):
        authorized(x_agent_token)
        store.update_schedule(body.save_interval_sec, body.purge_interval_sec)
        store.update_retention([item.model_dump() for item in body.policies])
        return store.retention_status()

    @app.post("/api/retention/run")
    def run_retention(x_agent_token: str | None = Header(default=None)):
        authorized(x_agent_token)
        summary = store.purge()
        status = store.retention_status()
        status["summary"] = summary
        return status

    return app


def start_query_server(store: AgentStore, token: str, host: str, port: int) -> None:
    app = create_agent_app(store, token)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name=f"agent-query-{store.alias}", daemon=True)
    thread.start()


def start_purge_loop(store: AgentStore) -> None:
    def loop() -> None:
        import time

        while True:
            time.sleep(store.purge_interval())
            try:
                store.purge()
            except Exception as exc:
                print(f"purge failed {store.alias}: {exc}", flush=True)

    threading.Thread(target=loop, name=f"agent-purge-{store.alias}", daemon=True).start()
