"""Build translations/en.json from strings.json.

Custom integrations don't get the `[%key:...]` references in strings.json
resolved by Home Assistant, so this script inlines them.
Run: python script/translations.py
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "toddle"

# The subset of Home Assistant's common strings used by this integration.
COMMON = {
    "common::config_flow::data::email": "Email",
    "common::config_flow::data::password": "Password",
    "common::config_flow::title::reauth": "Reauthenticate integration",
    "common::config_flow::error::cannot_connect": "Failed to connect",
    "common::config_flow::error::invalid_auth": "Invalid authentication",
    "common::config_flow::error::unknown": "Unexpected error",
    "common::config_flow::abort::already_configured_account": "Account is already configured",
    "common::config_flow::abort::reauth_successful": "Re-authentication was successful",
    "common::config_flow::abort::reconfigure_successful": "Re-configuration was successful",
}
KEY_RE = re.compile(r"\[%key:([^%]+)%\]")


def main() -> None:
    """Resolve references and write en.json."""
    strings = json.loads((ROOT / "strings.json").read_text())

    def lookup(key: str) -> str:
        if key in COMMON:
            return COMMON[key]
        parts = key.split("::")
        if parts[:2] != ["component", "toddle"]:
            raise KeyError(key)
        node: Any = strings
        for part in parts[2:]:
            node = node[part]
        return resolve(node)

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, str):
            return KEY_RE.sub(lambda m: lookup(m.group(1)), node)
        return node

    out = ROOT / "translations" / "en.json"
    out.write_text(json.dumps(resolve(strings), indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
