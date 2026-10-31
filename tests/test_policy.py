import datetime as dt

import pytest

from api_contract import ApiContractError, Severity, check, diff
from api_contract.config import config_from_dict
from api_contract.normalize import normalize
from api_contract.policy import ClientProfile, apply_policies

TODAY = dt.date(2026, 6, 1)


def op(**extra):
    return {"responses": {"200": {"description": "ok"}}, **extra}


def doc(paths):
    return {"openapi": "3.0.3", "paths": paths}


def evaluate(old, new, **kwargs):
    changes = diff(old, new)
    apply_policies(changes, normalize(old), normalize(new), today=TODAY, **kwargs)
    return changes


def test_frozen_paths_make_every_change_breaking():
    old = doc({"/v1/a": {"get": op()}, "/v2/a": {"get": op()}})
    new = doc(
        {
            "/v1/a": {"get": op()},
            "/v1/b": {"get": op()},
            "/v2/b": {"get": op()},
            "/v2/a": {"get": op()},
        }
    )
    changes = {c.path: c for c in evaluate(old, new, frozen=["/v1/*"])}
    assert changes["/v1/b"].severity is Severity.BREAKING
    assert "[frozen: /v1/*]" in changes["/v1/b"].message
    assert changes["/v2/b"].severity is Severity.SAFE


def test_removal_after_sunset_is_safe_and_before_is_breaking():
    old = doc(
        {
            "/past": {"get": op(deprecated=True, **{"x-sunset": "2026-01-01"})},
            "/future": {"get": op(deprecated=True, **{"x-sunset": "2026-12-01"})},
            "/undated": {"get": op(deprecated=True)},
        }
    )
    changes = {c.path: c for c in evaluate(old, doc({}))}
    assert changes["/past"].severity is Severity.SAFE
    assert "sunset 2026-01-01 has passed" in changes["/past"].message
    assert changes["/future"].severity is Severity.BREAKING
    assert "183 days early" in changes["/future"].message
    assert changes["/undated"].severity is Severity.BREAKING
    assert "no x-sunset" in changes["/undated"].message


def test_yaml_dates_for_sunset_are_accepted():
    old = doc({"/past": {"get": op(deprecated=True, **{"x-sunset": dt.date(2026, 1, 1)})}})
    [change] = evaluate(old, doc({}))
    assert change.severity is Severity.SAFE


def test_client_profiles_by_path_and_tag():
    enum = {"type": "string", "enum": ["a"]}
    wider = {"type": "string", "enum": ["a", "b"]}

    def spec(schema):
        response = {
            "200": {"description": "ok", "content": {"application/json": {"schema": schema}}}
        }
        return doc(
            {
                "/mobile/x": {"get": {"responses": response}},
                "/web/x": {"get": {"responses": response}},
                "/tagged": {"get": {"tags": ["app"], "responses": response}},
            }
        )

    mobile = ClientProfile(
        name="mobile",
        paths=("/mobile/*",),
        tags=("app",),
        fail_on=Severity.POTENTIALLY_BREAKING,
        rules={"response-enum-value-added": Severity.BREAKING},
    )
    changes = {c.path: c for c in evaluate(spec(enum), spec(wider), clients=[mobile])}
    assert changes["/mobile/x"].client == "mobile"
    assert changes["/mobile/x"].severity is Severity.BREAKING
    assert changes["/tagged"].client == "mobile"
    assert changes["/web/x"].client is None
    assert changes["/web/x"].severity is Severity.POTENTIALLY_BREAKING


def test_client_fail_on_applies_per_change(tmp_path):
    import yaml

    (tmp_path / "old.yaml").write_text(
        yaml.safe_dump(doc({"/mobile/x": {"get": op()}, "/web/x": {"get": op()}}))
    )
    new = doc({"/mobile/x": {"get": op()}, "/web/x": {"get": op()}})
    for path in ("/mobile/x", "/web/x"):
        new["paths"][path]["get"]["responses"]["410"] = {"description": "gone"}
        new["paths"][path]["get"]["responses"]["201"] = {"description": "created"}
    (tmp_path / "new.yaml").write_text(yaml.safe_dump(new))
    config = config_from_dict(
        {
            "source": f"file:{tmp_path / 'new.yaml'}",
            "snapshot": "snap.json",
            "clients": {"mobile": {"paths": ["/mobile/*"], "fail_on": "potentially-breaking"}},
        },
        base=tmp_path,
    )
    from api_contract import snapshot

    snapshot(config, source=f"file:{tmp_path / 'old.yaml'}")
    result = check(config)
    # response-success-added is potentially breaking: fails for mobile only.
    assert [c.path for c in result.failing] == ["/mobile/x"]
    assert not result.ok


@pytest.mark.parametrize(
    "table, message",
    [
        ({"clients": []}, "table of"),
        ({"clients": {"m": {}}}, "needs 'paths' or 'tags'"),
        ({"clients": {"m": {"paths": "/m/*", "bogus": 1}}}, "unknown setting"),
        ({"clients": {"m": {"paths": [1]}}}, "clients.m.paths"),
        ({"clients": {"m": {"paths": ["/m"], "fail_on": "safe"}}}, "invalid fail_on"),
        ({"clients": {"m": {"paths": ["/m"], "rules": {"nope": "safe"}}}}, "unknown change kind"),
        ({"frozen": [1]}, "'frozen'"),
    ],
)
def test_config_validation(tmp_path, table, message):
    with pytest.raises(ApiContractError, match=message):
        config_from_dict(table, base=tmp_path)


def test_config_accepts_single_string_for_lists(tmp_path):
    config = config_from_dict({"frozen": "/v1/*", "clients": {"m": {"tags": "app"}}}, base=tmp_path)
    assert config.frozen == ("/v1/*",)
    assert config.clients[0].tags == ("app",)
