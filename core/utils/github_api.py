from typing import Optional
import httpx
import asyncio


async def get_latest_release(owner: str, repo: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"Failed to get latest release: {e}")
            return None

    data = resp.json()
    return {
        "tag_name": data.get("tag_name"),
        "name": data.get("name"),
        "body": data.get("body"),
        "html_url": data.get("html_url"),
        "published_at": data.get("published_at")
    }


def clone_repo(owner: str, repo: str, proxy: Optional[str] = None):
    pass


if __name__ == '__main__':
    print(asyncio.run(get_latest_release("xxynet", "KiraAI")))
