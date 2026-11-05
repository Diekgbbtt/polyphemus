"""Unit tier: the loopback worker relay's configuration parser.

The relay itself is exercised live by the eval gate. This tier pins the
parsing contract: an empty value disables the relay, a comma-separated list is
accepted, and a malformed or out-of-range port fails loud instead of binding a
wrong listener.
"""
from __future__ import annotations

import pytest

from kali.steel_pool.forward import forward_ports


def test_forward_ports_accepts_a_comma_separated_list():
    assert forward_ports("3100,3101") == [3100, 3101]


def test_forward_ports_accepts_whitespace_and_empty_tokens():
    assert forward_ports(" 3100 , , 3101 ") == [3100, 3101]


def test_forward_ports_treats_an_empty_value_as_disabled():
    assert forward_ports("") == []
    assert forward_ports("   ") == []


@pytest.mark.parametrize("raw", ["0", "65536", "-1", "abc", "3100,oops"])
def test_forward_ports_rejects_an_invalid_port(raw):
    with pytest.raises(ValueError):
        forward_ports(raw)
