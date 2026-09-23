"""Model-size tiers for the MCP tool surface.

No dependency on the rest of the stack: this module must stay importable
before the catalog or the stdio pool exist.
"""

from __future__ import annotations

# e2b is the smallest lane. It is not a substring of e4b, but a name that
# somehow contains both stays on the smaller surface.
_MINIMAL = frozenset({"convert_time"})
_FAST = _MINIMAL | frozenset({
    "library_docs",
    "render_chart",
    "workspace_list",
    "workspace_read",
})
_FULL = _FAST | frozenset({
    "github_search",
    "github_read_file",
    "repo_status",
    "workspace_search",
    "query_data",
})

_BY_TIER = {
    "minimal": _MINIMAL,
    "fast": _FAST,
    "full": _FULL,
}


def model_tier(model_id: str) -> str:
    """Return ``minimal`` (e2b), ``fast`` (e4b) or ``full`` (anything else)."""
    name = (model_id or "").lower()
    if "e2b" in name:
        return "minimal"
    if "e4b" in name:
        return "fast"
    return "full"


def tools_for_tier(tier: str) -> set[str]:
    """Tool names exposed for ``tier``. Unknown tiers get an empty set."""
    return set(_BY_TIER.get(tier, ()))
