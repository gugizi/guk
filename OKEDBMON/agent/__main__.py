"""Agent entry point. One process collects the one instance on this database server."""

from agent.runtime import CONFIG, load_config, resolve_target, serve_target


def main() -> None:
    config = load_config(CONFIG)
    target = resolve_target(config)
    print(
        f"agent {target.get('agent_alias')} {target.get('product')} -> {config.get('collector_url')}",
        flush=True,
    )
    serve_target(config, target)


if __name__ == "__main__":
    main()
