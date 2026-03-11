# LI Lite — Agent Handover

## What this project is

LI Lite gives users a "lite" LinkedIn by discovering every UI component and network call on their LinkedIn pages, letting them choose what to keep, and building a Chrome extension that hides/blocks the rest. Four phases: auth, discover, configure, build.

Full spec: `docs/baseline-spec.md`

## Current state: scaffold complete, not yet tested against real LinkedIn

All four phases have code. The build phase has 3 passing unit tests. The auth, discovery, and configure phases have no tests yet — they depend on a real browser session which hasn't happened.

```
uv run pytest tests/ -v   # 3 tests, all pass
```

## File map

```
src/
├── __init__.py          # empty
├── __main__.py          # CLI: auth | discover | configure | build | run
├── config.py            # paths, env vars, LinkedIn URLs
├── auth.py              # Phase A: browser login, cookie save/load/validate
├── discovery.py         # Phase B: network interception + DOM walking
├── configure.py         # Phase C: rich terminal menu
└── build.py             # Phase D: Chrome extension generator

scripts/refresh_auth/
└── refresh_linkedin_auth.py   # standalone Mac-side auth (no src imports)

tests/
├── __init__.py
└── test_build.py        # 3 tests: manifest, no-DNR case, PNG validity

config/linkedin.com/     # output dir (gitignored), empty until first run
data/auth/               # cookies + Chrome profile (gitignored)
docs/
├── baseline-spec.md     # full spec
└── handover.md          # this file
```

## How to run

Requires a display (Mac, or Ubuntu with X11/Wayland). Auth and discovery open a real Chrome window.

```bash
# Step-by-step
uv run python -m lilite auth        # opens Chrome, you log in, cookies saved
uv run python -m lilite discover    # intercepts network + walks DOM
uv run python -m lilite configure   # terminal menu, pick what to block
uv run python -m lilite build       # generates Chrome extension

# Or all at once
uv run python -m lilite run
```

Mac path: `/Volumes/sambashare/expts/lilite/`
Ubuntu path: `/home/julian/sambashare/expts/lilite/`

## Patterns reused from x-bookmark-to-substack

The sibling project at `../x-bookmark-to-substack` is the source of all browser automation patterns. Key parallels:

| Pattern | Source file | Lilite file |
|---|---|---|
| Patchright persistent context | `src/substack.py:58-65` | `src/auth.py:31-37` |
| Cookie save/load JSON | `src/substack.py:522-538` | `src/auth.py:54-64, 105-114` |
| Auth validation (login redirect check) | `src/auth.py:43-71` | `src/auth.py:67-90` |
| Request/response interception | `src/bookmarks.py` (discover_query_id) | `src/discovery.py:94-117` |
| Mac-side refresh script | `scripts/refresh_auth/refresh_substack_auth.py` | `scripts/refresh_auth/refresh_linkedin_auth.py` |
| Config module (PROJECT_ROOT, env, paths) | `src/config.py` | `src/config.py` |
| pyproject.toml (hatchling, uv) | `pyproject.toml` | `pyproject.toml` |

## What works (tested)

- **Build phase** (`src/build.py`): Generates a valid Manifest V3 Chrome extension from a configuration JSON. Tested:
  - `manifest.json` structure (MV3, content_scripts, declarativeNetRequest)
  - CSS hide rules with `display: none !important`
  - `content.js` MutationObserver with configured selectors
  - `rules.json` declarativeNetRequest block rules
  - Omits `declarativeNetRequest` permission when no block rules exist
  - Generates valid PNG icons (LinkedIn blue, correct PNG headers)

## What exists but is untested (needs a real browser session)

### Phase A: Auth (`src/auth.py`)

- `authenticate()` — opens Chrome, user logs in, saves cookies. Straightforward port of the Substack refresh script. Likely works but needs validation that:
  - LinkedIn doesn't block Patchright/Playwright user agents
  - Cookie capture includes `li_at` (the critical session cookie)
  - `validate_session()` selectors (`[role="main"]`, `#global-nav`) actually exist on current LinkedIn

### Phase B: Discovery (`src/discovery.py`)

This is the most complex and least proven phase. Specific concerns:

1. **DOM selectors are speculative.** The `_discover_ui_components` JS uses `[data-test-id]`, `[data-control-name]`, `[data-resource-context]` — these are based on LinkedIn's historical patterns but may have changed. The first real run will reveal what attributes LinkedIn actually uses today.

