"""Shared utilities for platform modules."""

import re

# Matches YouTube URLs with a video ID containing "dapr" (case-insensitive)
_YT_DAPR_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?.*?v=|youtu\.be/|youtube\.com/shorts/)([A-Za-z0-9_-]*[Dd][Aa][Pp][Rr][A-Za-z0-9_-]*)",
    re.IGNORECASE,
)


_NSFW_RE = re.compile(r"\bnsfw\b|18\+", re.IGNORECASE)


def is_nsfw(text: str) -> bool:
    """Return True if the text contains NSFW or 18+ markers."""
    return bool(_NSFW_RE.search(text))


def only_dapr_in_youtube_id(text: str) -> bool:
    """Return True if every occurrence of 'dapr' in the text is inside a YouTube video ID."""
    if "dapr" not in text.lower():
        return False
    # Remove all YouTube URLs whose video ID contains 'dapr'
    stripped = _YT_DAPR_ID_RE.sub("", text)
    # If 'dapr' no longer appears, the match was only in video IDs
    return "dapr" not in stripped.lower()
