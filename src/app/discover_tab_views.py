"""View-layer support for the tabbed Discover UI (fork:tabbed-discover).

Holds everything the tab bar needs at the view layer -- the per-request tab-bar
payload, the single-media and All-Media context builders, and the ``discover_tab``
HTMX endpoint -- so ``discover_views`` keeps only one tiny tagged hook
(``_discover_rows_context`` calls :func:`tab_context`).

Shared request helpers (media-type resolution, debug coercion, response headers,
row-fragment rendering) live in ``discover_views`` and are referenced through the
module object. The import is one-way at module scope: ``discover_views`` imports
this module lazily inside ``_discover_rows_context``, so there is no cycle.
"""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_GET

from app import discover, discover_views
from app.discover import tabs as discover_tabs
from app.discover.registry import DISCOVER_MEDIA_TYPES
from app.templatetags import app_tags

# Editorial registry rows surfaced through the tab bar instead of stacked rows.
TABBED_EDITORIAL_ROW_KEYS = {
    "trending_right_now",
    "all_time_greats_unseen",
    "coming_soon",
}


def _tabs_enabled() -> bool:
    """Return whether the tabbed Discover UI is active (kill-switch)."""
    return bool(getattr(settings, "DISCOVER_TABS_ENABLED", True))


def _media_type_has_tabs(media_type: str) -> bool:
    return bool(discover_tabs.get_tabs(media_type))


def _discover_tabs_payload(media_type: str, *, selected_tab: str):
    """Return the tab-bar payload (label, active state, availability) for templates."""
    availability = discover_tabs.tab_availability(media_type)
    # Show a source logo on each tab only when the media type mixes providers.
    multi_source = discover_tabs.media_type_is_multi_source(media_type)
    payload = []
    for tab in discover_tabs.get_tabs(media_type):
        state = availability.get(tab.key, {"enabled": True, "tooltip": None})
        source_icon = None
        if multi_source:
            icon_path = discover_tabs.source_icon_path(tab.provider)
            if icon_path:
                source_icon = static(icon_path)
        payload.append(
            {
                "key": tab.key,
                "label": tab.label,
                "enabled": state["enabled"],
                "tooltip": state["tooltip"],
                "active": tab.key == selected_tab,
                "source_icon": source_icon,
            },
        )
    return payload


def _resolve_discover_tab(request, media_type: str, rows):
    """Build the tab-bar payload, the selected tab's row, and the stacked rows.

    The default tab is the first *enabled* one (so a media type whose Trending
    provider key is missing opens on the first usable tab). When that default is
    the trending row, it is reused from the already-built ``rows`` (produced by
    the background tab cache, not rebuilt here); otherwise it is built on demand.
    Remaining editorial rows are dropped from the stacked list, leaving only the
    personalized rows.
    """
    selected_tab = discover_tabs.first_enabled_tab(media_type)
    tab = discover_tabs.get_tab(media_type, selected_tab)
    rows_by_key = {row.key: row for row in rows}
    tab_row = rows_by_key.get(tab.row_key) if tab else None
    if (
        tab is not None
        and tab_row is None
        and tab.row_key not in TABBED_EDITORIAL_ROW_KEYS
    ):
        tab_row = discover.get_discover_tab_row(request.user, media_type, tab)
    stacked_rows = [row for row in rows if row.key not in TABBED_EDITORIAL_ROW_KEYS]
    return {
        "has_tabs": True,
        "discover_tabs": _discover_tabs_payload(media_type, selected_tab=selected_tab),
        "selected_tab": selected_tab,
        "tab_row": tab_row,
        "rows": stacked_rows,
    }


def _all_media_section_media_types(request):
    """Return the ordered media types that get a section in the All Media view."""
    enabled = [
        media_type
        for media_type in request.user.get_enabled_media_types()
        if media_type in DISCOVER_MEDIA_TYPES
    ]
    return enabled or list(DISCOVER_MEDIA_TYPES)


