"""Collection server: ingest, query, environment settings, and retention."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from collector.store import ROOT, Store, load_properties, now_text, repository_path
from collector.version import PRODUCT, VERSION, display_name

WEB = ROOT / "web"


class LoginBody(BaseModel):
    username: str
    password: str


class InstanceBody(BaseModel):
    agent_alias: str
    product: str
    host_nm: str
    port: int
    db_name: str = ""
    username: str = ""
    group_nm: str = ""
    collect_interval_sec: int = 5
    enabled: bool = True
    description: str = ""


class SettingsBody(BaseModel):
    values: dict[str, str]


class RetentionItem(BaseModel):
    data_kind: str
    keep_days: int = Field(ge=0, le=3650)
    enabled: bool = True


class RetentionBody(BaseModel):
    policies: list[RetentionItem]


class IngestBody(BaseModel):
    agent_alias: str
    product: str = ""
    collect_tm: str
    version: str = VERSION
    status: str = "ONLINE"
    message: str = ""
    performance: dict | None = None
    active_sessions: list[dict] = Field(default_factory=list)
    session_history: list[dict] = Field(default_factory=list)
    sql_texts: list[dict] = Field(default_factory=list)
    sql_stats: list[dict] = Field(default_factory=list)


def create_app(store: Store | None = None) -> FastAPI:
    props = load_properties()
    if store is None:
        store = Store(repository_path(props), props)
    app = FastAPI(title=f"{PRODUCT} Collector", version=store.setting("support.ver", VERSION))
    app.state.store = store
    _start_retention_loop(store)

    def current_user(authorization: str | None = Header(default=None)) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        token = authorization.split(" ", 1)[1].strip()
        user = store.user_for_token(token)
        if user is None:
            raise HTTPException(status_code=401, detail="세션이 만료되었습니다.")
        return user

    @app.get("/api/health")
    def health():
        title = store.setting("support.title", PRODUCT)
        version = store.setting("support.ver", VERSION)
        return {"status": "ok", "time": now_text(), "title": title, "version": version, "display": display_name(title, version)}

    @app.post("/api/login")
    def login(body: LoginBody):
        token = store.login(body.username.strip(), body.password)
        if token is None:
            raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
        return {"token": token}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return user

    @app.get("/api/dashboard")
    def dashboard(user: dict = Depends(current_user)):
        return store.dashboard()

    @app.get("/api/instances")
    def instances(user: dict = Depends(current_user)):
        return {"instances": store.list_instances()}

    @app.post("/api/instances")
    def create_instance(body: InstanceBody, user: dict = Depends(current_user)):
        try:
            store.save_instance(body.model_dump(), create=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.put("/api/instances/{alias}")
    def update_instance(alias: str, body: InstanceBody, user: dict = Depends(current_user)):
        payload = body.model_dump()
        payload["agent_alias"] = alias
        try:
            store.save_instance(payload, create=False)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True}

    @app.delete("/api/instances/{alias}")
    def delete_instance(alias: str, user: dict = Depends(current_user)):
        store.delete_instance(alias)
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings(user: dict = Depends(current_user)):
        return {"settings": store.settings_public()}

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, user: dict = Depends(current_user)):
        try:
            store.update_settings(body.values)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"settings": store.settings_public()}

    @app.get("/api/retention")
    def get_retention(user: dict = Depends(current_user)):
        return {"policies": store.retention_status(), "log": store.purge_log()}

    @app.put("/api/retention")
    def put_retention(body: RetentionBody, user: dict = Depends(current_user)):
        store.update_retention([item.model_dump() for item in body.policies])
        return {"policies": store.retention_status()}

    @app.post("/api/retention/run")
    def run_retention(user: dict = Depends(current_user)):
        summary = store.purge()
        return {"summary": summary, "policies": store.retention_status(), "log": store.purge_log()}

    @app.get("/api/performance")
    def performance(
        alias: str,
        start: str | None = None,
        end: str | None = None,
        user: dict = Depends(current_user),
    ):
        end_text = end or now_text()
        start_text = start or now_text(datetime.now() - timedelta(hours=1))
        return {"series": store.performance_series(alias, start_text, end_text)}

    @app.get("/api/sessions/active")
    def active_sessions(alias: str, user: dict = Depends(current_user)):
        rows = store.current_sessions(alias)
        return {"collect_tm": rows[0]["agent_collect_tm"] if rows else None, "sessions": rows, "locks": _lock_tree(rows)}

    @app.get("/api/sessions/history")
    def session_history(
        alias: str,
        start: str | None = None,
        end: str | None = None,
        sql_id: str = "",
        user: dict = Depends(current_user),
    ):
        end_text = end or now_text()
        start_text = start or now_text(datetime.now() - timedelta(hours=1))
        return {"sessions": store.session_history(alias, start_text, end_text, sql_id)}

    @app.get("/api/sql")
    def sql_list(alias: str, q: str = "", user: dict = Depends(current_user)):
        return {"sql": store.sql_catalog(alias, q)}

    @app.get("/api/events")
    def events(alias: str = "", user: dict = Depends(current_user)):
        return {"events": store.events(alias)}

    @app.get("/api/report")
    def report(
        alias: str,
        start: str | None = None,
        end: str | None = None,
        user: dict = Depends(current_user),
    ):
        end_text = end or now_text()
        start_text = start or now_text(datetime.now() - timedelta(hours=6))
        return store.report(alias, start_text, end_text)

    @app.post("/api/ingest")
    def ingest(body: IngestBody, x_agent_token: str | None = Header(default=None)):
        if not store.agent_authorized(x_agent_token or ""):
            raise HTTPException(status_code=401, detail="에이전트 토큰이 올바르지 않습니다.")
        return store.ingest(body.model_dump())

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


def _lock_tree(sessions: list[dict]) -> list[dict]:
    by_sid = {row["sid"]: row for row in sessions if row.get("sid") is not None}
    children: dict[int, list[dict]] = {}
    waiting = []
    for row in sessions:
        blocker = row.get("blocking_sid")
        if blocker and blocker in by_sid and blocker != row.get("sid"):
            children.setdefault(blocker, []).append(row)
            waiting.append(row["sid"])
    roots = []
    for row in sessions:
        sid = row.get("sid")
        if sid in waiting:
            continue
        if sid in children or row.get("wait_class") == "Lock":
            roots.append(_lock_node(row, children))
    return roots


def _lock_node(row: dict, children: dict[int, list[dict]]) -> dict:
    sid = row.get("sid")
    return {
        "sid": sid,
        "db_user": row.get("db_user"),
        "sql_id": row.get("sql_id"),
        "sql_text": row.get("sql_text"),
        "wait_event": row.get("wait_event"),
        "elapsed_ms": row.get("elapsed_ms"),
        "children": [_lock_node(child, children) for child in children.get(sid, [])],
    }


def _start_retention_loop(store: Store) -> None:
    if getattr(store, "_retention_started", False):
        return
    store._retention_started = True

    def loop() -> None:
        while True:
            try:
                interval = max(15, int(store.setting("retention.purge.interval.sec", "60")))
            except ValueError:
                interval = 60
            time.sleep(interval)
            try:
                store.purge()
            except Exception:
                continue

    thread = threading.Thread(target=loop, name="retention", daemon=True)
    thread.start()


def build_demo_history(store: Store) -> None:
    """Fill an hour of samples so charts are usable before the agent catches up."""
    if store.conn.execute("SELECT COUNT(*) AS c FROM o_performance").fetchone()["c"]:
        return
    from agent.simulate import Simulator

    moment = datetime.now() - timedelta(minutes=60)
    end = datetime.now() - timedelta(seconds=5)
    step = timedelta(seconds=20)
    sims = {
        row["agent_alias"]: Simulator(
            {
                "agent_alias": row["agent_alias"],
                "product": row["product"],
                "host": row["host_nm"],
                "database": row["db_name"],
            }
        )
        for row in store.list_instances()
    }
    while moment <= end:
        for sim in sims.values():
            payload = sim.collect(moment)
            store.ingest(payload)
        moment += step
