from typing import Optional
import requests


def get_latest_release(owner: str, repo: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    response = requests.get(url, timeout=5)

    if response.status_code == 200:
        data = response.json()
        return {
            "tag_name": data.get("tag_name"),
            "name": data.get("name"),
            "body": data.get("body"),
            "html_url": data.get("html_url"),
            "published_at": data.get("published_at")
        }
    else:
        print(f"Failed to get latest release：{response.status_code}")
        return None


def clone_repo(owner: str, repo: str, proxy: Optional[str] = None):
    pass


if __name__ == '__main__':
    print(get_latest_release("xxynet", "KiraAI"))
