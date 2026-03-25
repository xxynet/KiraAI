<div align="center">

# ✨ KiraAI

点亮数字生命灵魂

[English](/README.md) | 简体中文

[🧭 文档](https://docs.kira-ai.top/zh/)

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/) [![Releases](https://img.shields.io/github/v/release/xxynet/KiraAI)](https://github.com/xxynet/KiraAI/releases) [![Commit](https://img.shields.io/github/last-commit/xxynet/KiraAI?color=green)]() [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/xxynet/KiraAI) [![QQ群](https://custom-icon-badges.demolab.com/badge/QQ群-874381335-00BFFF?style=flat&logo=tencent-qq)](https://qm.qq.com/q/eZBJu9wfFC) [![Discord](https://custom-icon-badges.demolab.com/badge/Discord-KiraAI-00BFFF?style=flat&logo=icons8-discord-48)](https://discord.gg/tPRNggzR)

</div>

KiraAI，一个模块化、跨平台的 AI 数字生命项目，以数字生命为中心，连接大语言模型（LLM）与多种聊天平台（QQ、Telegram 等）。

## 🚀 功能特性
- 专为拟人场景优化
- 可自定义的 LLM 提供商与模型
- 灵活的消息发送机制，丰富的消息元素支持
- 附加功能，可自行拓展数字生命能力边界
- Function Calling（函数调用）
- 持久化记忆

## 🧩 架构说明
- `core/`：配置、LLM、提示词、记忆、日志的编排中心
- `data/`：运行期数据
    - `config/`：适配器、模型、提供商、贴纸等 INI/JSON 配置
- `scripts/`：便捷启动脚本
- `webui/`: Web管理界面

## 📷 截图

![alt text](/screenshots/webui-light-cn.png)

![alt text](/screenshots/webui-dark-cn.png)

<details>
<summary>📸 聊天截图</summary>

![alt text](/screenshots/image01.jpg)

![alt text](/screenshots/image02.png)

![alt text](/screenshots/image03.png)

![alt text](/screenshots/image04.png)

![alt text](/screenshots/image05.png)

![alt text](/screenshots/image06.png)

</details>

> [!IMPORTANT]
> 本项目在活跃开发期间，可能会有 **破坏性更新**

## 📦 环境要求
- Python 3.10+ （推荐 3.10-3.12）
- Windows、macOS 或 Linux

## 🛠️ 安装与初始化
1. 克隆本仓库。
2. 进入 KiraAI 文件夹

## ▶️ 运行
可通过以下方式启动 KiraAI（venv）：
- Windows 批处理：`scripts\run.bat`
- Linux 脚本：`scripts/run.sh`（先赋予可执行权限）

Linux 赋权并运行：
```bash
chmod +x scripts/run.sh
scripts/run.sh
```

您也可以自行使用`uv`, `conda`等包管理器运行

## ⚙️ 配置项
运行项目后进入WebUI配置
- 提供商
- 适配器
- 人设
...

## 🗂️ 项目结构
```
KiraAI/
  core/               # 配置/LLM/日志/记忆/提示词 管理器
  data/               # 记忆，表情包，配置文件
  scripts/            # 启动脚本
  main.py           # 主启动入口
```

## 🐞 故障排查
- 查看WebUI系统日志选项卡种的报错信息

## ✨ Star History
[![Star History Chart](https://api.star-history.com/svg?repos=xxynet/KiraAI&type=date&legend=top-left)](https://www.star-history.com/#xxynet/KiraAI&type=date&legend=top-left)

