import pytest

from core.adapter.base import AccessController, ListAccessPolicy


def test_allow_list_policy_normalizes_target_ids():
    policy = ListAccessPolicy.from_lists(
        "allow_list",
        allow_list=[123, "user"],
        deny_list=["ignored"],
    )

    assert policy.entries == frozenset({"123", "user"})
    assert policy.allows(123)
    assert policy.allows("123")
    assert not policy.allows("missing")
    assert not policy.allows(None)


def test_deny_list_policy_uses_only_deny_entries():
    policy = ListAccessPolicy.from_lists(
        "deny_list",
        allow_list=["ignored"],
        deny_list=[123, "blocked"],
    )

    assert policy.entries == frozenset({"123", "blocked"})
    assert not policy.allows(123)
    assert not policy.allows("blocked")
    assert policy.allows("other")
    assert not policy.allows(None)


def test_invalid_mode_falls_back_to_allow_list():
    policy = ListAccessPolicy.from_lists(
        "invalid",
        allow_list=["allowed"],
        deny_list=["blocked"],
    )

    assert policy.mode == "allow_list"
    assert policy.allows("allowed")
    assert not policy.allows("blocked")


def test_access_controller_separates_domains_and_permissions():
    access = AccessController()
    access.set_policy(
        domain="qq_channel",
        permission="im.group.receive",
        policy=ListAccessPolicy.from_lists(
            "allow_list",
            allow_list=["group-1"],
        ),
    )
    access.set_policy(
        domain="qzone",
        permission="feed.comment.receive",
        policy=ListAccessPolicy.from_lists(
            "deny_list",
            deny_list=["user-1"],
        ),
    )

    assert access.is_allowed(
        "group-1",
        domain="qq_channel",
        permission="im.group.receive",
    )
    assert not access.is_allowed(
        "group-1",
        domain="qzone",
        permission="im.group.receive",
    )
    assert not access.is_allowed(
        "user-1",
        domain="qzone",
        permission="feed.comment.receive",
    )
    assert access.is_allowed(
        "user-2",
        domain="qzone",
        permission="feed.comment.receive",
    )


@pytest.mark.parametrize(
    ("domain", "permission"),
    [
        ("", "im.group.receive"),
        ("qq_channel", ""),
        ("   ", "im.group.receive"),
        ("qq_channel", "   "),
    ],
)
def test_access_controller_rejects_empty_keys(domain, permission):
    access = AccessController()

    with pytest.raises(ValueError):
        access.is_allowed(
            "target",
            domain=domain,
            permission=permission,
        )
