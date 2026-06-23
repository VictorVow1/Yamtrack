# Fork maintenance: tabbed Discover

This fork adds a **tabbed Discover** UI on top of upstream's Discover feature. Upstream
declined the change, so it is maintained here as a personal feature. To keep pulling from
upstream cheap, the feature is built so that **almost all of its code lives in new,
fork-owned files** (git never conflicts on a file upstream doesn't have). The few edits
that *must* live inside upstream-owned files are reduced to one or two lines and tagged
with a marker so a rebase is mechanical.

## Rebasing onto upstream

1. `git fetch upstream && git rebase upstream/latest` (or `main`).
2. Resolve conflicts only in the **hook points** below — every fork edit inside an
   upstream file is marked `# fork:tabbed-discover` (Python) or `{# fork:tabbed-discover #}`
   (templates). Find them all with:
   ```
   grep -rn "fork:tabbed-discover" src/
   ```
3. Re-apply each hook (they are small and listed below), then run the verification suite.

If a rebase gets messy, flip the **kill-switch** (below) to make the feature inert and fix
it later — the page falls back to upstream's stacked-row layout.

## Kill-switch

`discover_tab_views.tab_context()` and the template branches are gated on
`settings.DISCOVER_TABS_ENABLED` (defaults to `True` via `getattr`, so no settings change
is needed to run it). To disable the tabbed UI without touching code, set in your
environment / settings:
```python
DISCOVER_TABS_ENABLED = False
```

## Hook points (edits inside upstream-owned files)

| File | Hook |
|---|---|
| `src/app/discover/provider_candidates.py` | `_provider_row_candidates`: lazy `from app.discover.tabs.builders import tab_row_candidates` + 3-line guard; `# noqa` on the def line. |
| `src/app/discover/service.py` | imports `PROVIDER_TAB_ROW_KEYS`; two `... in PROVIDER_TAB_ROW_KEYS` membership checks (`_build_row_candidates`, `_blocked_statuses_for_row`); `_compose_all_media_rows` sets `row.component_media_type`. |
| `src/app/discover/schemas.py` | `RowResult.component_media_type` field + its `to_dict`/`from_dict` lines. |
| `src/app/discover/__init__.py` | re-exports `get_discover_tab_row` from `app.discover.tabs.service`. |
| `src/app/discover/providers/tmdb_adapter.py` | appended `airing_today()` method (append-only). |
| `src/app/discover/providers/trakt_adapter.py` | appended `movie_boxoffice()` method (append-only). |
| `src/app/discover_views.py` | top-level `from app import ... discover_tab_views`; `_discover_rows_context` merges `discover_tab_views.tab_context(...)`. |
| `src/app/views.py` | `from app.discover_tab_views import discover_tab`. |
| `src/app/urls.py` | `path("discover/tab", views.discover_tab, name="discover_tab")`. |
| `src/templates/app/components/discover_rows.html` | two `{% elif %}` branches that `{% include %}` the tab partials. |
| `src/templates/app/components/discover_row.html` | grid body extracted to `{% include "app/components/discover_grid.html" %}`. |
| `src/templates/app/discover.html` | `discover-tabs.js` `<script>` include + `...window.discoverTabs(...)` spread into the Alpine component. |

## Fork-owned files (self-contained; never conflict)

- `src/app/discover/tabs/` — `registry.py`, `capabilities.py`, `builders.py`, `service.py`,
  `__init__.py` (the tab registry, availability, provider builders, and on-demand row builder).
- `src/app/discover_tab_views.py` — tab-bar context builders + the `discover_tab` HTMX view.
- `src/templates/app/components/discover_tabs_bar.html`,
  `src/templates/app/components/discover_all_media_sections.html`,
  `src/templates/app/components/discover_grid.html`.
- `src/static/js/discover-tabs.js`, `src/static/img/musicbrainz-logo.ico`.
- `src/app/tests/discover/test_tabs.py`.

## Verification

```
cd src
python -m pytest app/tests/discover/ -q
ruff check app/discover_tab_views.py app/discover/tabs/
djlint templates/app/components/discover_tabs_bar.html \
       templates/app/components/discover_all_media_sections.html --lint
```