def _resolve_all_media_sections(request, rows):
    """Build per-media-type tabbed sections for the All Media view.

    A section is created for every enabled media type so the tab bars render even
    while the rows are still warming in the background; each section's grid shows
    its own loading/empty state until its Trending row is ready. Tabs swap that
    section's grid independently.
    """
    trending_by_media = {}
    for row in rows:
        if row.key != "trending_right_now":
            continue
        # component_media_type is set on fresh composition; fall back to the row's
        # items when it is absent (e.g. rows restored from the serialized cache).
        media_type = row.component_media_type
        if not media_type and row.items:
            media_type = row.items[0].media_type
        if media_type and media_type not in trending_by_media:
            trending_by_media[media_type] = row

    sections = []
    for media_type in _all_media_section_media_types(request):
        if not _media_type_has_tabs(media_type):
            continue
        selected_tab = discover_tabs.first_enabled_tab(media_type)
        tab = discover_tabs.get_tab(media_type, selected_tab)
        section_row = trending_by_media.get(media_type)
        # Build on demand only when the default tab isn't the (cached) Trending row;
        # a missing Trending row means it is still warming, so leave it to load.
        if tab is not None and tab.row_key != "trending_right_now" and (
            section_row is None or section_row.key != tab.row_key
        ):
            section_row = discover.get_discover_tab_row(request.user, media_type, tab)
        sections.append(
            {
                "media_type": media_type,
                "label": app_tags.media_type_readable_plural(media_type),
                "tabs": _discover_tabs_payload(media_type, selected_tab=selected_tab),
                "selected_tab": selected_tab,
                "row": section_row,
            },
        )
    return sections


def tab_context(request, selected_media_type: str, rows) -> dict:
    """Return the tab-bar / All-Media-section context to merge into the rows partial.

    Returns an empty dict when the tabbed UI is disabled or the media type has no
    tabs, so ``discover_views._discover_rows_context`` can merge unconditionally and
    the templates fall back to upstream's stacked-row layout.
    """
    if not _tabs_enabled():
        return {}
    if _media_type_has_tabs(selected_media_type):
        return _resolve_discover_tab(request, selected_media_type, rows)
    if selected_media_type == "all":
        return {"all_media_sections": _resolve_all_media_sections(request, rows)}
    return {}


@login_required
@require_GET
def discover_tab(request):
    """Render a single editorial tab's grid for HTMX tab switching."""
    selected_media_type = discover_views._resolve_discover_media_type_for_user(
        request.user,
        request.GET.get("media_type"),
    )
    if not _media_type_has_tabs(selected_media_type):
        return HttpResponseBadRequest("Tabs are not available for this media type.")

    tab_key = (request.GET.get("tab") or "").strip()
    tab = discover_tabs.get_tab(selected_media_type, tab_key)
    if tab is None:
        return HttpResponseBadRequest("Unknown Discover tab.")

    availability = discover_tabs.tab_availability(selected_media_type)
    if not availability.get(tab_key, {}).get("enabled", False):
        return HttpResponseBadRequest("This Discover tab is not available.")

    discover_debug = discover_views._coerce_discover_debug(
        request.GET.get("discover_debug"),
    )
    tab_row = discover.get_discover_tab_row(request.user, selected_media_type, tab)

    # All-media sections swap only their grid (header + tab bar stay put) and keep
    # the "all" action context, so post-action refresh stays on the All Media tab.
    if request.GET.get("layout") == "grid":
        active_media_type = request.GET.get("active_media_type") or selected_media_type
        response = render(
            request,
            "app/components/discover_grid.html",
            {
                "row": tab_row,
                "discover_active_media_type": active_media_type,
                "show_more": False,
                "discover_debug": discover_debug,
            },
        )
        return discover_views._apply_discover_response_headers(
            response,
            user_id=request.user.id,
            selected_media_type=selected_media_type,
            show_more=False,
            discover_debug=discover_debug,
        )

    return discover_views._render_discover_row_fragment(
        request,
        selected_media_type=selected_media_type,
        show_more=False,
        discover_debug=discover_debug,
        row=tab_row,
    )
