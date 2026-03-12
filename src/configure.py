"""Phase C: Interactive configuration — let user enable/disable discovered sections.

Presents a per-section checkbox menu grouped by page zone (top-nav,
left-sidebar, main-feed, right-sidebar, etc.).
Use arrow keys to navigate, space to toggle, enter to confirm.
Defaults come from Gemini's analysis (default_action: keep/hide).
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from InquirerPy import inquirer
from rich.console import Console

from . import config

log = logging.getLogger(__name__)
console = Console()

# Zone display order and labels
_ZONE_ORDER = [
    "top-nav", "left-sidebar", "main-feed",
    "right-sidebar", "messaging", "footer", "overlay", "other",
]

# Network categories that are essential — never offer these for blocking
_ESSENTIAL_NETWORK_CATEGORIES = frozenset({
    "core-data", "social", "messaging", "notifications",
    "authentication", "infrastructure", "media",
})

_ZONE_LABELS = {
    "top-nav": "Top Navigation",
    "left-sidebar": "Left Sidebar",
    "main-feed": "Main Feed",
    "right-sidebar": "Right Sidebar",
    "messaging": "Messaging",
    "footer": "Footer",
    "overlay": "Overlays",
    "other": "Other",
}

# Maximum label length for the configuration menu
_MAX_LABEL_LENGTH = 80


def configure(discovery_path: str | None = None) -> str:
    """Run interactive configuration. Returns path to config JSON."""
    if discovery_path:
        disc_file = Path(discovery_path)
    else:
        disc_file = _find_latest_discovery()

    if not disc_file or not disc_file.exists():
        raise FileNotFoundError("No discovery file found — run 'lilite discover' first")

    with open(disc_file) as f:
        discovery = json.load(f)

    console.print(f"\n[bold]LI Lite Configuration[/bold]")
    console.print(f"Based on: {disc_file.name}")
    console.print("Use arrow keys to navigate, space to toggle, enter to confirm.\n")

    rules = []

    for page_data in discovery.get("pages", []):
        page_url = page_data["url"]
        ui_components = page_data.get("ui_components", [])
        api_calls = page_data.get("api_calls", [])

        if not ui_components and not api_calls:
            continue

        # Build items for the menu
        all_items = []

        # UI sections grouped by zone
        for comp in ui_components:
            name = comp.get("name") or comp.get("description") or comp.get("id", "unknown")
            default_keep = comp.get("default_action", "keep") == "keep"
            zone = comp.get("zone", "other")

            all_items.append({
                "item": comp,
                "type": "ui_component",
                "zone": zone,
                "label": _truncate(name, _MAX_LABEL_LENGTH),
                "name": f"ui:{comp.get('id', 'unknown')}",
                "default_keep": default_keep,
            })

        # Network blocking disabled — only offering visual changes for now
        # TODO: re-enable when network classification is reliable
        # for call in api_calls:
        #     category = call.get("category", "other")
        #     if category in _ESSENTIAL_NETWORK_CATEGORIES:
        #         continue
        #     item_id = call.get("id", "unknown")
        #     call_name = call.get("name", call.get("url_pattern", "unknown"))
        #     default_keep = call.get("default_action", "keep") == "keep"
        #     zone_label = f"network:{category}"
        #     all_items.append({
        #         "item": call,
        #         "type": "api_call",
        #         "zone": zone_label,
        #         "label": _truncate(call_name, _MAX_LABEL_LENGTH),
        #         "name": f"api:{item_id}",
        #         "default_keep": default_keep,
        #     })

        if not all_items:
            continue

        # Build choices grouped by zone
        choices = []
        groups = {}
        for entry in all_items:
            groups.setdefault(entry["zone"], []).append(entry)

        # Sort zones in display order
        zone_order = _ZONE_ORDER + ["network"]
        sorted_zones = sorted(groups.keys(),
                              key=lambda z: zone_order.index(z) if z in zone_order else 99)

        for zone in sorted_zones:
            items = groups[zone]
            label = _ZONE_LABELS.get(zone, zone.replace("-", " ").title())
            choices.append({"name": f"── {label} ──", "value": None, "enabled": False})
            for entry in items:
                choices.append({
                    "name": f"  {entry['label']}",
                    "value": entry["name"],
                    "enabled": entry["default_keep"],
                })

        console.print(f"[bold cyan]{page_url}[/bold cyan]")
        kept = inquirer.checkbox(
            message="Select items to KEEP (unchecked = blocked/hidden):",
            choices=choices,
            cycle=True,
            instruction="(space=toggle, a=all, i=invert, enter=confirm)",
        ).execute()

        kept_set = set(kept) if kept else set()

        # Generate rules for items NOT kept
        for entry in all_items:
            if entry["name"] not in kept_set:
                item = entry["item"]
                if entry["type"] == "ui_component":
                    rules.append({
                        "id": item.get("id", "unknown"),
                        "type": "ui_component",
                        "action": "hide",
                        "xpath": item.get("xpath", ""),
                        "selector": item.get("selector"),
                        "scope": item.get("scope", f"url:{page_url}"),
                        "zone": entry["zone"],
                        "description": item.get("name") or item.get("description", ""),
                    })
                else:
                    rules.append({
                        "id": item.get("id", "unknown"),
                        "type": "api_call",
                        "action": "block",
                        "url_pattern": item.get("url_pattern", ""),
                        "scope": item.get("scope", ""),
                        "category": item.get("category", "other"),
                        "description": item.get("name") or item.get("url_pattern", ""),
                    })

    # Summary
    hide_count = sum(1 for r in rules if r["action"] == "hide")
    block_count = sum(1 for r in rules if r["action"] == "block")
    console.print(f"\n[bold green]Configuration complete:[/bold green] "
                  f"{hide_count} sections hidden, {block_count} network calls blocked")

    # Save
    datestamp = datetime.now().strftime("%Y%m%d-%H%M")
    output_path = config.CONFIG_DIR / f"{datestamp}-configuration.json"
    result = {
        "configured_at": datetime.now(timezone.utc).isoformat(),
        "based_on_discovery": disc_file.name,
        "rules": rules,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    console.print(f"Saved to {output_path}")
    return str(output_path)


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, adding ellipsis if needed."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def _find_latest_discovery() -> Path | None:
    """Find the most recent discovery JSON in the config directory."""
    files = sorted(config.CONFIG_DIR.glob("*-discovery.json"), reverse=True)
    return files[0] if files else None
