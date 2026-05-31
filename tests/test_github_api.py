import hashlib
import pytest

from core.utils.github_api import parse_github_url, verify_sha256


def test_parse_standard_url():
    assert parse_github_url("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_url_with_trailing_slash():
    assert parse_github_url("https://github.com/owner/repo/") == ("owner", "repo")


def test_parse_url_with_extra_path():
    assert parse_github_url("https://github.com/owner/repo/tree/main/sub") == ("owner", "repo")


def test_parse_shorthand():
    assert parse_github_url("owner/repo") == ("owner", "repo")


def test_parse_shorthand_with_spaces():
    assert parse_github_url("  owner/repo  ") == ("owner", "repo")


def test_parse_non_github_http_raises():
    with pytest.raises(ValueError, match="Not a GitHub URL"):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_incomplete_path_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_github_url("owner")


def test_parse_empty_owner_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_github_url("/repo")


def test_verify_sha256_match():
    data = b"hello world"
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(data, digest) is True


def test_verify_sha256_with_prefix():
    data = b"hello world"
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(data, f"sha256:{digest}") is True


def test_verify_sha256_mismatch():
    assert verify_sha256(b"hello", "0" * 64) is False


def test_verify_sha256_case_insensitive():
    data = b"test"
    digest = hashlib.sha256(data).hexdigest().upper()
    assert verify_sha256(data, digest) is True


def test_verify_sha256_strips_whitespace():
    data = b"test"
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(data, f"  {digest}  ") is True
