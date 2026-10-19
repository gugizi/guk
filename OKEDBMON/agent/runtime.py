"""One agent process collects one database instance and posts the result."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from agent.collectors import empty_error, make_collector
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


def serve_target(config: dict, target: dict) -> None:
    """Collect one instance on its own interval. The collector object stays alive so deltas accumulate."""
    interval = target_interval(config, target)
    prepared = dict(target)
    prepared["interval_sec"] = interval
    collector = make_collector(prepared)
    alias = prepared.get("agent_alias") or "?"
    url = config["collector_url"]
    token = config["token"]
    with httpx.Client() as client:
        while True:
            started = time.time()
            try:
                payload = collector.collect()
            except Exception as exc:
                payload = empty_error(prepared, str(exc))
            try:
                post_payload(client, url, token, payload)
                print(f"collected {alias}:{payload['status']}", flush=True)
            except Exception as exc:
                print(f"post failed {alias}: {exc}", flush=True)
            time.sleep(max(0, interval - (time.time() - started)))
