import pytest


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param
