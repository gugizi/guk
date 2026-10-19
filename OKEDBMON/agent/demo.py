"""Demo-only runner. Each configured instance is collected by its own thread.

Production does not use this. Install python -m agent on each database server
with a config that contains one target.
"""

from __future__ import annotations

import threading
import time

from agent.runtime import DEMO_CONFIG, demo_targets, load_config, serve_target


def run_targets_once(config: dict, targets: list[dict], collect) -> list:
    """Run collect for every target at the same time. One target cannot delay another."""
    results: list = [None] * len(targets)
    errors: list[BaseException] = []

    def work(index: int, target: dict) -> None:
        try:
            results[index] = collect(config, target)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(index, target)) for index, target in enumerate(targets)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return results


def main() -> None:
    config = load_config(DEMO_CONFIG)
    targets = demo_targets(config)
    names = ", ".join(f"{item.get('agent_alias')}:{item.get('product')}" for item in targets)
    print(f"demo agents ({len(targets)} independent collectors): {names}", flush=True)
    threads = [
        threading.Thread(target=serve_target, args=(config, target), name=str(target.get("agent_alias")), daemon=True)
        for target in targets
    ]
    for thread in threads:
        thread.start()
    try:
        while any(thread.is_alive() for thread in threads):
            time.sleep(1)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
