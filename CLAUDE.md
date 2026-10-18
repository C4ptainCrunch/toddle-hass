# Toddle Home Assistant integration

Custom integration (`custom_components/toddle`) for the Toddle / kinderopvang.software parent API (Tactics bvba), targeting the Platinum quality scale. The API was reverse engineered in `../toddle` (see `API.md` there).

## Layout

- `api.py`: standalone async API client and models (no HA imports). Auth: email/password login → 15 min JWT + refresh token; refreshes proactively and retries once on 401.
- `coordinator.py`: one coordinator per account. It fetches children, attendance (today + 21 days) and journals (past 6 days) and removes stale child devices. It polls every 5 min during weekday daycare hours and every 30 min otherwise.
- `entity.py`: `ToddleChildEntity` (one device per child) and `async_setup_child_entities`, which adds entities for children that appear later.
- Platforms: `sensor`, `binary_sensor`, `calendar` (attendance + journal calendars; both query the API for the requested range), `event` (new journal entries), `image` (QR code).
- `services.py`: response-only actions `get_journal` and `get_attendance`.

## Gotchas

- **Time encoding**: the API *returns* daycare wall-clock time encoded as UTC epochs; decode in UTC, then attach `Europe/Brussels` (`DAYCARE_TZ`). But `daterange[gte|lte]` *filters* are matched against real instants (true local midnight per day), so send real Brussels-time bounds like the official app does. Getting this wrong shifts every query by one day (verified against the live API, Oct 2026). `../toddle`'s `DaycareTime.swift` has this bug.
- Raw `state` values seen on real data: `EXPECTED` (future) → `OUT` (attended) → `INVOICED` (billed), plus `ABSENT` and `UNPLANNED` (weekends). Missed days often stay `INVOICED` with no presences and no absence reason. Status is therefore derived from presences/schedules at a point in time (`SubscriptionDay.status_at(now)`): a planned day without check-in becomes `absent` once its scheduled pick-up has passed.
- The API **ignores `page`/`limit`** and returns at most 500 items (with the real `total`). `_ranged` splits the date range until each part fits; never add page-based pagination back.
- Refresh tokens rotate and are single-use. Bad tokens get **400** `Invalid 'Authorization' Header` (treated as auth failure), unknown accounts get 404, unknown tenants 400 `Connection named "x" does not exist` (`ToddleInvalidTenantError`). The tenant header is only needed for login.
- HA 2026.10 uses `probatio` instead of `voluptuous`. Devices now belong to a single config entry (`device.config_entry_id`, `async_get_device_by_identifier`, `async_remove_device`).
- In tests, coordinator refreshes run as background tasks: use `await hass.async_block_till_done(wait_background_tasks=True)` after `async_fire_time_changed`.
- `translations/en.json` is generated from `strings.json` by `script/translations.py`. Keep `nl.json` and `fr.json` in sync by hand.

## Commands

```bash
.venv/bin/pytest          # with coverage, fails under 95%
.venv/bin/mypy            # strict
.venv/bin/ruff check . && .venv/bin/ruff format .
docker compose up -d      # dev HA at http://localhost:8123 (user dev / dev)
```
