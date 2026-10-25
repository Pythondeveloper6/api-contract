import pytest

from api_contract import ApiContractError, Severity, load_config
from api_contract.normalize import DEFAULT_IGNORE_KEYS


def test_defaults_without_any_config(tmp_path):
    config = load_config(start=tmp_path)
    assert config.source is None
    assert config.snapshot == tmp_path.resolve() / "api-contract.json"
    assert config.fail_on is Severity.BREAKING
    assert config.ignore_keys == DEFAULT_IGNORE_KEYS


def test_pyproject_table_is_discovered_from_subdirectory(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.api-contract]\nsource = "file:openapi.yaml"\nsnapshot = "contract/api.json"\n'
        'fail_on = "potentially-breaking"\nignore_keys = ["description"]\n'
        '[tool.api-contract.rules]\nenum-value-added = "breaking"\n'
    )
    sub = tmp_path / "pkg"
    sub.mkdir()
    config = load_config(start=sub)
    assert config.source == "file:openapi.yaml"
    assert config.snapshot == tmp_path.resolve() / "contract" / "api.json"
    assert config.fail_on is Severity.POTENTIALLY_BREAKING
    assert config.ignore_keys == ("description",)
    assert config.make_rules().severity("response-enum-value-added") is Severity.BREAKING


def test_pyproject_without_table_is_skipped(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert load_config(start=tmp_path).path is None


def test_standalone_file_with_bare_keys(tmp_path):
    (tmp_path / "api-contract.toml").write_text('source = "file:a.json"\n')
    assert load_config(start=tmp_path).source == "file:a.json"


@pytest.mark.parametrize(
    "body, message",
    [
        ('surce = "x"', "unknown api-contract setting"),
        ('fail_on = "safe"', "invalid fail_on"),
        ("[rules]\nnope = 'safe'", "unknown change kind"),
        ("ignore_keys = 'x'", "list of strings"),
        ("source = [", "not valid TOML"),
    ],
)
def test_invalid_config(tmp_path, body, message):
    path = tmp_path / "api-contract.toml"
    path.write_text(body + "\n")
    with pytest.raises(ApiContractError, match=message):
        load_config(path)


def test_extra_ignore_keys_append_to_the_defaults(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.api-contract]\nextra_ignore_keys = ["x-internal", "deprecated"]\n'
    )
    config = load_config(start=tmp_path)
    assert config.ignore_keys == (*DEFAULT_IGNORE_KEYS, "x-internal", "deprecated")


def test_extra_ignore_keys_extend_a_replaced_list_without_duplicates(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.api-contract]\nignore_keys = ["description"]\n'
        'extra_ignore_keys = ["title", "description"]\n'
    )
    assert load_config(start=tmp_path).ignore_keys == ("description", "title")


def test_ignore_keys_alone_still_replaces_the_defaults(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nignore_keys = ["description"]\n')
    assert load_config(start=tmp_path).ignore_keys == ("description",)


def test_extra_ignore_keys_must_be_a_list_of_strings(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nextra_ignore_keys = "x-foo"\n')
    with pytest.raises(ApiContractError, match="extra_ignore_keys.*list of strings"):
        load_config(start=tmp_path)
