import pytest

from core.config.config_field import (
    ConfigType,
    StringField,
    IntField,
    FloatField,
    SensitiveField,
    ListField,
    EnumField,
    SwitchField,
    JsonField,
    MarkdownField,
    YamlField,
    EditorField,
    TextareaField,
    ModelSelectField,
    MultiSelectField,
    SectionField,
    create_field_from_schema,
    build_fields,
)


def test_string_field():
    f = StringField("k", "Name", "hint", default="val")
    assert f.type == ConfigType.String
    d = f.to_dict()
    assert d["type"] == "string"
    assert d["default"] == "val"


def test_int_field():
    f = IntField("k", "Name", "hint", default=42)
    d = f.to_dict()
    assert d["type"] == "integer"
    assert d["default"] == 42


def test_float_field():
    f = FloatField("k", "Name", "hint", default=3.14)
    d = f.to_dict()
    assert d["type"] == "float"


def test_sensitive_field():
    f = SensitiveField("k", "Name", "hint", default="secret")
    d = f.to_dict()
    assert d["type"] == "sensitive"


def test_list_field_default_none():
    f = ListField("k", "Name", "hint", default=None)
    assert f.default == []


def test_list_field_default_list():
    f = ListField("k", "Name", "hint", default=["a", "b"])
    assert f.default == ["a", "b"]


def test_enum_field_with_valid_default():
    f = EnumField("k", "Name", "hint", options=["a", "b", "c"], default="b")
    assert f.default == "b"
    d = f.to_dict()
    assert d["options"] == ["a", "b", "c"]


def test_enum_field_invalid_default_fallback():
    f = EnumField("k", "Name", "hint", options=["a", "b"], default="z")
    assert f.default == "a"


def test_switch_field_default_bool():
    f = SwitchField("k", "Name", "hint", default=True)
    assert f.default is True


def test_switch_field_non_bool_default():
    f = SwitchField("k", "Name", "hint", default="yes")
    assert f.default is False


def test_json_field_default_none():
    f = JsonField("k", "Name", "hint", default=None)
    assert f.default == {}


def test_editor_field_with_language():
    f = EditorField("k", "Name", "hint", default="", language="json")
    d = f.to_dict()
    assert d["language"] == "json"


def test_editor_field_no_language():
    f = EditorField("k", "Name", "hint", default="")
    d = f.to_dict()
    assert "language" not in d


def test_model_select_field():
    f = ModelSelectField("k", "Name", "hint", model_type="llm")
    d = f.to_dict()
    assert d["model_type"] == "llm"


def test_multi_select_field():
    f = MultiSelectField("k", "Name", "hint", options=["a", "b"], default=["a"])
    d = f.to_dict()
    assert d["options"] == ["a", "b"]
    assert f.default == ["a"]


def test_section_field():
    child = StringField("child_k", "Child", "hint", default="v")
    f = SectionField("sec", "Section", "hint", fields=[child], collapsed=True)
    d = f.to_dict()
    assert d["collapsed"] is True
    assert "child_k" in d["fields"]
    assert d["fields"]["child_k"]["type"] == "string"


def test_locales_included():
    f = StringField("k", "Name", "hint", locales={"zh": {"name": "zh_name"}})
    d = f.to_dict()
    assert d["locales"] == {"zh": {"name": "zh_name"}}


def test_locales_omitted_when_empty():
    f = StringField("k", "Name", "hint")
    d = f.to_dict()
    assert "locales" not in d


def test_create_field_string():
    f = create_field_from_schema("k", {"type": "string", "name": "Name", "hint": "h", "default": "v"})
    assert isinstance(f, StringField)
    assert f.default == "v"


def test_create_field_text_with_options_becomes_enum():
    f = create_field_from_schema("k", {"type": "text", "options": ["a", "b"]})
    assert isinstance(f, EnumField)


def test_create_field_sensitive():
    f = create_field_from_schema("k", {"type": "sensitive"})
    assert isinstance(f, SensitiveField)


def test_create_field_integer():
    f = create_field_from_schema("k", {"type": "integer"})
    assert isinstance(f, IntField)


def test_create_field_int_alias():
    f = create_field_from_schema("k", {"type": "int"})
    assert isinstance(f, IntField)


def test_create_field_float():
    f = create_field_from_schema("k", {"type": "float"})
    assert isinstance(f, FloatField)


def test_create_field_list():
    f = create_field_from_schema("k", {"type": "list"})
    assert isinstance(f, ListField)


def test_create_field_enum():
    f = create_field_from_schema("k", {"type": "enum", "options": ["x", "y"], "default": "y"})
    assert isinstance(f, EnumField)
    assert f.default == "y"


def test_create_field_switch():
    f = create_field_from_schema("k", {"type": "switch", "default": True})
    assert isinstance(f, SwitchField)
    assert f.default is True


def test_create_field_json():
    f = create_field_from_schema("k", {"type": "json"})
    assert isinstance(f, JsonField)


def test_create_field_markdown():
    f = create_field_from_schema("k", {"type": "markdown"})
    assert isinstance(f, MarkdownField)


def test_create_field_yaml():
    f = create_field_from_schema("k", {"type": "yaml"})
    assert isinstance(f, YamlField)


def test_create_field_editor():
    f = create_field_from_schema("k", {"type": "editor", "language": "css"})
    assert isinstance(f, EditorField)
    assert f.language == "css"


def test_create_field_textarea():
    f = create_field_from_schema("k", {"type": "textarea"})
    assert isinstance(f, TextareaField)


def test_create_field_model_select():
    f = create_field_from_schema("k", {"type": "model_select", "model_type": "embedding"})
    assert isinstance(f, ModelSelectField)
    assert f.model_type == "embedding"


def test_create_field_multi_select():
    f = create_field_from_schema("k", {"type": "multi_select", "options": ["a"]})
    assert isinstance(f, MultiSelectField)


def test_create_field_section():
    schema = {
        "type": "section",
        "collapsed": True,
        "fields": {
            "child": {"type": "string", "name": "Child"},
        },
    }
    f = create_field_from_schema("sec", schema)
    assert isinstance(f, SectionField)
    assert f.collapsed is True
    assert len(f.fields) == 1
    assert isinstance(f.fields[0], StringField)


def test_create_field_unknown_type_defaults_to_string():
    f = create_field_from_schema("k", {"type": "unknown_xyz"})
    assert isinstance(f, StringField)


def test_create_field_missing_type_defaults_to_string():
    f = create_field_from_schema("k", {"name": "N"})
    assert isinstance(f, StringField)


def test_create_field_name_fallback_to_key():
    f = create_field_from_schema("my_key", {"type": "string"})
    assert f.name == "my_key"


def test_build_fields():
    schema = {
        "host": {"type": "string", "name": "Host", "default": "localhost"},
        "port": {"type": "integer", "name": "Port", "default": 8080},
        "debug": {"type": "switch", "name": "Debug"},
    }
    fields = build_fields(schema)
    assert len(fields) == 3
    types = {f.key: f.type for f in fields}
    assert types["host"] == ConfigType.String
    assert types["port"] == ConfigType.Integer
    assert types["debug"] == ConfigType.Switch


def test_build_fields_skips_non_dict_values():
    schema = {
        "valid": {"type": "string"},
        "skip_str": "not a dict",
        "skip_int": 123,
    }
    fields = build_fields(schema)
    assert len(fields) == 1
    assert fields[0].key == "valid"
