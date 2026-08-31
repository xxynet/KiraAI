from core.adapter.adapter_utils import IMAdapter


class PluginRegistrationSmokeAdapter(IMAdapter):
    async def start(self):
        pass

    async def stop(self):
        pass

    def get_client(self):
        return None

    async def send_group_message(self, group_id, send_message_obj):
        return None

    async def send_direct_message(self, user_id, send_message_obj):
        return None