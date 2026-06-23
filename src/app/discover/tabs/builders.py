"""Provider candidate builders for editorial Discover tabs (fork:tabbed-discover).

Each builder turns one tab ``row_key`` into a list of ``CandidateItem`` by calling
the relevant provider. ``tab_row_candidates`` is the single dispatcher the upstream
``provider_candidates._provider_row_candidates`` defers to (via a lazy import) before
falling through to its own legacy trending/canon/coming-soon handling.

Shared low-level helpers (HTTP caching, value coercion, the OpenLibrary / IGDB / MAL
candidate builders that already existed upstream) are imported from
``app.discover.provider_candidates`` so this module never duplicates them. The import
direction is one-way: ``provider_candidates`` imports ``tab_row_candidates`` lazily
inside its function body, so there is no module-level import cycle.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from app.discover.adapters import TMDB_ADAPTER, TRAKT_ADAPTER
from app.discover.provider_candidates import (
    PROVIDER_DISCOVER_TTL_SECONDS,
    _api_cached_results,
    _igdb_games_candidates,
    _iso_date,
    _mal_manga_ranking_candidates,
    _openlibrary_trending_candidates,
    _safe_float,
    _safe_int,
)
from app.discover.schemas import CandidateItem
from app.models import MediaTypes, Sources
from app.providers import mal, services

MAL_ANIME_LIST_FIELDS = (
    "media_type,start_date,genres,mean,num_scoring_users,num_list_users,"
    "main_picture,alternative_titles,start_season"
)
_MAL_SEASONS = ("winter", "spring", "summer", "fall")


def _current_anime_season(now=None) -> tuple[int, str]:
    """Return the (year, season) for the current calendar quarter."""
    now = now or timezone.now()
    return now.year, _MAL_SEASONS[(now.month - 1) // 3]


def _previous_anime_season(year: int, season: str) -> tuple[int, str]:
    """Return the (year, season) immediately preceding the given one."""
    index = _MAL_SEASONS.index(season)
    if index == 0:
        return year - 1, _MAL_SEASONS[-1]
    return year, _MAL_SEASONS[index - 1]


def _mal_anime_node_candidate(
    node: dict,
    *,
    row_key: str,
    source_reason: str,
    popularity: float | None,
) -> CandidateItem | None:
    media_id = _safe_int(node.get("id"))
    title = (mal.get_localized_title(node) or node.get("title") or "").strip()
    if not media_id or not title:
        return None
    genres = [
        str(genre.get("name")).strip()
        for genre in (node.get("genres") or [])
        if isinstance(genre, dict) and str(genre.get("name") or "").strip()
    ]
    return CandidateItem(
        media_type=MediaTypes.ANIME.value,
        source=Sources.MAL.value,
        media_id=str(media_id),
        title=title,
        original_title=node.get("title") or title,
        localized_title=title,
        image=mal.get_image_url(node),
        release_date=_iso_date(node.get("start_date")),
        genres=genres,
        popularity=popularity,
        rating=_safe_float(node.get("mean")),
        rating_count=_safe_int(node.get("num_scoring_users")),
        row_key=row_key,
        source_reason=source_reason,
    )


def _mal_anime_ranking_candidates(
    *,
    ranking_type: str,
    row_key: str,
    source_reason: str,
    limit: int = 100,
) -> list[CandidateItem]:
    endpoint = "/anime/ranking"
    params = {
        "ranking_type": ranking_type,
        "limit": min(max(limit, 1), 100),
        "fields": MAL_ANIME_LIST_FIELDS,
    }
    if settings.MAL_NSFW:
        params["nsfw"] = "true"

    def fetcher() -> list[dict]:
        payload = services.api_request(
            Sources.MAL.value,
            "GET",
            f"{mal.base_url}{endpoint}",
            params=params,
            headers={"X-MAL-CLIENT-ID": settings.MAL_API},
        )
        return [
            entry for entry in (payload.get("data") or []) if isinstance(entry, dict)
        ]

    entries = _api_cached_results(
        Sources.MAL.value,
        f"{endpoint}:{ranking_type}",
        params,
        ttl_seconds=PROVIDER_DISCOVER_TTL_SECONDS,
        fetcher=fetcher,
    )
    candidates: list[CandidateItem] = []
    for index, entry in enumerate(entries, start=1):
        node = entry.get("node") or {}
        ranking = entry.get("ranking") or {}
        popularity = _safe_float(ranking.get("rank"))
        if popularity is None:
            popularity = float(max(len(entries) - index + 1, 1))
        else:
            popularity = max(1.0, 1000.0 - popularity)
        candidate = _mal_anime_node_candidate(
            node,
            row_key=row_key,
            source_reason=source_reason,
            popularity=popularity,
        )
        if candidate:
            candidates.append(candidate)

    return candidates[:limit]


def _mal_anime_season_candidates(
    *,
    year: int,
    season: str,
    row_key: str,
    source_reason: str,
    sort: str = "anime_num_list_users",
    limit: int = 100,
) -> list[CandidateItem]:
    endpoint = f"/anime/season/{year}/{season}"
    params = {
        "sort": sort,
        "limit": min(max(limit, 1), 100),
        "fields": MAL_ANIME_LIST_FIELDS,
    }
    if settings.MAL_NSFW:
        params["nsfw"] = "true"

    def fetcher() -> list[dict]:
        payload = services.api_request(
            Sources.MAL.value,
            "GET",
            f"{mal.base_url}{endpoint}",
            params=params,
            headers={"X-MAL-CLIENT-ID": settings.MAL_API},
        )
        return [
            entry for entry in (payload.get("data") or []) if isinstance(entry, dict)
        ]

    entries = _api_cached_results(
        Sources.MAL.value,
        endpoint,
        params,
        ttl_seconds=PROVIDER_DISCOVER_TTL_SECONDS,
        fetcher=fetcher,
    )
    candidates: list[CandidateItem] = []
    for index, entry in enumerate(entries, start=1):
        node = entry.get("node") or {}
        popularity = _safe_float(node.get("num_list_users"))
        if popularity is None:
            popularity = float(max(len(entries) - index + 1, 1))
        candidate = _mal_anime_node_candidate(
            node,
            row_key=row_key,
            source_reason=source_reason,
            popularity=popularity,
        )
        if candidate:
            candidates.append(candidate)

    return candidates[:limit]


def _mal_anime_tab_candidates(
    media_type: str, row_key: str
) -> list[CandidateItem] | None:
    """Return candidates for anime/manga tab rows, or None if not such a row."""
    if media_type == MediaTypes.ANIME.value:
        if row_key == "mal_this_season":
            year, season = _current_anime_season()
            return _mal_anime_season_candidates(
                year=year,
                season=season,
                row_key=row_key,
                source_reason="MAL current season",
            )
        if row_key == "mal_last_season":
            year, season = _previous_anime_season(*_current_anime_season())
            return _mal_anime_season_candidates(
                year=year,
                season=season,
                row_key=row_key,
                source_reason="MAL previous season",
            )
        ranking_map = {
            "mal_anime_top_rated": "all",
            "mal_anime_airing": "airing",
            "mal_anime_popular": "bypopularity",
            "mal_anime_upcoming": "upcoming",
        }
        if row_key in ranking_map:
            return _mal_anime_ranking_candidates(
                ranking_type=ranking_map[row_key],
                row_key=row_key,
                source_reason="MAL ranking",
            )
    if media_type == MediaTypes.MANGA.value and row_key == "mal_manga_publishing":
        return _mal_manga_ranking_candidates(
            ranking_type="manga",
            row_key=row_key,
            source_reason="MAL publishing",
        )
    return None


def _reassign_row_key(
    candidates: list[CandidateItem], row_key: str
) -> list[CandidateItem]:
    """Stamp the tab's row_key onto adapter-produced candidates."""
    for candidate in candidates:
        candidate.row_key = row_key
    return candidates


