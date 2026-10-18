# Contributing

This is a personal project made for my own use. It is not supported in any way: no issues, no PRs, no guarantee it works. Use at your own risk.

## Development

### Tests, typing and lint

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv pytest-homeassistant-custom-component mypy ruff
.venv/bin/pytest            # tests + coverage (must stay ≥ 95%)
.venv/bin/mypy              # strict typing
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Update snapshots after an intended change with `.venv/bin/pytest --snapshot-update`.

### Translations

`custom_components/toddle/strings.json` is the source of truth. After editing it, regenerate the English translation with `python3 script/translations.py`, then update `translations/nl.json` and `translations/fr.json` by hand.

### Local Home Assistant

```bash
docker compose up -d
```

Open http://localhost:8123. The integration is mounted read-only into the container. Restart it after a code change with `docker compose restart`. Debug logging for `custom_components.toddle` is enabled in `config/configuration.yaml`.

### Demo instance

To try the UI or take screenshots without a real account, start the demo profile:

```bash
docker compose --profile demo up -d demo
```

Open http://localhost:8124 and add the Toddle integration with any email, password and tenant. The `toddle_demo` component in `demo/` replaces the API client with the data from `tests/fixtures`, moved so that the fixtures' "today" is the current day. Check-ins and journal entries later than the current time are hidden.

The container's clock is faked with libfaketime, starting on a Tuesday afternoon while the child is at daycare. Pick another moment with `DEMO_TIME="2026-10-20 17:00:00" docker compose --profile demo up -d demo`. Your browser still uses the real time, so relative times ("5 hours ago") will be off unless you fake its clock too, as the screenshot script does with Playwright's `page.clock`.

## Version scheme

[CalVer](https://calver.org/) `YYYY.MM.patch`, kept in sync in `manifest.json` and `pyproject.toml`.

## Releasing

1. Bump the version in `custom_components/toddle/manifest.json` and `pyproject.toml`, then commit.
2. `git tag vYYYY.MM.N && git push origin main --tags`

Pushing the tag runs the release workflow, which checks that the tag matches `manifest.json` and creates the GitHub release with generated notes.
