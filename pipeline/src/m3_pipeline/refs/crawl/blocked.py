def _has_markers(title: str, text_head: str) -> bool:
    markers = (
        "just a moment",
        "attention required",
        "security checkpoint",
        "verify you are human",
        "captcha",
        "access denied",
    )
    text = (title + " " + text_head).lower()
    return any(marker in text for marker in markers)


def is_rate_limited(status: int, title: str, text_head: str) -> bool:
    """A plain 429 with no challenge markers: ordinary rate limiting, not a block."""
    return status == 429 and not _has_markers(title, text_head)


def is_blocked(status: int, title: str, text_head: str) -> bool:
    return status in {403, 429} or _has_markers(title, text_head)
