"""Tests for relay host classification."""

from __future__ import annotations

import pytest

from zing.utils.net import is_local_host


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:11434/v1",
        "http://127.0.0.1:8080/v1",
        "http://[::1]:8000/v1",
        "http://192.168.1.20:1234/v1",
        "http://10.0.0.5/v1",
        "http://172.17.0.1:8000/v1",
        "http://host.docker.internal:11434/v1",
        "http://gpu-box.local:8000/v1",
    ],
)
def test_local_hosts(url):
    assert is_local_host(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://relay.example.com/v1",
        "https://8.8.8.8/v1",
        # a public DNS name that merely starts with "127." is not loopback
        "http://127.relay.example.com/v1",
        "",
        "not a url",
    ],
)
def test_remote_hosts(url):
    assert not is_local_host(url)
