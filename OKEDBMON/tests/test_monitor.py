import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from agent.collectors import make_collector
from agent.osmetrics import read_host_metrics
from agent.simulate import Simulator
from collector.server import create_app
from collector.store import Store, load_properties, now_text


def build(tmp_path: Path):
    store = Store(tmp_path / "repo.sqlite", load_properties(), seed=True)
    app = create_app(store)
    return store, TestClient(app)


def login(client: TestClient) -> str:
    response = client.post("/api/login", json={"username": "admin", "password": "okedbmon"})
    assert response.status_code == 200
    return response.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def sample_payload(alias="ORA_PROD", moment=None, sql="SELECT 1 FROM dual", sql_key="abc"):
    moment = moment or datetime.now()
    return {
        "agent_alias": alias,
        "product": "ORACLE",
        "collect_tm": now_text(moment),
        "status": "ONLINE",
        "performance": {
            "instance_nm": "ORCL",
            "cpu_usage": 91,
            "mem_usage": 60,
            "active_sessions": 3,
            "connected_sessions": 5,
            "lock_wait": 1,
            "buffer_cache_ratio": 88,
            "execute_cnt": 20,
            "user_commits": 4,
            "tps": 0.8,
            "qps": 4,
            "extra": {"mode": "test"},
        },
        "active_sessions": [
            {
                "sid": 10,
                "serial_number": 1,
                "status": "ACTIVE",
                "db_user": "APP",
                "sql_id": sql_key,
                "sql_text": sql,
                "wait_event": "ON CPU",
                "wait_class": "CPU",
                "elapsed_ms": 1200,
            },
            {
                "sid": 11,
                "serial_number": 2,
                "status": "ACTIVE",
                "db_user": "APP",
                "sql_id": "def",
                "sql_text": "UPDATE orders SET status='PAID'",
                "wait_event": "enq: TX - row lock contention",
                "wait_class": "Lock",
                "elapsed_ms": 3400,
                "blocking_sid": 10,
            },
        ],
        "session_history": [
            {
                "sid": 11,
                "status": "ACTIVE",
                "sql_id": "def",
                "sql_text": "UPDATE orders SET status='PAID'",
                "elapsed_ms": 3400,
                "source": "sample",
            }
        ],
        "sql_texts": [{"sql_id": sql_key, "sql_text": sql, "command_type": "SELECT", "db_user": "APP"}],
        "sql_stats": [{"sql_id": sql_key, "executions": 4, "elapsed_ms": 80, "buffer_gets": 10, "disk_reads": 1, "rows_processed": 4}],
    }


def test_login_and_ingest_flow(tmp_path):
    store, client = build(tmp_path)
    assert client.post("/api/login", json={"username": "admin", "password": "nope"}).status_code == 401
    token = login(client)
    assert client.get("/api/dashboard").status_code == 401
    denied = client.post("/api/ingest", json=sample_payload())
    assert denied.status_code == 401

    accepted = client.post("/api/ingest", json=sample_payload(), headers={"X-Agent-Token": "okedbmon-agent"})
    assert accepted.status_code == 200

    dashboard = client.get("/api/dashboard", headers=auth(token)).json()
    card = next(item for item in dashboard["instances"] if item["agent_alias"] == "ORA_PROD")
    assert card["online"] is True
    assert card["cpu_usage"] == 91
    assert "CPU" in card["alerts"]
    assert "LOCK" in card["alerts"]
    assert "CACHE" in card["alerts"]

    stored = store.conn.execute("SELECT COUNT(*) AS c FROM active_session").fetchone()["c"]
    assert stored == 0
    missing = client.get("/api/sessions/active", params={"alias": "ORA_PROD"}, headers=auth(token))
    assert missing.status_code == 503
    store.close()


def test_retention_deletes_only_expired_rows(tmp_path):
    store, client = build(tmp_path)
    token = login(client)
    old = datetime.now() - timedelta(days=10)
    fresh = datetime.now()
    client.post("/api/ingest", json=sample_payload(moment=old, sql="SELECT old_row FROM dual", sql_key="old"), headers={"X-Agent-Token": "okedbmon-agent"})
    client.post("/api/ingest", json=sample_payload(moment=fresh, sql="SELECT fresh_row FROM dual", sql_key="new"), headers={"X-Agent-Token": "okedbmon-agent"})
    client.put(
        "/api/retention",
        headers=auth(token),
        json={"policies": [
            {"data_kind": "performance", "keep_days": 3, "enabled": True},
            {"data_kind": "event", "keep_days": 30, "enabled": False},
        ]},
    )
    summary = client.post("/api/retention/run", headers=auth(token)).json()["summary"]
    deleted = {item["data_kind"]: item["deleted_rows"] for item in summary}
    assert deleted == {"performance": 1, "event": 0}
    kinds = {item["data_kind"] for item in client.get("/api/retention", headers=auth(token)).json()["policies"]}
    assert kinds == {"performance", "event"}
    store.close()


