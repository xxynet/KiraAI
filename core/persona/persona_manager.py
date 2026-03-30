from core.utils.path_utils import get_data_path

ALLOWED_FORMATS = ('text', 'markdown', 'json', 'yaml')


class PersonaManager:
    def __init__(self):
        self.persona_path = get_data_path() / "persona.txt"
        self._format_path = get_data_path() / "persona_format.txt"
        self.persona_str = ""
        self._format = "text"

        """init persona prompt"""
        self.reload_persona()

    def get_persona(self) -> str:
        """
        Get persona text
        :return: str
        """
        return self.persona_str

    def update_persona(self, text):
        self.persona_str = text
        with open(self.persona_path, 'w', encoding="utf-8") as f:
            f.write(text)

    def set_format(self, fmt: str):
        if fmt in ALLOWED_FORMATS:
            self._format = fmt
            self._format_path.write_text(fmt, encoding="utf-8")

    def reload_persona(self):
        if not self.persona_path.exists():
            self.persona_path.write_text("")
        with open(self.persona_path, 'r', encoding="utf-8") as f:
            persona = f.read()
        self.persona_str = persona
        if self._format_path.exists():
            saved_fmt = self._format_path.read_text(encoding="utf-8").strip()
            if saved_fmt in ALLOWED_FORMATS:
                self._format = saved_fmt
