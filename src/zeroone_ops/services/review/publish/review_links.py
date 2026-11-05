"""Validate optional browser links without turning presentation errors into failures."""

from urllib.parse import urlsplit


def is_browser_url(url: str | None) -> bool:
    """Treat malformed, credential-bearing, or non-HTTP(S) links as unavailable."""
    if not url or url != url.strip():
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in url):
        return False

    try:
        parsed = urlsplit(url)
        port = parsed.port
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and not any(character.isspace() for character in parsed.netloc)
            and parsed.username is None
            and parsed.password is None
            and (port is None or 0 <= port <= 65535)
        )
    except ValueError:
        return False
