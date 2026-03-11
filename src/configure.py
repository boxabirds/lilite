"""Phase C: Interactive configuration — let user enable/disable discovered items.

Presents a per-item checkbox menu grouped by page and classification.
Use arrow keys to navigate, space to toggle, enter to confirm.
Sensible defaults: core content enabled; ads/trackers/analytics disabled.
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

# Classifications that default to BLOCKED
_BLOCK_BY_DEFAULT = {
    "tracking-pixel", "analytics", "ad-network",
    "promoted-content",
}


def configure(discovery_path: str | None = None) -> str:
    """Run interactive configuration. Returns path to config JSON."""
    # Find discovery file
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

        # Collect all items for this page with metadata
        ui_items = []
        for comp in page_data.get("ui_components", []):
            cls = comp.get("classification", "other")
            item_id = comp.get("id", "unknown")
            desc = comp.get("description", item_id)[:60]
            ui_items.append({
                "item": comp,
                "type": "ui_component",
                "classification": cls,
                "label": f"{desc}",
                "name": f"ui:{item_id}",
                "default_keep": cls not in _BLOCK_BY_DEFAULT,
            })

        api_items = []
        for call in page_data.get("api_calls", []):
            cls = call.get("classification", "other")
            item_id = call.get("id", "unknown")
            pattern = call.get("url_pattern", call.get("url", ""))[:60]
            vendor = f" ({call['vendor']})" if call.get("vendor") else ""
            api_items.append({
                "item": call,
                "type": "api_call",
                "classification": cls,
                "label": f"{pattern}{vendor}",
                "name": f"api:{item_id}",
                "default_keep": cls not in _BLOCK_BY_DEFAULT,
            })

        all_items = ui_items + api_items
        if not all_items:
            continue

        # Build choices grouped by classification
        choices = []
        # Group by classification, sorted
        groups = {}
        for entry in all_items:
            groups.setdefault(entry["classification"], []).append(entry)

        for cls in sorted(groups.keys()):
            items = groups[cls]
            blocked = cls in _BLOCK_BY_DEFAULT
            tag = "BLOCK" if blocked else "KEEP"
            choices.append({"name": f"── {cls} (default: {tag}) ──", "value": None, "enabled": False})
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
                        "selector": item.get("selector", ""),
                        "scope": item.get("scope", f"url:{page_url}"),
                        "classification": entry["classification"],
                        "description": item.get("description", ""),
                    })
                else:
                    rules.append({
                        "id": item.get("id", "unknown"),
                        "type": "api_call",
                        "action": "block",
                        "url_pattern": item.get("url_pattern", ""),
                        "scope": item.get("scope", ""),
                        "classification": entry["classification"],
                        "vendor": item.get("vendor"),
                        "description": item.get("url_pattern", ""),
                    })

    # Summary
    block_count = sum(1 for r in rules if r["action"] in ("block", "hide"))
    console.print(f"\n[bold green]Configuration complete:[/bold green] "
                  f"{block_count} items will be blocked/hidden")

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


def _find_latest_discovery() -> Path | None:
    """Find the most recent discovery JSON in the config directory."""
    files = sorted(config.CONFIG_DIR.glob("*-discovery.json"), reverse=True)
    return files[0] if files else None
