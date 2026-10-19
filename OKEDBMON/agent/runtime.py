"""One agent process collects one database instance and posts the result."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from agent.collectors import empty_error, make_collector
from agent.localstore import AgentStore
from agent.query import start_purge_loop, start_query_server
from collector.store import ROOT

CONFIG = ROOT / "config" / "agent.json"
DEMO_CONFIG = ROOT / "config" / "demo-agents.json"


class AgentConfigError(ValueError):
    """The agent config does not describe exactly one database instance."""


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG).read_text(encoding="utf-8"))


def target_interval(config: dict, target: dict) -> int:
    raw = target.get("interval_sec", config.get("interval_sec", 5))
    return max(2, int(raw))


def resolve_target(config: dict) -> dict:
    """Return the single instance this agent process is responsible for."""
    has_target = "target" in config
    has_targets = "targets" in config
    if has_target and has_targets:
        raise AgentConfigError("target 과 targets 를 함께 둘 수 없습니다. DB 서버에는 target 하나만 둡니다.")
    if has_target:
        target = config["target"]
        if not isinstance(target, dict):
            raise AgentConfigError("target 은 인스턴스 하나여야 합니다.")
        return dict(target)
    targets = config.get("targets")
    if isinstance(targets, list) and len(targets) == 1 and isinstance(targets[0], dict):
        return dict(targets[0])
    if isinstance(targets, list) and len(targets) > 1:
        raise AgentConfigError(
            "에이전트 프로세스 하나는 이 DB 서버의 인스턴스만 수집합니다. "
            "대상마다 에이전트를 따로 설치하세요. "
            "한 PC에서 여러 대상을 흉내 내는 데모는 python -m agent.demo 입니다."
        )
    raise AgentConfigError("config/agent.json 에 target 이 없습니다.")


def demo_targets(config: dict) -> list[dict]:
    targets = config.get("targets")
    if not isinstance(targets, list) or not targets or not all(isinstance(item, dict) for item in targets):
        raise AgentConfigError("데모 설정에는 targets 목록이 필요합니다.")
    return [dict(item) for item in targets]


def post_payload(client: httpx.Client, url: str, token: str, payload: dict) -> None:
    response = client.post(
        url.rstrip("/") + "/api/ingest",
        json=payload,
        headers={"X-Agent-Token": token},
        timeout=20,
    )
    response.raise_for_status()


def listen_of(config: dict, target: dict) -> tuple[str, int, str]:
    host = str(target.get("listen_host") or config.get("listen_host") or "0.0.0.0")
    port = int(target.get("listen_port") or config.get("listen_port") or 9101)
    advertise = str(target.get("advertise_host") or config.get("advertise_host") or "127.0.0.1")
    return host, port, f"http://{advertise}:{port}"


def performance_body(payload: dict, agent_url: str) -> dict:
    """Performance goes to the collector. Sessions and SQL text stay on this agent."""
    return {
        "agent_alias": payload.get("agent_alias"),
        "product": payload.get("product") or "",
        "collect_tm": payload.get("collect_tm"),
        "version": payload.get("version") or "",
        "status": payload.get("status") or "ONLINE",
        "message": payload.get("message") or "",
        "performance": payload.get("performance"),
        "agent_url": agent_url,
    }


def serve_target(config: dict, target: dict) -> None:
    """Collect one instance on its own interval. The collector object stays alive so deltas accumulate."""
    interval = target_interval(config, target)
    prepared = dict(target)
    prepared["interval_sec"] = interval
    collector = make_collector(prepared)
    alias = prepared.get("agent_alias") or "?"
    url = config["collector_url"]
    token = config["token"]
    bind_host, bind_port, agent_url = listen_of(config, prepared)
    store_path = Path(prepared["store_path"]) if prepared.get("store_path") else ROOT / "data" / "agents" / f"{alias}.sqlite"
    local = AgentStore(
        store_path,
        alias,
        save_interval_sec=int(prepared.get("save_interval_sec") or interval),
        purge_interval_sec=int(prepared.get("purge_interval_sec") or config.get("purge_interval_sec") or 60),
    )
    start_query_server(local, token, bind_host, bind_port)
    start_purge_loop(local)
    print(f"agent store {alias}: {store_path} query {agent_url}", flush=True)
    last_save = 0.0
    with httpx.Client() as client:
        while True:
            started = time.time()
            try:
                payload = collector.collect()
            except Exception as exc:
                payload = empty_error(prepared, str(exc))
            try:
                post_payload(client, url, token, performance_body(payload, agent_url))
                print(f"collected {alias}:{payload['status']}", flush=True)
            except Exception as exc:
                print(f"post failed {alias}: {exc}", flush=True)
            if payload.get("status") == "ONLINE" and (time.time() - last_save) >= local.save_interval():
                try:
                    local.save_sample(payload)
                    last_save = time.time()
                except Exception as exc:
                    print(f"local save failed {alias}: {exc}", flush=True)
            time.sleep(max(0, interval - (time.time() - started)))
