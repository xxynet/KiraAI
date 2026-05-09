# SubAgent 机制设计文档

> Issue: [#33 [FEATURE] 引入 SubAgent 机制：内部委派式多代理协作](https://github.com/xxynet/KiraAI/issues/33)  
> 作者: Qixuan112  
> 日期: 2026-05-09  
> 状态: 设计中 / MVP 实现

---

## 1. 背景与目标

### 1.1 当前痛点
- **复杂任务耦合**: 主 Agent 遇到需要特定能力（写代码、画图、深度研究）的任务时，所有逻辑都堆在主流程中，难以维护与复用。
- **缺乏专业分工**: 无法为不同领域配置专用模型、工具和提示词。
- **上下文管理粗暴**: 容易造成 token 浪费或信息泄漏。

### 1.2 目标
引入 **SubAgent（子代理）** 机制，使 KiraAI 主 Agent 能将专业任务委派给具备 **独立人格、工具集和上下文** 的内部虚拟会话实体，实现多代理协作。

---

## 2. 核心概念

| 术语 | 说明 |
|------|------|
| **SubAgent** | 内部虚拟代理，拥有独立的 Persona、工具集、模型配置和生命周期。 |
| **内部会话通道** | 不经过外部 Adapter 的虚拟会话，Session ID 使用 `sub:dm:<subagent_id>` 前缀。 |
| **correlation_id** | 用于主 Agent 与 SubAgent 之间消息匹配的唯一标识。 |
| **上下文策略** | 主 Agent 向 SubAgent 传递上下文的方式：`none` / `summary` / `full` / `selective`。 |

---

## 3. 架构设计

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        主 Agent (Main Agent)                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │  AgentExecutor │   │  LLMClient   │   │  SessionManager  │  │
│  └──────┬──────┘    └──────┬──────┘    └────────┬────────┘  │
│         │                  │                     │           │
│         │  1. session_send(sub:dm:code_expert)   │           │
│         │────────────────────────────────────────>│           │
│         │                  │                     │           │
│         │  4. await 回复    │                     │           │
│         │<────────────────────────────────────────│           │
│         │                  │                     │           │
└─────────┼──────────────────┼─────────────────────┼───────────┘
          │                  │                     │
          │  2. 路由到 SubAgent                   │
          │                  │                     │
┌─────────┼──────────────────┼─────────────────────┼───────────┐
│         ▼                  │                     ▼           │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              SubAgent Router (SessionManager 扩展)        │  │
│  │     识别 sub:dm:* 前缀，将消息分发给对应 SubAgent         │  │
│  └─────────────────────────┬───────────────────────────────┘  │
│                            │                                  │
│                            │  3. 独立执行                     │
│                            ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                    SubAgent 实例                          │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │  │
│  │  │ Persona  │  │ ToolSet  │  │ LLMModel │  │ Memory  │ │  │
│  │  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              SubAgent Registry & Factory                  │  │
│  │     管理 SubAgent 配置、生命周期、注册/注销               │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### 3.2 模块职责

| 模块 | 职责 |
|------|------|
| `core.subagent.registry` | SubAgent 注册表，管理配置、生命周期、实例化。 |
| `core.subagent.subagent` | SubAgent 实体类，封装独立执行逻辑。 |
| `core.subagent.router` | 路由层，挂载到 SessionManager，识别 `sub:dm:*` 前缀。 |
| `core.subagent.client` | 主 Agent 侧调用客户端，提供同步/异步调用接口。 |
| `core.chat.session_manager` | 扩展：增加 SubAgent 路由分支。 |
| `core.plugin.plugin_context` | 扩展：暴露 `subagent_registry` 供插件注册。 |

---

## 4. 详细设计

### 4.1 会话 ID 与路由

```python
# SubAgent 会话 ID 格式
sub:dm:<subagent_id>

# 示例
sub:dm:code_expert
sub:dm:research_assistant
```

**路由规则**:
1. `SessionManager` 在 `fetch_memory` / `write_memory` / `update_memory` 等方法中，检查 session 是否以 `sub:dm:` 开头。
2. 若是，将操作转发给 `SubAgentRouter`，不经过外部 Adapter，不写入 `chat_memory.json`（或写入隔离存储）。
3. SubAgent 的 memory 存储在独立命名空间，避免污染主会话。

### 4.2 通信流程（同步 MVP）

```
主 Agent                              SubAgent
  │                                    │
  │  ① session_send()                 │
  │  {correlation_id: "abc123",        │
  │   task_type: "code_review",        │
  │   content: "...",                  │
  │   metadata: {parent_context:       │
  │              "summary"}}           │
  │───────────────────────────────────>│
  │                                    │
  │                           ② 构建独立请求
  │                           ③ 调用专属 LLM
  │                           ④ 执行工具
  │                                    │
  │  ⑤ 回复到同一会话                  │
  │  {correlation_id: "abc123",        │
  │   status: "success",               │
  │   result: "..."}                   │
  │<───────────────────────────────────│
  │                                    │
  │  ⑥ 通过 correlation_id 匹配结果    │
  │  ⑦ 返回给主 Agent 调用方           │
```

### 4.3 消息格式

**请求消息 (SubAgentRequest)**:
```python
@dataclass
class SubAgentRequest:
    correlation_id: str      # 唯一匹配 ID
    task_type: str           # 任务类型标识
    content: str             # 任务内容
    metadata: dict           # 扩展元数据
    # metadata.parent_context: str  # 上下文策略
    # metadata.max_tokens: int      # 限制 token
    # metadata.tools: list[str]     # 指定可用工具
```

**回复消息 (SubAgentResponse)**:
```python
@dataclass
class SubAgentResponse:
    correlation_id: str
    status: Literal["success", "timeout", "tool_error", "model_error", "cancelled"]
    result: str              # 执行结果文本
    attachments: list        # 附件（Image/File/Record）
    metadata: dict           # 执行元数据（耗时、token 用量等）
    err: Optional[str]       # 错误详情
```

### 4.4 上下文策略

主 Agent 在 `metadata.parent_context` 中指定：

| 策略 | 说明 |
|------|------|
| `none` | 完全隔离，SubAgent 只接收当前任务内容。 |
| `summary` | 主 Agent 传递一段摘要作为上下文。 |
| `full` | 传递限定 token / 轮次的历史记录。 |
| `selective` | 传递指定消息 ID 列表对应的内容。 |

### 4.5 SubAgent 配置

```python
@dataclass
class SubAgentConfig:
    subagent_id: str
    name: str
    description: str
    persona: str                    # 角色设定
    model_uuid: Optional[str]       # 指定模型，默认使用 default_llm
    tools: list[str]                # 可用工具名列表
    max_steps: int = 3              # 最大 Agent 步数
    timeout: float = 60.0           # 调用超时（秒）
    context_strategy: str = "none"  # 默认上下文策略
    lifecycle: Literal["session", "app_scope", "on_demand"] = "on_demand"
```

**生命周期**:
- `session`: 随主会话创建/销毁，状态隔离。
- `app_scope`: 应用全局单例，多会话共享。
- `on_demand`: 每次调用创建新实例，执行完即销毁（MVP 默认）。

### 4.6 错误处理与降级

| 状态码 | 含义 | 主 Agent 行为 |
|--------|------|---------------|
| `success` | 执行成功 | 直接使用结果 |
| `timeout` | 执行超时 | 重试（最多 2 次，线性退避）或降级输出 |
| `tool_error` | 工具调用失败 | 重试或返回错误摘要 |
| `model_error` | LLM 调用失败 | 重试或切换 fallback 模型 |
| `cancelled` | 被主动取消 | 终止当前任务分支 |

### 4.7 并发与嵌套限制

- **禁止嵌套**: SubAgent 内部不允许再调用其他 SubAgent，避免死锁。
- **会话隔离**: 多用户通过独立会话实例隔离，状态不污染。
- **并发控制**: 每个 SubAgent 实例内部串行执行，不同实例可并行。

---

## 5. 与现有模块集成

### 5.1 SessionManager 扩展

```python
# core/chat/session_manager.py

class SessionManager:
    def __init__(self, ...):
        # ... existing code ...
        self.subagent_router: Optional[SubAgentRouter] = None

    def register_subagent_router(self, router: SubAgentRouter):
        self.subagent_router = router

    def fetch_memory(self, session: str):
        if session.startswith("sub:dm:"):
            if self.subagent_router:
                return self.subagent_router.fetch_memory(session)
            return []
        # ... existing code ...

    def write_memory(self, session: str, memory: list):
        if session.startswith("sub:dm:"):
            if self.subagent_router:
                self.subagent_router.write_memory(session, memory)
            return
        # ... existing code ...
```

### 5.2 事件总线复用

SubAgent 的执行结果通过标准 `MessageReceived` 事件机制回传（内部模拟），主 Agent 通过 `correlation_id` 在事件层匹配。

### 5.3 Plugin 注册接口

```python
# core/plugin/plugin_context.py

class PluginContext:
    # ... existing code ...
    subagent_registry: Optional[SubAgentRegistry] = None

    def register_subagent(self, config: SubAgentConfig):
        if self.subagent_registry:
            self.subagent_registry.register(config)
```

插件示例：
```python
from core.plugin import register
from core.subagent import SubAgentConfig

@register.subagent(
    subagent_id="code_expert",
    name="代码专家",
    description="擅长编写、审查和重构代码",
    persona="你是一位资深软件工程师...",
    tools=["read_file", "write_file", "execute_shell"],
    lifecycle="on_demand"
)
class CodeExpertPlugin:
    pass
```

### 5.4 可观测性

- **日志**: 所有 SubAgent 调用记录 `correlation_id`、耗时、状态码。
- **指标**: 接入现有统计系统，记录调用次数、成功率、平均耗时。
- **追踪**: 在日志中保持 `correlation_id` 贯穿主 Agent → SubAgent → 工具调用全链路。

---

## 6. MVP 实现步骤

| 步骤 | 内容 | 优先级 |
|------|------|--------|
| 1 | 实现 `SubAgentConfig`、`SubAgentRequest`、`SubAgentResponse` 数据模型 | P0 |
| 2 | 实现 `SubAgentRegistry`（注册、配置加载、生命周期管理） | P0 |
| 3 | 实现 `SubAgent` 实体类（封装独立 AgentExecutor、ToolSet、Memory） | P0 |
| 4 | 实现 `SubAgentRouter`，挂载到 `SessionManager` | P0 |
| 5 | 实现 `SubAgentClient`，提供同步调用接口（`await call()`） | P0 |
| 6 | 实现 `correlation_id` 消息匹配与超时控制 | P0 |
| 7 | 实现基础错误回复与重试/降级逻辑 | P1 |
| 8 | 实现一个 `on_demand` 示例 SubAgent（如 `code_expert`） | P1 |
| 9 | 扩展 `PluginContext` 暴露注册接口 | P1 |
| 10 | 编写单元测试与集成测试 | P1 |
| 11 | 预留异步回调扩展接口 | P2 |

---

## 7. 文件结构规划

```
core/
├── subagent/
│   ├── __init__.py
│   ├── models.py          # SubAgentConfig, SubAgentRequest, SubAgentResponse
│   ├── registry.py        # SubAgentRegistry
│   ├── subagent.py        # SubAgent 实体类
│   ├── router.py          # SubAgentRouter
│   ├── client.py          # SubAgentClient（主 Agent 侧调用）
│   └── builtin/           # 内置示例 SubAgent
│       └── code_expert.py
```

---

## 8. 风险与注意事项

1. **循环调用**: 必须严格禁止 SubAgent 嵌套调用，在 `SubAgentClient.call()` 中通过调用栈深度检测拦截。
2. **Token 爆炸**: `full` 上下文策略需强制限制最大 token 数，避免主会话历史过长导致子代理成本失控。
3. **Memory 隔离**: SubAgent 的 memory 必须物理隔离，不可与主会话共享同一 `chat_memory.json` 条目。
4. **超时处理**: 同步等待模式下，超时后需清理挂起的 `correlation_id`，避免内存泄漏。
5. **与 Skills 的关系**: Skills 是无状态指令集合，SubAgent 是有状态代理实体。后续统一注册层设计时再明确二者边界。

---

## 9. 附录

### 9.1 相关代码文件
- `core/chat/session_manager.py`
- `core/message_manager.py`
- `core/agent/agent_executor.py`
- `core/event_bus.py`
- `core/plugin/plugin_context.py`
- `core/plugin/plugin_registry.py`

### 9.2 参考 Issue
- [KiraAI #33 - 引入 SubAgent 机制](https://github.com/xxynet/KiraAI/issues/33)
