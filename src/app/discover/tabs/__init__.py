"""Discover editorial tabs (fork:tabbed-discover).

Fork-owned sub-package that layers a tabbed Discover UI over upstream's row
machinery. Everything tab-specific lives here so the upstream files it plugs into
keep only small, tagged hook lines (see ``FORK.md``).

This ``__init__`` deliberately re-exports only the lightweight registry and
capability helpers. ``builders`` (provider fetches) and ``service`` (on-demand row
building) pull in heavy upstream modules, so their hook sites import them straight
from the submodule to avoid import cycles during app start-up.
"""

from __future__ import annotations

from app.discover.tabs.capabilities import first_enabled_tab, tab_availability
from app.discover.tabs.registry import (
    PROVIDER_TAB_ROW_KEYS,
    SOURCE_ICONS,
    TAB_REGISTRY,
    TAB_ROW_DESCRIPTIONS,
    TabDefinition,
    default_tab,
    get_tab,
    get_tabs,
    media_type_is_multi_source,
    source_icon_path,
)

__all__ = [
    "PROVIDER_TAB_ROW_KEYS",
    "SOURCE_ICONS",
    "TAB_REGISTRY",
    "TAB_ROW_DESCRIPTIONS",
    "TabDefinition",
    "default_tab",
    "first_enabled_tab",
    "get_tab",
    "get_tabs",
    "media_type_is_multi_source",
    "source_icon_path",
    "tab_availability",
]
