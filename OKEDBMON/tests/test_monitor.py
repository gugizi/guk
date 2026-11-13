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
    assert stored == 2
    sessions = client.get("/api/sessions/active", params={"alias": "ORA_PROD"}, headers=auth(token))
    assert sessions.status_code == 200
    body = sessions.json()
    assert body["locks"][0]["sid"] == 10
    assert body["locks"][0]["children"][0]["sid"] == 11
    sql = client.get("/api/sql", params={"alias": "ORA_PROD", "q": "dual"}, headers=auth(token)).json()
    assert sql["sql"][0]["sql_text"].startswith("SELECT 1")
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
            {"data_kind": "active_session", "keep_days": 3, "enabled": True},
            {"data_kind": "session_history", "keep_days": 3, "enabled": True},
            {"data_kind": "sql_text", "keep_days": 3, "enabled": True},
            {"data_kind": "sql_stat", "keep_days": 3, "enabled": True},
            {"data_kind": "event", "keep_days": 30, "enabled": False},
        ]},
    )
    summary = client.post("/api/retention/run", headers=auth(token)).json()["summary"]
    deleted = {item["data_kind"]: item["deleted_rows"] for item in summary}
    assert deleted["performance"] == 1
    assert deleted["event"] == 0
    assert deleted["sql_text"] == 1
    assert store.conn.execute("SELECT COUNT(*) AS c FROM sql_text").fetchone()["c"] == 1
    kinds = {item["data_kind"] for item in client.get("/api/retention", headers=auth(token)).json()["policies"]}
    assert kinds == {"performance", "active_session", "session_history", "sql_stat", "sql_text", "event"}
    store.close()


def test_collector_keeps_sessions_after_ingest(tmp_path):
    store, client = build(tmp_path)
    token = login(client)
    fresh = datetime.now()
    client.post(
        "/api/ingest",
        json=sample_payload(moment=fresh, sql="SELECT fresh_row FROM dual", sql_key="new"),
        headers={"X-Agent-Token": "okedbmon-agent"},
    )
    assert store.current_sessions("ORA_PROD")[0]["agent_collect_tm"] == now_text(fresh)
    assert store.sql_catalog("ORA_PROD", "fresh")[0]["sql_text"].startswith("SELECT fresh")
    report = client.get("/api/report", params={"alias": "ORA_PROD"}, headers=auth(token)).json()
    assert report["top_sql"][0]["sql_id"] == "new"
    store.close()


def test_point_in_time_session_and_sql_detail(tmp_path):
    store, client = build(tmp_path)
    token = login(client)
    older = datetime.now() - timedelta(minutes=30)
    fresh = datetime.now()
    old_body = sample_payload(moment=older, sql="SELECT old_row FROM dual", sql_key="old")
    old_body["session_history"][0]["sql_id"] = "old"
    old_body["session_history"][0]["wait_class"] = "User I/O"
    client.post("/api/ingest", json=old_body, headers={"X-Agent-Token": "okedbmon-agent"})
    client.post(
        "/api/ingest",
        json=sample_payload(moment=fresh, sql="SELECT fresh_row FROM dual", sql_key="new"),
        headers={"X-Agent-Token": "okedbmon-agent"},
    )
    times = client.get("/api/sessions/times", params={"alias": "ORA_PROD"}, headers=auth(token)).json()["times"]
    assert times[0] == now_text(fresh)
    assert now_text(older) in times
    past = client.get(
        "/api/sessions/active",
        params={"alias": "ORA_PROD", "at": now_text(older)},
        headers=auth(token),
    ).json()
    assert past["collect_tm"] == now_text(older)
    assert any(row["sql_id"] == "old" for row in past["sessions"])
    series = client.get("/api/sessions/series", params={"alias": "ORA_PROD"}, headers=auth(token)).json()["points"]
    assert [row["collect_tm"] for row in series] == [now_text(older), now_text(fresh)]
    assert series[0]["active_sessions"] == 2
    detail = client.get(
        "/api/sql/detail",
        params={"alias": "ORA_PROD", "sql_id": "old"},
        headers=auth(token),
    ).json()
    assert detail["sql"]["sql_text"].startswith("SELECT old_row")
    assert detail["stats"]["executions"] == 4
    assert detail["trace"][0]["wait_class"] == "User I/O"
    assert detail["trace"][0]["sid"] == 11
    assert client.get("/api/sql/detail", params={"alias": "ORA_PROD", "sql_id": "missing"}, headers=auth(token)).status_code == 404
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
    from agent.runtime import AgentConfigError, resolve_target

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


def test_login_token_stays_visible_while_ingest_runs(tmp_path):
    import threading

    store, client = build(tmp_path)
    token = login(client)
    stop = threading.Event()
    errors = []

    def writer():
        while not stop.is_set():
            store.ingest(sample_payload())

    def reader():
        for _ in range(40):
            if store.user_for_token(token) is None:
                errors.append("missing")
            response = client.get("/api/dashboard", headers=auth(token))
            if response.status_code != 200:
                errors.append(str(response.status_code))

    threads = [threading.Thread(target=writer)]
    threads.extend(threading.Thread(target=reader) for _ in range(3))
    for thread in threads:
        thread.start()
    for thread in threads[1:]:
        thread.join()
    stop.set()
    threads[0].join()
    store.close()
    assert errors == []
