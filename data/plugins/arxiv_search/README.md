# arXiv Search（arXiv 论文助手）

KiraAI 插件：arXiv 论文查询、翻译与下载。数据源为 arXiv 官方 API
`export.arxiv.org/api/query`（Atom XML 格式），PDF 下载自 `arxiv.org/pdf/{id}`，
LaTeX 源码下载自 `arxiv.org/e-print/{id}`。

## 功能

| 命令 | 说明 |
| --- | --- |
| `/arxiv search <关键词> [-t]` | 搜索论文，返回标题、摘要（截断）、作者、arXiv ID、分类、PDF 链接，默认 5 条；加 `-t` 附带标题译文 |
| `/arxiv get <arXiv ID> [-t]` | 获取单篇论文完整详情（标题/全部作者/摘要/日期/分类/PDF）；加 `-t` 附带标题与摘要译文 |
| `/arxiv tr <arXiv ID>` | 将单篇论文的标题与摘要翻译成中文（使用默认 LLM，失败友好兜底） |
| `/arxiv dl <arXiv ID> [多个ID]` | 下载 PDF 到 `data/files/arxiv_pdf/` 并返回本地路径 |
| `/arxiv src <arXiv ID>` | 下载 LaTeX 源码包（e-print，tar.gz/tex.gz/tex）到 `data/files/arxiv_src/` 并返回本地路径 |
| `/arxiv translate-latex <arXiv ID>` | 提交 LaTeX 全文翻译任务（后台异步，见下文「后台异步翻译」） |
| `/arxiv translate-status <任务ID>` | 查询翻译任务状态（别名 `trs` / `tstatus`） |
| `/arxiv help` | 查看帮助 |

同时注册 8 个 LLM 工具：`arxiv_search`、`arxiv_get`、`arxiv_translate`、`arxiv_download`、`arxiv_src`、
`arxiv_translate_latex`（后台异步翻译，提交后立即返回任务 ID，完成后自动推送 PDF）、
`query_arxiv_translate_task`（查询翻译任务状态）、`parse_arxiv_command`，
LLM 可主动调用查询/翻译/下载，也可代为执行斜杠命令。

## 用法示例

```
@bot /arxiv search large language model
@bot /arxiv search au:vaswani AND ti:attention -t
@bot /arxiv get 1706.03762 -t
@bot /arxiv tr 1706.03762
@bot /arxiv dl 1706.03762
@bot /arxiv dl 1706.03762 2105.02723
@bot /arxiv src 1706.03762
@bot /arxiv translate-latex 1706.03762
@bot /arxiv translate-status TR1700000000A1B2C3
```

群聊需先 @ 机器人；私聊无需 @。斜杠命令白名单留空 = 所有用户可用。

## 后台异步翻译（LaTeX 全文翻译）

`/arxiv translate-latex <ID>`（或 LLM 工具 `arxiv_translate_latex`）对论文 LaTeX 源码执行
「下载源码 → 解压 → 分块翻译 → 编译 PDF」完整流程。**该流程在后台异步执行，不是同步等待**：

### 提交式调用（立即返回任务 ID）

调用 `arxiv_translate_latex` 后立即返回任务 ID（形如 `TR1700000000A1B2C3`），不阻塞当前对话：

```
📖 翻译任务已提交，任务ID：TR1700000000A1B2C3
🔖 arXiv ID：1706.03762
⚙️ 后台流程：下载源码 → 解压 → 分块翻译 → 编译 PDF
📨 执行期间会推送翻译进度，完成后自动发送 PDF 路径。
🔎 查询进度：query_arxiv_translate_task(task_id="TR1700000000A1B2C3")
```

- 同一会话对同一论文已有进行中任务（pending/running）时，重复提交会被拒绝并提示已有任务 ID。
- 任务记录保存在插件进程内（模块级注册表），插件卸载/系统关闭时在途任务会被取消并标记为 `failed`。

### 进度推送规则

后台执行期间会向**发起会话**推送进度消息：

- 分块翻译块数 ≤ 10：每完成一块推送一次；
- 块数 > 10：每完成 5 块推送一次；
- 最后一块（完成）必然推送。

推送示例：`📖 翻译进度 8/12 块`

### 完成自动回传 PDF

任务完成后自动向发起会话推送完成消息，包含译文 TeX 路径与编译产物 PDF 路径：

```
✅ 翻译完成（分块数/翻译方式说明）
📄 译文 TeX：data/files/arxiv_src/1706.03762_work/1706.03762_zh.tex
📕 PDF：data/files/arxiv_src/1706.03762_work/1706.03762_zh.pdf
🔖 任务ID：TR1700000000A1B2C3
```

失败时也会推送失败通知（含错误信息），可用 `query_arxiv_translate_task` 查询详情。

### 任务状态字段

任务记录包含以下字段（`query_arxiv_translate_task` 返回）：

| 字段 | 说明 |
| --- | --- |
| `task_id` | 任务 ID（`TR` + 时间戳 + 短随机码） |
| `arxiv_id` | 论文 arXiv ID |
| `status` | `pending` 排队中 / `running` 进行中 / `done` 已完成 / `failed` 已失败 |
| `stage` | `queued` 排队 / `download` 下载源码 / `extract` 解压源码 / `translate` 分块翻译 / `compile` 编译 PDF / `done` 完成 |
| `total_blocks` | 分块翻译总块数（翻译阶段起有值） |
| `done_blocks` | 已翻译完成的块数 |
| `result_pdf` | 翻译完成后的 PDF 路径（完成后有值） |
| `result_tex` | 译文 TeX 文件路径（完成后有值） |
| `error` | 失败原因（`failed` 时有值） |
| `note` | 翻译方式等说明 |
| `created_at` / `updated_at` | 创建/更新时间戳 |

