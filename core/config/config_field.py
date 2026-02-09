from enum import Enum


class ConfigType(Enum):
    String = "string"
    Integer = "integer"
    Float = "float"
    Sensitive = "sensitive"
    List = "list"
    Enum = "enum"
    Switch = "switch"
    Json = "json"
    Markdown = "markdown"
    Yaml = "yaml"
    Editor = "editor"


class BaseConfigField:
    type: ConfigType

    def __init__(self, key: str, name: str, hint: str, default=None):
        """
        Base class for configuration fields.

        :param key: The unique key for the field.
        :param name: The name of the field (shown on WebUI).
        :param hint: A hint or description for the field.
        :param default: The default value for the field (optional).
        """
        self.key = key
        self.name = name
        self.hint = hint
        self.default = default

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "type": self.type.value,
            "default": self.default,
            "hint": self.hint,
        }
        if isinstance(self, EnumField):
            data["options"] = list(self.options)
        if isinstance(self, EnumField):
            if getattr(self, "options", None):
                data["options"] = list(self.options)
        if isinstance(self, EditorField) and getattr(self, "language", None):
            data["language"] = self.language
        return data


class ConfigSection:
    def __init__(self, name: str, hint: str, fields: list[BaseConfigField], fold: bool = False):
        self.name = name
        self.hint = hint
        self.fields = fields
        self.fold = fold


class StringField(BaseConfigField):
    type = ConfigType.String

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default)


class IntField(BaseConfigField):
    type = ConfigType.Integer

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default)


class FloatField(BaseConfigField):
    type = ConfigType.Float

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default)


class SensitiveField(BaseConfigField):
    """Sensitive content, e.g. api key"""
    type = ConfigType.Sensitive

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default)


class ListField(BaseConfigField):
    type = ConfigType.List

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default if isinstance(default, list) else [])


class EnumField(BaseConfigField):
    type = ConfigType.Enum

    def __init__(self, key: str, name: str, hint: str, options, default=None):
        super().__init__(key, name, hint, default if default in options else options[0])
        self.options = list(options)


class SwitchField(BaseConfigField):
    type = ConfigType.Switch

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default if isinstance(default, bool) else False)


class JsonField(BaseConfigField):
    type = ConfigType.Json

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default if default else {})


class MarkdownField(BaseConfigField):
    type = ConfigType.Markdown

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default)


class YamlField(BaseConfigField):
    type = ConfigType.Yaml

    def __init__(self, key: str, name: str, hint: str, default=None):
        super().__init__(key, name, hint, default)


class EditorField(BaseConfigField):
    type = ConfigType.Editor

    def __init__(self, key: str, name: str, hint: str, default=None, language: str = None):
        super().__init__(key, name, hint, default)
        self.language = language


def create_field_from_schema(key: str, schema: dict) -> BaseConfigField:
    field_type = schema.get("type", "string")
    name = schema.get("name") or key
    hint = schema.get("hint", "")
    default = schema.get("default")
    options = schema.get("options")

    if field_type in ("string", "text"):
        if options:
            return EnumField(key=key, name=name, hint=hint, options=options, default=default)
        return StringField(key=key, name=name, hint=hint, default=default)

    if field_type == "sensitive":
        return SensitiveField(key=key, name=name, hint=hint, default=default)

    if field_type in ("integer", "int"):
        return IntField(key=key, name=name, hint=hint, default=default)

    if field_type == "float":
        return FloatField(key=key, name=name, hint=hint, default=default)

    if field_type == "list":
        return ListField(key=key, name=name, hint=hint, default=default)

    if field_type == "enum":
        return EnumField(key=key, name=name, hint=hint, default=default, options=options)

    if field_type == "switch":
        return SwitchField(key=key, name=name, hint=hint, default=default)

    if field_type == "json":
        return JsonField(key=key, name=name, hint=hint, default=default)

    if field_type == "markdown":
        return MarkdownField(key=key, name=name, hint=hint, default=default)

    if field_type == "yaml":
        return YamlField(key=key, name=name, hint=hint, default=default)

    if field_type == "editor":
        language = schema.get("language")
        return EditorField(key=key, name=name, hint=hint, default=default, language=language)

    return StringField(key=key, name=name, hint=hint, default=default)


def build_fields(schema: dict) -> list[BaseConfigField]:
    fields: list[BaseConfigField] = []
    for key, value in schema.items():
        if isinstance(value, dict):
            field_ = create_field_from_schema(key, value)
            if field_:
                fields.append(field_)
    return fields