def _tmdb_tab_candidates(media_type: str, row_key: str) -> list[CandidateItem] | None:
    """Return candidates for TMDb-backed tabs, or None if not such a row."""
    if media_type not in {MediaTypes.MOVIE.value, MediaTypes.TV.value}:
        return None
    if row_key == "tmdb_trending":
        candidates = TMDB_ADAPTER.trending(media_type)
    elif row_key == "tmdb_top_rated":
        candidates = TMDB_ADAPTER.top_rated(media_type)
    elif row_key in {"tmdb_now_playing", "tmdb_on_the_air"}:
        candidates = TMDB_ADAPTER.current_cycle(media_type)
    elif row_key == "tmdb_airing_today":
        candidates = TMDB_ADAPTER.airing_today(media_type)
    else:
        return None
    return _reassign_row_key(candidates, row_key)


def _trakt_tab_candidates(media_type: str, row_key: str) -> list[CandidateItem] | None:
    """Return candidates for extra Trakt tabs, or None if not such a row."""
    if media_type == MediaTypes.MOVIE.value and row_key == "trakt_box_office":
        return TRAKT_ADAPTER.movie_boxoffice(limit=100)
    return None


_OPENLIBRARY_PERIOD_ROWS = {
    "openlibrary_weekly": "weekly",
    "openlibrary_monthly": "monthly",
    "openlibrary_yearly": "yearly",
}


