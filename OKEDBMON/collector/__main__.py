"""Run the collection server."""

from __future__ import annotations

import uvicorn

from collector.server import build_demo_history, create_app
from collector.store import load_properties


def main() -> None:
    props = load_properties()
    app = create_app()
    build_demo_history(app.state.store)
    host = app.state.store.setting("collector.host", props.get("collector.host", "0.0.0.0"))
    port = int(app.state.store.setting("collector.port", props.get("collector.port", "8080")))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
