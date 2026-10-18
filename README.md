<img src="custom_components/toddle/brand/icon.png" alt="Toddle" width="96" align="right">

# Toddle for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Release](https://img.shields.io/github/v/release/C4ptainCrunch/toddle-hass)](https://github.com/C4ptainCrunch/toddle-hass/releases)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-18BCF2?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![CI](https://github.com/C4ptainCrunch/toddle-hass/actions/workflows/ci.yml/badge.svg)](https://github.com/C4ptainCrunch/toddle-hass/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/C4ptainCrunch/toddle-hass)](LICENSE)

A Home Assistant integration for [**Toddle**](https://www.toddle.be/), the childcare platform.

> [!WARNING]
> **This project is vibe coded.** Almost all of the code, tests and documentation were written by [Claude Code](https://claude.com/claude-code) from my prompts. I've used it with my own account, but I haven't reviewed every line. It uses an unofficial, reverse-engineered API and is not affiliated with or endorsed by Tactics or Toddle. Use it at your own risk.

It shows whether your child is at daycare, when they were dropped off and picked up, and what the staff wrote in the journal: meals, naps and messages. You can use these to build dashboards and notifications.

## Requirements

- Home Assistant 2026.10 or newer.
- A *Toddle for Parents* account at a daycare that uses kinderopvang.software (Belgium).

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=C4ptainCrunch&repository=toddle-hass&category=integration)

Or add it by hand:

1. In HACS, open the menu (⋮) in the top right → **Custom repositories**.
2. Add `https://github.com/C4ptainCrunch/toddle-hass` with type **Integration**.
3. Search for **Toddle**, open it and select **Download**.
4. Restart Home Assistant.

HACS will notify you of new [releases](https://github.com/C4ptainCrunch/toddle-hass/releases).


## Configuration

[![Open your Home Assistant instance and start setting up Toddle.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=toddle)

Or go to **Settings → Devices & services → Add integration → Toddle**.

| Parameter | Description |
|-----------|-------------|
| Email | The email address of your Toddle parent account (the one you use in the *Toddle for Parents* app). |
| Password | The password of that account. |
| Tenant | The organisation running your daycare on kinderopvang.software. |

Each parent account can be added once. If your password changes, Home Assistant asks you to re-authenticate. To change the email, password or tenant, use **Reconfigure** on the integration entry. The integration has no other options.

## What you get

Each child linked to your account becomes a device with the following entities:

| Entity | Type | Description |
|--------|------|-------------|
| At daycare | Binary sensor (presence) | On while the child is checked in. |
| Status | Sensor (enum) | `expected`, `present` (at daycare), `picked_up`, `absent` or `no_daycare`. A planned day without check-in turns `absent` once the scheduled pick-up time has passed. |
| Check-in / Check-out | Sensor (timestamp) | Today's actual drop-off and pick-up time. |
| Scheduled drop-off / pick-up | Sensor (timestamp) | Today's contracted hours. |
| Time at daycare | Sensor (duration) | Time spent at daycare today, counting up while present. |
| Next daycare day | Sensor (date) | The next planned (non-absent) day. |
| Latest journal entry | Sensor | Most recent journal message of the past week; the full text, type and time are attributes. |
| Last meal / Last nap | Sensor | Most recent nutrition and sleep reports. |
| Journal entries today | Sensor | Number of journal entries written today. |
| Attendance | Calendar | Actual presence, planned days and absences. |
| Journal | Calendar | Every journal entry (meals, naps, messages) at the time it happened, as far back as Toddle keeps them. |
| Journal | Event | Fires for every new journal entry, with types `general`, `nutrition`, `sleep`, `bowel_movement`, `activity`, `health`, `other`. |
| Remark | Sensor (disabled by default) | Today's remark or absence reason. |
| Group, Daycare | Diagnostic sensors | The child's group (*leefgroep*) and daycare. |
| Date of birth | Diagnostic sensor (disabled by default) | |
| QR code | Image (diagnostic, disabled by default) | The child's check-in QR code. |


### Actions

Both actions return data (use `response_variable`):

These actions require an administrator when called by a user. Automations without a user context can also call them.

- `toddle.get_journal`: journal entries for a child between `start_date` and `end_date` (both optional, default today).
- `toddle.get_attendance`: planned and actual attendance per day for the same kind of range.

The range is limited to 93 days.

```yaml
action: toddle.get_journal
data:
  child: <device id of the child>
  start_date: "2026-03-30"
  end_date: "2026-03-31"
response_variable: journal
```

## Examples

**Notify when the daycare writes something:**

```yaml
automation:
  - alias: Toddle journal notification
    triggers:
      - trigger: state
        entity_id: event.emma_journal
    conditions:
      - condition: template
        value_template: "{{ trigger.from_state.state not in ['unavailable', 'unknown'] }}"
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "Emma — {{ trigger.to_state.attributes.event_type }}"
          message: "{{ trigger.to_state.attributes.message }}"
```

**Notify when your child has been picked up:**

```yaml
automation:
  - alias: Emma picked up
    triggers:
      - trigger: state
        entity_id: binary_sensor.emma_at_daycare
        from: "on"
        to: "off"
    actions:
      - action: notify.family
        data:
          message: "Emma left daycare at {{ states('sensor.emma_check_out') | as_timestamp | timestamp_custom('%H:%M') }}"
```

Other ideas: remind yourself if the child is still `expected` after the usual drop-off time, show the last meal and nap on a wall tablet, or count hours at daycare per week with a utility meter.

## How data is updated

The integration polls the Toddle cloud API every **5 minutes** on weekdays between 06:30 and 19:00 (Brussels time), and every **30 minutes** at other times. Each poll fetches the children on the account, their attendance for the next three weeks, and their journal entries for the past week. The calendar fetches whatever range you open. Children added to or removed from the account show up or disappear automatically.

## Known limitations

- The Toddle API is not public. This integration uses the same API as the official app, so it may break if Tactics changes it.
- Journal events are only fired for entries that appear while Home Assistant is running. Entries written while it was offline update the sensors but don't fire events.
- Check-in and check-out times have minute resolution and depend on staff registering them. A child can show as `expected` even though they have arrived.
- Journal messages are shown as written by the staff (usually Dutch). They are not translated.
- Only read access is supported.

## Troubleshooting

- **Invalid authentication**: check that you can log in with the same email and password in the *Toddle for Parents* app. Also check the tenant.
- **Entities unavailable**: the Toddle API could not be reached. The integration retries automatically. Check the logs for details.
- **Debug logging**: add the following to `configuration.yaml`, or use **Enable debug logging** on the integration page:

  ```yaml
  logger:
    logs:
      custom_components.toddle: debug
  ```

- **Diagnostics**: on the integration page, use **Download diagnostics**. Names, messages and credentials are redacted.

## Removal

1. Go to **Settings → Devices & services → Toddle**.
2. Open the menu (⋮) on the entry and select **Delete**.
3. If installed through HACS, remove the repository in HACS and restart Home Assistant.

