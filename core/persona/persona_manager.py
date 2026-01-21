from core.utils.path_utils import get_data_path


class PersonaManager:
    def __init__(self):
        self.persona_path = get_data_path() / "persona.txt"
        self.persona_str = ""

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

    def reload_persona(self):
        if not self.persona_path.exists():
            self.persona_path.write_text("")
        with open(self.persona_path, 'r', encoding="utf-8") as f:
            persona = f.read()
        self.persona_str = persona
