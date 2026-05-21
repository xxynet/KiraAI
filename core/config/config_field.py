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
    Textarea = "textarea"
    ModelSelect = "model_select"
    MultiSelect = "multi_select"
    Section = "section"


class BaseConfigField:
    type: ConfigType

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        """
        Base class for configuration fields.

        :param key: The unique key for the field.
        :param name: The name of the field (shown on WebUI).
        :param hint: A hint or description for the field.
        :param default: The default value for the field (optional).
        :param locales: Optional dict of locale overrides, e.g. {"zh": {"name": "...", "hint": "..."}}.
        """
        self.key = key
        self.name = name
        self.hint = hint
        self.default = default
        self.locales = locales or {}

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "type": self.type.value,
            "default": self.default,
            "hint": self.hint,
        }
        if self.locales:
            data["locales"] = self.locales
        if isinstance(self, EnumField):
            data["options"] = list(self.options)
        if isinstance(self, MultiSelectField):
            if getattr(self, "options", None):
                data["options"] = list(self.options)
        if isinstance(self, SectionField):
            data["collapsed"] = self.collapsed
            data["fields"] = {f.key: f.to_dict() for f in self.fields}
        if isinstance(self, EditorField) and getattr(self, "language", None):
            data["language"] = self.language
        if isinstance(self, ModelSelectField) and getattr(self, "model_type", None):
            data["model_type"] = self.model_type
        return data


class ConfigSection:
    def __init__(self, name: str, hint: str, fields: list[BaseConfigField], fold: bool = False):
        self.name = name
        self.hint = hint
        self.fields = fields
        self.fold = fold


class StringField(BaseConfigField):
    type = ConfigType.String

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class IntField(BaseConfigField):
    type = ConfigType.Integer

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class FloatField(BaseConfigField):
    type = ConfigType.Float

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class SensitiveField(BaseConfigField):
    """Sensitive content, e.g. api key"""
    type = ConfigType.Sensitive

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class ListField(BaseConfigField):
    type = ConfigType.List

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default if isinstance(default, list) else [], locales)


class EnumField(BaseConfigField):
    type = ConfigType.Enum

    def __init__(self, key: str, name: str, hint: str, options, default=None, locales: dict = None):
        super().__init__(key, name, hint, default if default in options else options[0], locales)
        self.options = list(options)


class SwitchField(BaseConfigField):
    type = ConfigType.Switch

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default if isinstance(default, bool) else False, locales)


class JsonField(BaseConfigField):
    type = ConfigType.Json

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default if default else {}, locales)


class MarkdownField(BaseConfigField):
    type = ConfigType.Markdown

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class YamlField(BaseConfigField):
    type = ConfigType.Yaml

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class EditorField(BaseConfigField):
    type = ConfigType.Editor

    def __init__(self, key: str, name: str, hint: str, default=None, language: str = None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)
        self.language = language


class TextareaField(BaseConfigField):
    type = ConfigType.Textarea

    def __init__(self, key: str, name: str, hint: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)


class ModelSelectField(BaseConfigField):
    type = ConfigType.ModelSelect

    def __init__(self, key: str, name: str, hint: str, model_type: str, default=None, locales: dict = None):
        super().__init__(key, name, hint, default, locales)
        self.model_type = model_type


class MultiSelectField(BaseConfigField):
    type = ConfigType.MultiSelect

    def __init__(self, key: str, name: str, hint: str, options, default=None, locales: dict = None):
        super().__init__(key, name, hint, default if isinstance(default, list) else [], locales)
        self.options = list(options)


class SectionField(BaseConfigField):
    type = ConfigType.Section

    def __init__(self, key: str, name: str, hint: str, fields: list = None, collapsed: bool = False, locales: dict = None):
        super().__init__(key, name, hint, default=None, locales=locales)
        self.fields = fields or []
        self.collapsed = collapsed


def create_field_from_schema(key: str, schema: dict) -> BaseConfigField:
    field_type = schema.get("type", "string")
    name = schema.get("name") or key
    hint = schema.get("hint", "")
    default = schema.get("default")
    options = schema.get("options")
    locales = schema.get("locales", {})

    if field_type in ("string", "text"):
        if options:
            return EnumField(key=key, name=name, hint=hint, options=options, default=default, locales=locales)
        return StringField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "sensitive":
        return SensitiveField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type in ("integer", "int"):
        return IntField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "float":
        return FloatField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "list":
        return ListField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "enum":
        return EnumField(key=key, name=name, hint=hint, default=default, options=options, locales=locales)

    if field_type == "switch":
        return SwitchField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "json":
        return JsonField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "markdown":
        return MarkdownField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "yaml":
        return YamlField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "editor":
        language = schema.get("language")
        return EditorField(key=key, name=name, hint=hint, default=default, language=language, locales=locales)

    if field_type == "textarea":
        return TextareaField(key=key, name=name, hint=hint, default=default, locales=locales)

    if field_type == "model_select":
        model_type = schema.get("model_type", "llm")
        return ModelSelectField(key=key, name=name, hint=hint, model_type=model_type, default=default, locales=locales)

    if field_type == "multi_select":
        return MultiSelectField(key=key, name=name, hint=hint, options=options or [], default=default, locales=locales)

    if field_type == "section":
        collapsed = schema.get("collapsed", False)
        nested = schema.get("fields", {})
        child_fields = build_fields(nested) if isinstance(nested, dict) else []
        return SectionField(key=key, name=name, hint=hint, fields=child_fields, collapsed=collapsed, locales=locales)

    return StringField(key=key, name=name, hint=hint, default=default, locales=locales)


def build_fields(schema: dict) -> list[BaseConfigField]:
    fields: list[BaseConfigField] = []
    for key, value in schema.items():
        if isinstance(value, dict):
            field_ = create_field_from_schema(key, value)
            if field_:
                fields.append(field_)
    return fields
