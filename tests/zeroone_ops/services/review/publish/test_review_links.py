"""Optional presentation URLs cannot crash rendering or hide finding evidence."""

import pytest

from zeroone_ops.services.review.publish.review_links import is_browser_url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        " ",
        "https://[broken",
        "https://[not-an-ip]/review",
        "https://example.com:invalid/review",
        "https://example.com:65536/review",
        "https://example.com:-1/review",
        "https://example.com\uff0f.invalid/review",
        "javascript:alert(1)",
        "file:///review",
        "//example.com/review",
        "/review",
        "https:///review",
        "https://bad host/review",
        " https://example.com/review",
        "https://example.com/review\n",
        "https://example.com/\x00review",
        "https://example.com/\x7freview",
        "https://user:secret@example.com/review",
    ],
)
def test_unusable_browser_url_is_rejected_without_raising(url: str | None) -> None:
    assert not is_browser_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/review#comment-1",
        "http://git.internal:8080/review",
        "https://[::1]:8443/review",
        "https://example.com/review?attempt=2&stage=review",
        "https://example.com/review with spaces",
        "https://example.com/\u6771\u4eac",
    ],
)
def test_supported_browser_urls_remain_available(url: str) -> None:
    assert is_browser_url(url)
