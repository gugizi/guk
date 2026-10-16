"""Send active sessions, session history, and SQL text to the collector."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from agent.collectors import empty_error, make_collector
from collector.store import ROOT

CONFIG = ROOT / "config" / "agent.json"


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG).read_text(encoding="utf-8"))


def post_payload(client: httpx.Client, url: str, token: str, payload: dict) -> None:
    response = client.post(
        url.rstrip("/") + "/api/ingest",
        json=payload,
        headers={"X-Agent-Token": token},
        timeout=20,
    )
    response.raise_for_status()


def run_once(config: dict | None = None) -> list[dict]:
    config = config or load_config()
    results = []
    with httpx.Client() as client:
        for target in config["targets"]:
            target = dict(target)
            target["interval_sec"] = config.get("interval_sec", 5)
            collector = make_collector(target)
            try:
                payload = collector.collect()
            except Exception as exc:
                payload = empty_error(target, str(exc))
            post_payload(client, config["collector_url"], config["token"], payload)
            results.append(
                {
                    "agent_alias": payload["agent_alias"],
                    "status": payload["status"],
                    "message": payload.get("message") or "",
                }
            )
    return results


def main() -> None:
    config = load_config()
    interval = max(2, int(config.get("interval_sec", 5)))
    while True:
        started = time.time()
        try:
            results = run_once(config)
            print("collected", ", ".join(f"{row['agent_alias']}:{row['status']}" for row in results), flush=True)
        except Exception as exc:
            print("agent error", exc, flush=True)
        elapsed = time.time() - started
        time.sleep(max(0, interval - elapsed))


if __name__ == "__main__":
    main()