def test_agent_keeps_sessions_and_sql(tmp_path):
    import socket
    import threading
    import time

    import uvicorn

    from agent.localstore import AgentStore
    from agent.query import create_agent_app

    local = AgentStore(tmp_path / "agent.sqlite", "ORA_PROD", save_interval_sec=5, purge_interval_sec=60)
    old = datetime.now() - timedelta(days=10)
    fresh = datetime.now()
    local.save_sample(sample_payload(moment=old, sql="SELECT old_row FROM dual", sql_key="old"))
    local.save_sample(sample_payload(moment=fresh, sql="SELECT fresh_row FROM dual", sql_key="new"))
    local.update_retention([
        {"data_kind": "active_session", "keep_days": 3, "enabled": True},
        {"data_kind": "session_history", "keep_days": 3, "enabled": True},
        {"data_kind": "sql_text", "keep_days": 3, "enabled": True},
        {"data_kind": "sql_stat", "keep_days": 3, "enabled": True},
    ])
    deleted = {item["data_kind"]: item["deleted_rows"] for item in local.purge()}
    assert deleted["active_session"] == 2
    assert deleted["session_history"] == 1
    assert deleted["sql_text"] == 1
    assert local.current_sessions()[0]["agent_collect_tm"] == now_text(fresh)
    assert local.sql_catalog("old_row") == []
    assert local.sql_catalog("fresh")[0]["sql_text"].startswith("SELECT fresh")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_agent_app(local, "okedbmon-agent")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while time.time() < deadline and not server.started:
        time.sleep(0.05)

    store, client = build(tmp_path)
    token = login(client)
    accepted = client.post(
        "/api/ingest",
        json={**sample_payload(), "agent_url": f"http://127.0.0.1:{port}"},
        headers={"X-Agent-Token": "okedbmon-agent"},
    )
    assert accepted.status_code == 200
    assert store.conn.execute("SELECT COUNT(*) AS c FROM sql_text").fetchone()["c"] == 0
    sessions = client.get("/api/sessions/active", params={"alias": "ORA_PROD"}, headers=auth(token)).json()
    assert sessions["locks"][0]["sid"] == 10
    assert sessions["locks"][0]["children"][0]["sid"] == 11
    saved = client.put(
        "/api/agent-retention",
        params={"alias": "ORA_PROD"},
        headers=auth(token),
        json={
            "save_interval_sec": 30,
            "purge_interval_sec": 120,
            "policies": [{"data_kind": "sql_text", "keep_days": 9, "enabled": True}],
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["save_interval_sec"] == 30
    assert body["purge_interval_sec"] == 120
    assert next(item["keep_days"] for item in body["policies"] if item["data_kind"] == "sql_text") == 9
    server.should_exit = True
    thread.join(timeout=3)
    local.close()
    store.close()


def test_product_identity_and_legacy_names(tmp_path):
    store, client = build(tmp_path)
    health = client.get("/api/health").json()
    assert (health["title"], health["version"], health["display"]) == ("OKEDBMON", "1.0.0.0", "OKEDBMON V1.0.0.0")
    assert client.get("/api/dashboard", headers=auth(login(client))).json()["display"] == "OKEDBMON V1.0.0.0"
    store.close()

    legacy_props = {**load_properties(), "support.title": "OKEMON", "agent.token": "spacemon-agent", "db.repository.path": "data/okemon.sqlite"}
    Store(tmp_path / "old.sqlite", legacy_props, seed=True).close()
    migrated = Store(tmp_path / "old.sqlite", load_properties(), seed=True)
    assert migrated.setting("support.title") == "OKEDBMON"
    assert migrated.setting("db.repository.path") == "data/okedbmon.sqlite"
    assert migrated.agent_authorized("okedbmon-agent")
    migrated.close()


def test_settings_and_instance_registry(tmp_path):
    store, client = build(tmp_path)
    token = login(client)
    saved = client.put(
        "/api/settings",
        headers=auth(token),
        json={"values": {"threshold.cpu": "70", "agent.token": "next-token", "support.title": "OKEDBMON", "support.ver": "1.0.0.1"}},
    )
    assert saved.status_code == 200
    masked = next(item for item in saved.json()["settings"] if item["setting_key"] == "agent.token")
    assert masked["setting_value"] == "********"
    assert store.setting("threshold.cpu") == "70"
    assert store.setting("support.title") == "OKEDBMON"
    assert store.setting("support.ver") == "1.0.0.1"
    rejected = client.put(
        "/api/settings",
        headers=auth(token),
        json={"values": {"support.ver": "1.0.1"}},
    )
    assert rejected.status_code == 400
    assert store.agent_authorized("next-token")
    assert not store.agent_authorized("okedbmon-agent")

    created = client.post(
        "/api/instances",
        headers=auth(token),
        json={
            "agent_alias": "PG_STAGE",
            "product": "POSTGRESQL",
            "host_nm": "10.0.0.8",
            "port": 5432,
            "db_name": "stage",
            "username": "monitor",
            "group_nm": "검증",
            "collect_interval_sec": 10,
            "enabled": True,
            "description": "stage",
        },
    )
    assert created.status_code == 200
    duplicate = client.post(
        "/api/instances",
        headers=auth(token),
        json={
            "agent_alias": "PG_STAGE",
            "product": "POSTGRESQL",
            "host_nm": "10.0.0.8",
            "port": 5432,
        },
    )
    assert duplicate.status_code == 400
    store.close()


def test_simulator_covers_four_products():
    for product, alias in [("ORACLE", "ORA_PROD"), ("TIBERO", "TIB_ERP"), ("MARIADB", "MARIA_WEB"), ("POSTGRESQL", "PG_ANALYTICS")]:
        sim = Simulator({"agent_alias": alias, "product": product, "host": "db", "database": "demo"})
        first = sim.collect()
        second = sim.collect()
        assert first["product"] == product
        assert first["active_sessions"]
        assert first["session_history"]
        assert first["sql_texts"]
        assert all(row["status"] == "ACTIVE" for row in first["session_history"])
        assert second["collect_tm"] >= first["collect_tm"]
        assert make_collector({"agent_alias": alias, "product": product, "mode": "simulate", "host": "db"}).collect()["status"] == "ONLINE"


def test_host_metrics_from_proc(tmp_path):
    import agent.osmetrics as osmetrics

    osmetrics._PREVIOUS = None
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "stat").write_text("cpu  10 0 10 70 0 0 0 0\ncpu0 10 0 10 70 0 0 0 0\n", encoding="utf-8")
    (proc / "meminfo").write_text("MemTotal: 1000 kB\nMemAvailable: 400 kB\n", encoding="utf-8")
    assert read_host_metrics(proc)["cpu_usage"] is None
    (proc / "stat").write_text("cpu  30 0 30 80 0 0 0 0\n", encoding="utf-8")
    cpu = read_host_metrics(proc)["cpu_usage"]
    assert cpu == 80.0
    assert read_host_metrics(proc)["mem_usage"] == 60.0


def test_agent_config_is_one_instance():
    from agent.runtime import AgentConfigError, demo_targets, resolve_target

    config = json.loads(Path("config/agent.json").read_text(encoding="utf-8"))
    assert "targets" not in config
    target = resolve_target(config)
    assert target["agent_alias"] == "ORA_PROD"
    assert target["product"] == "ORACLE"
    assert resolve_target({"targets": [target]})["agent_alias"] == "ORA_PROD"
    try:
        resolve_target({"targets": [target, dict(target, agent_alias="OTHER")]})
    except AgentConfigError as exc:
        assert "인스턴스만" in str(exc)
    else:
        raise AssertionError("several targets must be rejected")

    demo = json.loads(Path("config/demo-agents.json").read_text(encoding="utf-8"))
    products = {item["product"] for item in demo_targets(demo)}
    assert products == {"ORACLE", "TIBERO", "MARIADB", "POSTGRESQL"}


def test_demo_targets_collect_in_parallel():
    import time

    from agent.demo import run_targets_once

    def collect(config, target):
        time.sleep(0.35 if target["agent_alias"] == "SLOW" else 0.05)
        return {"agent_alias": target["agent_alias"]}

    started = time.perf_counter()
    rows = run_targets_once(
        {},
        [{"agent_alias": "SLOW"}, {"agent_alias": "FAST"}, {"agent_alias": "FAST2"}],
        collect,
    )
    elapsed = time.perf_counter() - started
    assert [row["agent_alias"] for row in rows] == ["SLOW", "FAST", "FAST2"]
    assert elapsed < 0.55
