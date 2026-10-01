from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image as PILImage
from bilibili_api import Credential, comment, dynamic, homepage, search, session, user
from bilibili_api.utils import network
from bilibili_api.utils.picture import Picture


def get_bilibili_client() -> network.BiliAPIClient:
    """Configure the SDK-owned transport shared by adapters and QR login."""
    network.select_client("aiohttp")
    client = network.get_client()
    client.get_wrapped_session().headers["Accept-Encoding"] = "gzip, deflate"
    return client


class _BiliBiliPicture(Picture):
    """Upload without the SDK's shared temporary filename or image re-download."""

    @classmethod
    def from_picture(cls, picture: Picture) -> _BiliBiliPicture:
        return cls(
            height=picture.height, width=picture.width, imageType=picture.imageType,
            size=picture.size, url=picture.url, content=picture.content,
        )

    def _prepare_upload(self) -> tuple[TemporaryDirectory, network.BiliAPIFile]:
        with PILImage.open(BytesIO(self.content)) as image:
            mime = image.get_format_mimetype()
        directory = TemporaryDirectory(prefix="kira-bilibili-upload-")
        try:
            path = Path(directory.name) / "image"
            path.write_bytes(self.content)
            return directory, network.BiliAPIFile(path=str(path), mime_type=mime)
        except BaseException:
            directory.cleanup()
            raise

    def _to_biliapifile(self) -> network.BiliAPIFile:
        return self._upload_file

    async def prepare_upload(self) -> TemporaryDirectory:
        prepare = asyncio.create_task(asyncio.to_thread(self._prepare_upload))
        try:
            directory, self._upload_file = await asyncio.shield(prepare)
        except asyncio.CancelledError:
            directory, _ = await prepare
            await asyncio.to_thread(directory.cleanup)
            raise
        return directory

    async def upload(self, credential: Credential) -> Picture:
        directory = await self.prepare_upload()
        try:
            result = await dynamic.upload_image(self, credential)
            self.height = result["image_height"]
            self.width = result["image_width"]
            self.url = result["image_url"]
            self.size = result["img_size"]
            return self
        finally:
            await asyncio.to_thread(directory.cleanup)


class BiliBiliClient:
    """Bilibili-native operations bound to one adapter account.

    The SDK still owns the shared transport; this object must not close it.
    """

    def __init__(self, credential: Credential, *, timeout: float = 60.0):
        self._credential = credential
        self.timeout = timeout

    async def _request(
        self, operation: str, call: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        try:
            get_bilibili_client()
            return await asyncio.wait_for(call(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Bilibili {operation} timed out") from None
        except Exception:
            raise RuntimeError(f"Bilibili {operation} failed") from None

    async def get_recommended_videos(self) -> dict[str, Any]:
        return await self._request(
            "recommendation fetching", lambda: homepage.get_videos(credential=self._credential),
        )

    async def get_dynamic_page(self, *, offset: str = "", page: int = 1) -> dict[str, Any]:
        return await self._request(
            "dynamic fetching", lambda: dynamic.get_dynamic_page_info(
                credential=self._credential, _type=dynamic.DynamicType.ALL,
                offset=offset, pn=page,
            ),
        )

    async def get_user_dynamics(self, uid: int, *, offset: str = "") -> dict[str, Any]:
        return await self._request(
            "user dynamic fetching", lambda: user.User(uid, credential=self._credential).get_dynamics_new(offset=offset),
        )

    async def get_dynamic_info(self, dynamic_id: int) -> dict[str, Any]:
        return await self._request(
            "dynamic detail fetching", lambda: dynamic.Dynamic(dynamic_id, credential=self._credential).get_info(),
        )

    async def search_by_type(
        self, keyword: str, search_type: search.SearchObjectType, *, page: int = 1, page_size: int = 20,
    ) -> dict[str, Any]:
        # The SDK's search_by_type omits credentials; bind them at its API boundary.
        async def request() -> dict[str, Any]:
            return await network.Api(
                **search.API["search"]["web_search_by_type"], credential=self._credential, wbi=True,
            ).update_params(
                keyword=keyword, search_type=search_type.value, page=page, page_size=page_size,
            ).result
        return await self._request("content searching", request)

    async def send_comment(
        self, text: str, oid: int, type_: comment.CommentResourceType,
        *, root: int | None = None, parent: int | None = None,
        pic: Picture | list[Picture] | None = None,
    ) -> dict[str, Any]:
        """Send a native SDK comment using this account and isolated image files."""
        async def request() -> dict[str, Any]:
            directories = []
            pictures = []
            try:
                for picture in ([pic] if isinstance(pic, Picture) else pic or []):
                    prepared = _BiliBiliPicture.from_picture(picture)
                    directories.append(await prepared.prepare_upload())
                    pictures.append(prepared)
                options = {"pic": pictures} if pictures else {}
                return await comment.send_comment(
                    text=text, oid=oid, type_=type_, root=root, parent=parent,
                    credential=self._credential, **options,
                )
            finally:
                for directory in directories:
                    await asyncio.to_thread(directory.cleanup)
        return await self._request("comment reply", request)

    async def get_comments_lazy(self, oid: int, type_: comment.CommentResourceType) -> dict[str, Any]:
        return await self._request(
            "comment fetching", lambda: comment.get_comments_lazy(
                oid=oid, type_=type_, credential=self._credential,
            ),
        )

    async def get_reply_notifications(
        self, *, cursor_id: int | None = None, cursor_time: int | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "reply notification fetching", lambda: session.get_replies(
                self._credential, last_reply_id=cursor_id, reply_time=cursor_time,
            ),
        )

    async def get_at_notifications(
        self, *, cursor_id: int | None = None, cursor_time: int | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "mention notification fetching", lambda: session.get_at(
                self._credential, last_uid=cursor_id, at_time=cursor_time,
            ),
        )

    async def send_dynamic(self, info: dynamic.BuildDynamic) -> dict[str, Any]:
        """Submit a native dynamic using this account, returning the SDK result."""
        if not isinstance(info, dynamic.BuildDynamic):
            raise TypeError("Bilibili dynamics require BuildDynamic")
        self._credential.raise_for_no_sessdata()
        self._credential.raise_for_no_bili_jct()
        # The SDK mutates content and pictures while sending; isolate each call.
        draft = deepcopy(info)
        draft.pics = [_BiliBiliPicture.from_picture(pic) for pic in draft.pics]
        if draft.time is not None:
            # SDK 17.x replaces scheduling options when comment options exist.
            draft.options["timer_pub_time"] = int(draft.time.timestamp())
        return await self._request(
            "dynamic publishing", lambda: dynamic.send_dynamic(info=draft, credential=self._credential),
        )
