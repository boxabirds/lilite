"""Phase C: Interactive configuration — let user enable/disable discovered items.

Presents a rich terminal menu grouped by page and classification.
Sensible defaults: core content enabled, ads/trackers/analytics disabled.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table
from rich.tree import Tree

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
    console.print(f"Based on: {disc_file.name}\n")

    rules = []

    for page_data in discovery.get("pages", []):
        page_url = page_data["url"]
        console.print(f"\n[bold cyan]{page_url}[/bold cyan]")

        # Group UI components by classification
        ui_groups = {}
        for comp in page_data.get("ui_components", []):
            cls = comp.get("classification", "other")
            ui_groups.setdefault(cls, []).append(comp)

        # Group API calls by classification
        api_groups = {}
        for call in page_data.get("api_calls", []):
            cls = call.get("classification", "other")
            api_groups.setdefault(cls, []).append(call)

        # Display and collect decisions for UI components
        if ui_groups:
            console.print("\n  [bold]UI Components[/bold]")
            for cls, items in sorted(ui_groups.items()):
                console.print(f"\n  [yellow]{cls}[/yellow]")
                for item in items:
                    default_on = cls not in _BLOCK_BY_DEFAULT
                    desc = item.get("description", item.get("id", "unknown"))[:60]
                    marker = "[green]ON[/green]" if default_on else "[red]OFF[/red]"
                    console.print(f"    {marker} {item['id'][:30]:30s} — {desc}")

                # Ask for the group
                default_action = "allow" if cls not in _BLOCK_BY_DEFAULT else "block"
                toggle = Confirm.ask(
                    f"    Keep all [yellow]{cls}[/yellow] components?",
                    default=(default_action == "allow"),
                )
                action = "allow" if toggle else "hide"
                for item in items:
                    if action == "hide":
                        rules.append({
                            "id": item["id"],
                            "type": "ui_component",
                            "action": "hide",
                            "selector": item.get("selector", ""),
                            "scope": item.get("scope", f"url:{page_url}"),
                            "classification": cls,
                            "description": item.get("description", ""),
                        })
                    # allowed items don't need rules

        # Display and collect decisions for API calls
        if api_groups:
            console.print("\n  [bold]API / Network Calls[/bold]")
            for cls, items in sorted(api_groups.items()):
                console.print(f"\n  [yellow]{cls}[/yellow]")
                for item in items:
                    default_on = cls not in _BLOCK_BY_DEFAULT
                    desc = item.get("url_pattern", item.get("url", ""))[:60]
                    vendor = f" ({item['vendor']})" if item.get("vendor") else ""
                    marker = "[green]ON[/green]" if default_on else "[red]OFF[/red]"
                    console.print(f"    {marker} {desc}{vendor}")

                default_action = "allow" if cls not in _BLOCK_BY_DEFAULT else "block"
                toggle = Confirm.ask(
                    f"    Allow all [yellow]{cls}[/yellow] calls?",
                    default=(default_action == "allow"),
                )
                action = "allow" if toggle else "block"
                for item in items:
                    if action == "block":
                        rules.append({
                            "id": item.get("id", "unknown"),
                            "type": "api_call",
                            "action": "block",
                            "url_pattern": item.get("url_pattern", ""),
                            "scope": item.get("scope", ""),
                            "classification": cls,
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