2. **`_buildSelector()` fallback is fragile.** When no `data-test-id` or `id` exists, it falls back to `tag.className` — LinkedIn uses CSS modules with hashed class names (e.g., `.feed-shared-update-v2--minimal-padding`) that change across deploys. These selectors would break when LinkedIn deploys.

3. **Classification heuristics are educated guesses.** `_classify_ui_component()` and `_classify_network_call()` use keyword matching (`"ad"`, `"sponsor"`, `"promote"` in IDs/labels). These need calibration against actual discovery output.

4. **`_url_to_pattern()` may over-generalize.** It replaces numeric path segments and hex strings with `*`. LinkedIn URLs like `/in/username/` or `/company/name/` have string path segments that won't be caught by numeric regex.

5. **Nav link following** (`_extract_nav_links`) looks for `#global-nav` or `nav[role="navigation"]` — may need adjustment based on actual LinkedIn DOM.

6. **`networkidle` may not be sufficient.** LinkedIn loads content via infinite scroll and lazy loading. The 5s idle wait (`DISCOVERY_IDLE_WAIT_MS`) might miss deferred API calls. Consider scrolling down to trigger more loads.

### Phase C: Configure (`src/configure.py`)

- Groups decisions by classification, prompts per-group (not per-item). This is a deliberate simplification — the spec shows per-item toggles but the implementation asks "Keep all [navigation] components?" to avoid a 50-question survey.
- The `_BLOCK_BY_DEFAULT` set determines defaults. May need tuning after seeing real discovery output.

## What's missing entirely

### Tests

- **`test_auth.py`** — Mock Patchright context, test cookie save/load round-trip, test `validate_session()` with mocked page URLs
- **`test_discovery.py`** — Test classification functions (`_classify_network_call`, `_classify_ui_component`) with fixture data, test `_url_to_pattern`, test `_make_id`
- **`test_configure.py`** — Test config generation from a fixture discovery JSON (mock `Confirm.ask` to auto-accept defaults)

The pure functions in `discovery.py` (classifiers, URL pattern, ID generation) are the easiest to unit test and the most valuable — they don't need browser mocking.

### Features

1. **Scope-aware content script.** The spec says rules should be scoped to URL patterns (e.g., only hide sidebar on `/feed/`, not on `/messaging/`). The current `content.js` applies all rules globally on `*://*.linkedin.com/*`. Fix: group selectors by URL pattern in `content.js` and check `window.location` before applying.

2. **Per-item toggle in configure.** Current implementation toggles by classification group. The spec envisions per-item control. Could add a `--detailed` flag.

3. **Extension popup/options page.** The spec mentions the extension in `baseline-spec.md` but doesn't require a popup. Would be nice for toggling rules without rebuilding.

4. **Proper icons.** Currently generates solid LinkedIn-blue placeholder PNGs. Replace with an actual LI Lite logo.

5. **`background.js`** is mentioned in the spec's extension structure but not generated by `build.py`. It's not needed for the current functionality (declarativeNetRequest rules are static, content script handles DOM). Only needed if you add dynamic rule management.

6. **Diff between discovery runs.** When re-running discovery after a LinkedIn deploy, it would be useful to diff the old and new discovery JSONs to see what changed.

## Likely first-run issues

1. **LinkedIn bot detection.** LinkedIn is aggressive about detecting automation. Patchright helps (it patches Playwright's detectable fingerprints), but LinkedIn may still flag the session. If this happens, the persistent Chrome profile at `data/auth/linkedin_chrome_profile/` helps — it accumulates natural browsing history across runs.

2. **Cookie domain mismatch.** `ctx.cookies([config.LINKEDIN_BASE])` filters by `https://www.linkedin.com`. If LinkedIn sets cookies on `.linkedin.com` (without `www`), they should still be captured. But cookies on `lnkd.in` or `licdn.com` won't be — may need to expand the domain list.

3. **Discovery output could be huge.** LinkedIn makes hundreds of API calls on page load. The deduplication by `url_pattern` helps, but the discovery JSON might still be large. The configure phase groups by classification so this is manageable for the user, but review the raw output after first run.

## Environment

- Python 3.12+, managed by `uv`
- Patchright (Playwright fork) for browser automation — requires `patchright install chrome` on first use
- `rich` for terminal UI
- No database (unlike x-bookmark-to-substack) — all state is in JSON files
- No external APIs — everything is local browser automation

## Quick reference

```bash
# Install deps
cd /home/julian/sambashare/expts/lilite
uv sync

# Run tests
uv run pytest tests/ -v

# Install browser (first time only)
uv run patchright install chrome

# Run the pipeline
uv run python -m lilite run
```
