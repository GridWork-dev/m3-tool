def is_blocked(status: int, title: str, text_head: str) -> bool:
    markers = (
        "just a moment",
        "attention required",
        "security checkpoint",
        "verify you are human",
        "captcha",
        "access denied",
    )
    text = (title + " " + text_head).lower()
    return status in {403, 429} or any(marker in text for marker in markers)
