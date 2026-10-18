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

## Version scheme

[CalVer](https://calver.org/) `YYYY.MM.patch`, kept in sync in `manifest.json` and `pyproject.toml`.

## Releasing

1. Bump the version in `custom_components/toddle/manifest.json` and `pyproject.toml`, then commit.
2. `git tag vYYYY.MM.N && git push origin main --tags`
3. `gh release create vYYYY.MM.N --title "vYYYY.MM.N" --notes "…"`
