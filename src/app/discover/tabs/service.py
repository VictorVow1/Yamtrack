"""On-demand row building for a single Discover tab (fork:tabbed-discover).

A selected tab renders exactly one row and, unlike the stacked rows, always shows
(even when sparse) -- so it skips the min-items / drop-if-empty filtering that
``discover.service.get_discover_rows`` applies. This lives outside ``discover.service``
so that module keeps only a couple of small tagged hooks; the helpers it reuses are
referenced through the ``discover.service`` module object (SLF001 is project-ignored)
to avoid a wall of private-name imports.
"""

from __future__ import annotations

from app.discover import service as discover_service
from app.discover.schemas import RowDefinition, RowResult
from app.discover.tabs.registry import TAB_ROW_DESCRIPTIONS


def _tab_row_definition(media_type: str, tab) -> RowDefinition:
    """Return the RowDefinition backing a tab.

    Reuses the registry definition when the tab maps to an existing row (so the
    Trakt canon/anticipated build paths and copy are preserved); otherwise
    synthesizes a definition for the new tab-only row.
    """
    for row_definition in discover_service.get_rows(media_type, include_show_more=True):
        if row_definition.key == tab.row_key:
            return row_definition
    return RowDefinition(
        key=tab.row_key,
        title=tab.label,
        mission="",
        why=TAB_ROW_DESCRIPTIONS.get(tab.row_key, ""),
        source=tab.provider,
    )


def get_discover_tab_row(user, media_type: str, tab) -> RowResult:
    """Build a single editorial tab row on demand.

    Unlike the stacked rows, a user-selected tab always renders (even when sparse),
    so the min-items / drop-if-empty filtering used by get_discover_rows is skipped.
    """
    media_type = discover_service._coerce_media_type(media_type)
    media_type = discover_service.tab_cache.resolve_media_type_for_user(
        user,
        media_type,
    )
    row_definition = _tab_row_definition(media_type, tab)
    profile_payload = discover_service.get_or_compute_taste_profile(user, media_type)
    row = discover_service._build_and_cache_row(
        user,
        media_type,
        row_definition,
        profile_payload,
        defer_artwork=False,
        show_more=False,
    )
    deduped_items = discover_service.dedupe_candidates(row.items, seen_identities=set())
    row.items = deduped_items[: discover_service.MAX_ITEMS_PER_ROW]
    row.reserve_items = deduped_items[discover_service.MAX_ITEMS_PER_ROW :]
    row.match_signal = discover_service._row_match_signal_with_details(
        row_definition.key,
        row.items,
        profile_payload,
    )[0]
    return row
