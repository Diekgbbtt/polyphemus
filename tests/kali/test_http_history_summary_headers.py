"""The app-side header families and the Kali-side projection must agree.

The two live in separate deployment units (`src/polymerhus` in the app image,
`kali` in the Kali image), so neither can import the other.
The contract module carries the names the description teaches; the sanitizer
carries the names it renders.
This test is the pin.
"""
from __future__ import annotations

from polymerhus.attack.hunting.http_history_contract import (
    SEARCH_REQUEST_HEADERS,
    SEARCH_RESPONSE_HEADERS,
)
from kali.http_history.sanitize import (
    SUMMARY_REQUEST_HEADERS,
    SUMMARY_RESPONSE_HEADERS,
)


def test_the_request_header_family_matches_the_kali_projection():
    assert set(SEARCH_REQUEST_HEADERS) == set(SUMMARY_REQUEST_HEADERS)


def test_the_response_header_family_matches_the_kali_projection():
    assert set(SEARCH_RESPONSE_HEADERS) == set(SUMMARY_RESPONSE_HEADERS)