def _openlibrary_tab_candidates(
    media_type: str, row_key: str
) -> list[CandidateItem] | None:
    """Return candidates for OpenLibrary period tabs, or None if not such a row."""
    if media_type == MediaTypes.BOOK.value and row_key in _OPENLIBRARY_PERIOD_ROWS:
        return _openlibrary_trending_candidates(
            period=_OPENLIBRARY_PERIOD_ROWS[row_key],
            row_key=row_key,
            source_reason="Open Library trending",
        )
    return None


def _lastfm_top_artists_candidates(
    *,
    row_key: str,
    source_reason: str,
    limit: int = 100,
) -> list[CandidateItem]:
    if not settings.LASTFM_API_KEY:
        return []

    endpoint = "/2.0/chart.gettopartists"
    params = {
        "method": "chart.gettopartists",
        "api_key": settings.LASTFM_API_KEY,
        "format": "json",
        "limit": min(max(limit, 1), 200),
    }

    def fetcher() -> list[dict]:
        payload = services.api_request(
            "LASTFM",
            "GET",
            "https://ws.audioscrobbler.com/2.0/",
            params=params,
        )
        artists = ((payload.get("artists") or {}).get("artist") or [])
        if isinstance(artists, dict):
            artists = [artists]
        return [artist for artist in artists if isinstance(artist, dict)]

    artists = _api_cached_results(
        Sources.MUSICBRAINZ.value,
        endpoint,
        params,
        ttl_seconds=PROVIDER_DISCOVER_TTL_SECONDS,
        fetcher=fetcher,
    )

    candidates: list[CandidateItem] = []
    for artist in artists:
        mbid = str(artist.get("mbid") or "").strip()
        title = str(artist.get("name") or "").strip()
        if not mbid or not title:
            continue
        images = artist.get("image") or []
        image = settings.IMG_NONE
        if isinstance(images, list):
            for img in reversed(images):
                if isinstance(img, dict) and str(img.get("#text") or "").strip():
                    image = str(img.get("#text")).strip()
                    break
        candidates.append(
            CandidateItem(
                media_type=MediaTypes.MUSIC.value,
                source=Sources.MUSICBRAINZ.value,
                media_id=mbid,
                title=title,
                image=image,
                popularity=(
                    _safe_float(artist.get("playcount"))
                    or _safe_float(artist.get("listeners"))
                ),
                row_key=row_key,
                source_reason=source_reason,
            ),
        )
        if len(candidates) >= limit:
            break

    return candidates[:limit]


def _igdb_tab_candidates(media_type: str, row_key: str) -> list[CandidateItem] | None:
    """Return candidates for extra IGDB tabs, or None if not such a row."""
    if media_type != MediaTypes.GAME.value:
        return None
    base_fields = (
        "fields name,cover.image_id,first_release_date,"
        "total_rating,total_rating_count,genres.name;"
    )
    if row_key == "igdb_top_rated":
        query = (
            f"{base_fields}"
            " where total_rating != null & total_rating_count >= 50;"
            " sort total_rating desc;"
            " limit 100;"
        )
        return _igdb_games_candidates(
            query=query,
            endpoint_key="/games/igdb_top_rated",
            row_key=row_key,
            source_reason="IGDB top rated",
            limit=100,
        )
    if row_key == "igdb_coming_soon":
        future_cutoff = int(timezone.now().timestamp())
        query = (
            f"{base_fields}"
            " where first_release_date != null"
            f" & first_release_date > {future_cutoff} & hypes != null;"
            " sort hypes desc;"
            " limit 100;"
        )
        return _igdb_games_candidates(
            query=query,
            endpoint_key="/games/igdb_coming_soon",
            row_key=row_key,
            source_reason="IGDB anticipated",
            limit=100,
        )
    return None


def tab_row_candidates(media_type: str, row_key: str) -> list[CandidateItem] | None:
    """Dispatch editorial tab rows to their provider builder.

    Returns None when the row_key is not a dedicated tab row, so the caller can
    fall through to the legacy trending/canon/coming-soon handling.
    """
    for resolver in (
        _mal_anime_tab_candidates,
        _tmdb_tab_candidates,
        _trakt_tab_candidates,
        _openlibrary_tab_candidates,
        _igdb_tab_candidates,
    ):
        candidates = resolver(media_type, row_key)
        if candidates is not None:
            return candidates
    if media_type == MediaTypes.MUSIC.value and row_key == "lastfm_top_artists":
        return _lastfm_top_artists_candidates(
            row_key=row_key,
            source_reason="Last.fm top artists",
        )
    return None