### 查询工具：query_arxiv_translate_task

**参数**：`task_id`（必填，字符串）——由 `arxiv_translate_latex` 提交时返回。

**返回示例**（进行中）：

```
🔄 翻译任务 TR1700000000A1B2C3
📄 arXiv ID：1706.03762
🛠 当前阶段：分块翻译
📖 翻译进度：8/12 块
⏱ 耗时：42s
```

**返回示例**（已完成）：

```
✅ 翻译任务 TR1700000000A1B2C3
📄 arXiv ID：1706.03762
🛠 当前阶段：完成
📖 翻译进度：12/12 块
📕 PDF：data/files/arxiv_src/1706.03762_work/1706.03762_zh.pdf
📄 译文 TeX：data/files/arxiv_src/1706.03762_work/1706.03762_zh.tex
📝 说明：...
⏱ 耗时：98s
```

**返回示例**（失败）：

```
❌ 翻译任务 TR1700000000A1B2C3
📄 arXiv ID：1706.03762
🛠 当前阶段：分块翻译
📖 翻译进度：3/12 块
🚨 错误：ArxivApiError: 编译 PDF 失败: ...
⏱ 耗时：35s
```

### 斜杠命令

- `/arxiv translate-latex <arXiv ID>`（别名 `trl`）——提交翻译任务，立即返回任务 ID；
- `/arxiv translate-status <任务ID>`（别名 `trs` / `tstatus`）——查询任务状态，等价于 `query_arxiv_translate_task`。

> 前置条件：使用 LaTeX 全文翻译需在服务器安装 TeX Live（`pdflatex` 可用）。

## 配置（插件设置页）

- `max_results`：默认搜索条数（1-20，默认 5）
- `request_timeout`：API 请求超时秒数（默认 15）
- `sort_by`：默认排序（relevance / submittedDate / lastUpdatedDate）
- `download_dir`：PDF 保存目录（默认 `data/files/arxiv_pdf`）
- `source_dir`：LaTeX 源码保存目录（默认 `data/files/arxiv_src`）
- `command_prefix`：斜杠命令前缀（默认 `/arxiv`）
- `enable_commands`：斜杠命令总开关
- `slash_whitelist`：斜杠命令白名单 QQ 列表

翻译设置（`翻译设置` 配置分组）：

- `translate_enabled`：是否启用 LLM 翻译（默认开；关闭后 `-t`/`--translate` 参数与工具的 translate 参数不生效）
- `translate_lang`：标题/摘要翻译目标语言（zh/en/ja/ko，默认 zh）
- `translate_backend`：**LaTeX 正文翻译**（`/arxiv translate-latex`）使用的翻译后端：
  `auto`（默认，按翻译插件配置自动回退）/ `baidu` / `deepl` / `google` / `aliyun` / `local`
- `translate_local_model`：仅当 `translate_backend=local` 时生效的本地模型名（如 `qwen2.5:7b`，默认空）。

> **关于 `translate_backend` / `translate_local_model` 的说明**：这两个配置只作用于 LaTeX 全文翻译
> （`arxiv_translate_latex` / `/arxiv translate-latex`），标题/摘要翻译（`arxiv_translate` / `-t` 参数）始终走默认 LLM。
> LaTeX 正文翻译实际调用翻译插件（kira-ai-plugin-translate）的 `translate` 接口，`translate_backend` 会透传为其
> `backend` 参数（`local` 时 `translate_local_model` 透传为 `model`）。当前翻译插件接口暂不支持按调用覆盖本地模型，
> 因此 `translate_backend=local` 时若 `translate_local_model` 留空，将使用翻译插件自身的 `local_model` 配置；
> 若翻译插件后续支持 `model` 参数，本配置将自动透传覆盖。

## 技术要点

- 解析 Atom XML：标题/摘要/作者/发布日期/更新日期/分类/PDF 链接（`link[title=pdf]`）
- 遵守 arXiv API 礼貌间隔（两次请求 >= 3 秒），模块级锁 + 时间戳节流
- PDF / 源码并发下载（信号量上限 3），临时文件 + `os.replace` 原子落盘
- PDF 校验 `%PDF` 魔数；源码校验非空且非 HTML 错误页，扩展名按 Content-Type / 魔数推断
- 结果 TTL 缓存（10 分钟），减少重复 API 调用
- arXiv ID 白名单正则校验（`\d{4}\.\d{4,5}` 或 `cat/\d{7}`，可带 `vN`），防止路径穿越
- 搜索支持 arXiv 高级语法：`ti:` / `au:` / `abs:` / `cat:` / `all:` 前缀与 AND/OR/NOT
- 标题/摘要翻译使用默认 LLM（`get_default_llm_client()`），失败友好提示「翻译服务不可用，先试试 /arxiv get」
- LaTeX 全文翻译为后台异步任务：模块级任务注册表 + asyncio 后台任务，加锁读写任务状态，持有任务引用防止 GC 误取消；
  分块翻译批量调用翻译插件，按块推送进度，完成自动回传 PDF
- `/arxiv translate-latex` 的 LaTeX 正文翻译调用翻译插件（kira-ai-plugin-translate），后端与本地模型通过
  `translate_backend` / `translate_local_model` 配置控制；backend 透传至翻译插件的 translate 接口

## 文件清单

```
data/plugins/arxiv_search/
├── manifest.json   # 插件元信息
├── schema.json     # 配置项定义
├── main.py         # 插件主逻辑
├── __init__.py     # 包标记
└── README.md       # 本文件
```

下载的 PDF 存放于 `data/files/arxiv_pdf/`，LaTeX 源码存放于 `data/files/arxiv_src/`
（文件名 = 经 `_sanitize_id` 处理后的 arXiv ID，旧式 ID 的 `/` 替换为 `_`）。
