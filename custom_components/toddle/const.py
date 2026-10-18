"""Constants for the Toddle integration."""

from __future__ import annotations

from datetime import time, timedelta
import logging
from typing import Final

DOMAIN: Final = "toddle"
LOGGER = logging.getLogger(__package__)

CONF_TENANT: Final = "tenant"
CONF_DEVICE_ID: Final = "device_id"

DEFAULT_TENANT: Final = "brussel"
DEVICE_NAME: Final = "Home Assistant"

# Poll often while children are likely to be dropped off or picked up and
# journal entries are being written; back off in the evening and at weekends.
UPDATE_INTERVAL_ACTIVE: Final = timedelta(minutes=5)
UPDATE_INTERVAL_IDLE: Final = timedelta(minutes=30)
ACTIVE_HOURS_START: Final = time(6, 30)
ACTIVE_HOURS_END: Final = time(19, 0)

# How far back journal entries are kept for the "latest" sensors, and how far
# ahead attendance days are fetched to find the next daycare day.
JOURNAL_LOOKBACK_DAYS: Final = 6
ATTENDANCE_LOOKAHEAD_DAYS: Final = 21

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_CHILD: Final = "child"
ATTR_START_DATE: Final = "start_date"
ATTR_END_DATE: Final = "end_date"
MAX_SERVICE_RANGE_DAYS: Final = 93
