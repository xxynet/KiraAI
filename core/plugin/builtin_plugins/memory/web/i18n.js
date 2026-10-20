/* ============================================================================
   Default Memory — maintenance page strings (zh / en).

   Locale is driven by the host: /plugin-bridge.js hands the page a
   PluginPageContext containing the WebUI locale and delivers a fresh context
   whenever the user switches language, so the page re-labels itself live.
   Without the host (opening the page directly) the browser language decides.
   ========================================================================= */
;(function () {
  'use strict'

  var STRINGS = {
    zh: {
      'vector.title': '向量检索',
      'vector.note': '在插件配置中开启向量检索并选择远程 Embedding 模型。开启后会将记忆正文和检索词发送给所选服务商；索引在后台构建，失败时继续使用关键词检索。缺少依赖时可在此安装，无需下载本地模型。',
      'vector.model_warning': '请始终使用与建索引时相同的底层模型，模型名称可以不同。维度相同不代表模型相同；实际换模型后，必须手动重建索引。重建会重新请求全部记忆的 Embedding，可能产生较多费用；系统不会因模型名或维度变化自动重建。',
      'vector.dimensions': '索引维度：{expected}；当前返回维度：{actual}。',
      'vector.phase.rebuild_required': '向量维度不一致，已暂停向量检索并回退到关键词检索。请确认模型后，到「统计 → 向量检索」手动重建索引。',
      'vector.reason.dimension_mismatch': '索引已保留，不会自动清空或重建；请确认调用费用后手动操作。',
      'vector.install': '安装向量检索依赖',
      'vector.rebuild': '重建向量索引',
      'vector.progress': '已索引 {indexed} / {total} 条记忆',
      'vector.phase.disabled': '未启用，当前使用本地关键词检索。',
      'vector.phase.starting': '正在检查向量检索环境…',
      'vector.phase.dependency_missing': '缺少向量检索依赖，当前使用关键词检索。',
      'vector.phase.model_missing': 'Embedding 模型不可用，请在插件配置中选择模型，或设置默认 Embedding 模型。',
      'vector.phase.installing': '正在安装依赖…',
      'vector.phase.building': '正在构建向量索引，期间使用关键词检索。',
      'vector.phase.ready': '向量索引已就绪，使用关键词与语义混合检索。',
      'vector.phase.degraded': '向量检索暂不可用，已回退到关键词检索。',
      'vector.reason.embedding_failed': 'Embedding 请求或向量索引处理失败，稍后会重试。可检查模型配置并手动重建索引。',
      'vector.reason.install_failed': '依赖安装失败，请检查网络或 PyPI 镜像后重试。',
      'vector.used_keyword': '本次使用：关键词检索',
      'vector.used_hybrid': '本次使用：关键词与语义混合检索',
      'tab.recall': '模拟召回',
      'recall.persona': '人格（可选）',
      'recall.session': '会话（可选）',
      'recall.title': '测试记忆召回',
      'recall.note': '输入对话内容即可测试，默认检索全部范围，也可按人格和会话筛选。使用与真实对话相同的检索和字符预算规则，不修改记忆、不调用对话模型；启用向量检索时会请求远程 Embedding API。',
      'recall.context_hint': '此处不按本轮发言者隔离，测试结果可能与真实对话不同；无需先发送真实消息。',
      'recall.messages': '最近对话内容',
      'recall.messages_placeholder': '例如：今天想喝点什么？',
      'recall.messages_hint': '每行一条消息，使用最后三条，每条最多 160 字符；留空仅加载核心记忆。',
      'recall.run': '模拟召回',
      'recall.refresh_contexts': '刷新筛选项',
      'recall.idle': '输入对话内容测试召回；人格和会话均可留为全部。',
      'recall.budget': '记忆内容字符：{used} / {budget}',
      'recall.query': '实际检索词',
      'recall.core': '核心记忆',
      'recall.retrieved': '检索记忆（已去重）',
      'recall.truncated': '已按预算截断',
      'recall.details': '查看完整详情',
      'error.invalid_recall': '模拟上下文或消息格式无效，请检查输入。',
      'app.title': '记忆管理',
      'app.subtitle': '对话记忆的检索、状态与归属一览',

      'tab.records': '记忆条目',
      'tab.overview': '统计',

      // generic
      'common.loading': '加载中…',
      'common.retry': '重试',
      'common.refresh': '刷新',
      'common.close': '关闭',
      'common.search': '查询',
      'common.reset': '重置',
      'common.all': '全部',
      'common.select': '请选择',
      'common.no_options': '暂无可选项',
      'common.none': '暂无',
      'common.unknown': '未知',
      'common.load_failed': '加载失败：{msg}',
      'common.expired': '登录已过期，请刷新页面重新登录',
      'common.page_of': '共 {total} 条 · 第 {page}/{pages} 页',
      'common.yes': '是',
      'common.no': '否',
      'common.yes_option': '是',
      'common.no_option': '否',
      // machine values
      'kind.semantic': '语义',
      'kind.episodic': '情景',
      'kind.procedural': '流程',
      'status.active': '生效',
      'status.completed': '已完成',
      'status.cancelled': '已取消',
      'status.superseded': '已取代',
      'owner.user': '用户',
      'owner.group': '群聊',
      'owner.self': '人格',
      'owner.legacy': '旧记忆',
      'origin.conversation': '对话',
      'origin.legacy': 'core.txt',

      // filters
      'filter.title': '筛选',
      'filter.q': '内容搜索',
      'filter.q_placeholder': '输入关键词（支持中英文）',
      'filter.kind': '类型',
      'filter.status': '状态',
      'filter.owner_type': '归属',
      'filter.origin': '来源',
      'filter.core': '核心记忆',

      // table
      'records.title': '记忆条目',
      'records.count': '共 {total} 条',
      'records.empty': '没有符合条件的记忆',
      'records.empty_hint': '记忆会在对话中由模型通过 memory_add 自动写入，或在此放宽筛选条件。',
      'col.text': '内容',
      'col.kind': '类型',
      'col.owner': '归属',
      'col.importance': '重要度',
      'col.status': '状态',
      'col.updated': '更新时间',
      'col.source': '来源会话',
      'records.core_tag': '核心',
      'records.importance_value': '重要度 {value}/5',
      'records.prev': '上一页',
      'records.next': '下一页',

      // detail
      'edit.start': '编辑',
      'edit.cancel': '取消',
      'edit.save': '保存',
      'edit.saving': '保存中…',
      'edit.saved': '已保存，召回将使用更新后的记忆。',
      'edit.reload': '重新加载最新版本',
      'edit.text_hint': '正文不能为空，最多 4000 字符。',
      'edit.expiry_hint': '使用本地时间；留空表示永不过期。',
      'error.invalid_update': '包含不可编辑的字段。',
      'error.invalid_revision': '修订号无效，请重新加载记忆。',
      'error.invalid_text': '正文不能为空，最多 4000 字符，且不能包含空字符。',
      'error.invalid_expiry': '过期时间无效，请重新选择或留空。',
      'error.conflict': '这条记忆已被更新。你的修改仍保留在编辑框中；请先复制需要的内容，再重新加载最新版本。',
      'detail.title': '记忆详情',
      'detail.id': '记忆 ID',
      'detail.revision': '修订号',
      'detail.text': '记忆内容',
      'detail.kind': '类型',
      'detail.status': '状态',
      'detail.owner': '归属',
      'detail.owner_key': '归属键',
      'detail.persona': '人格 ID',
      'detail.adapter': '适配器',
      'detail.namespace': '命名空间',
      'detail.session': '会话 ID',
      'detail.source_message': '来源消息',
      'detail.importance': '重要度',
      'detail.core': '核心记忆',
      'detail.origin': '来源',
      'detail.created': '创建时间',
      'detail.updated': '更新时间',
      'detail.expires': '过期时间',
      'detail.expires_never': '永不过期',
      'detail.expires_expired': '已过期',
      'detail.terms': '索引词数',
      'detail.not_found': '该记忆已不存在',

      // overview
      'overview.title': '统计概览',
      'overview.total': '记忆总数',
      'overview.active': '生效中',
      'overview.inactive': '非生效',
      'overview.core': '核心记忆',
      'overview.expiring': '带过期时间',
      'overview.last_updated': '最近更新',
      'overview.by_status': '按状态',
      'overview.by_kind': '按类型',
      'overview.by_owner': '按归属',
      'overview.by_origin': '按来源',
      'overview.limits': '生效中的运行时设置',
      'overview.limit_core': '每轮核心记忆上限',
      'overview.limit_recall': '每轮检索记忆上限',
      'overview.limit_prompt': '注入字符预算',
      'overview.limit_search': '检索返回字符预算',
      'overview.limit_note': '这些数值在「插件管理 → 默认记忆」的配置表单中修改，保存后立即生效。',
      'overview.settings_link': '打开插件配置',
      'overview.unavailable': '统计暂不可用',

      // errors
      'error.memory_unavailable': '记忆存储尚未就绪，请稍后再试。',
      'error.not_found': '目标记忆不存在。',
      'error.invalid_query': '搜索词无效。',
      'error.invalid_limit': '分页参数无效。',
      'error.invalid_category': '类型、状态或筛选值无效。',
      'error.invalid_priority': '重要度必须为 1–5，核心标记必须为是或否。',
      'error.unknown': '请求失败（{msg}）',
    },

    en: {
      'vector.title': 'Vector retrieval',
      'vector.note': 'Enable vector retrieval and select a remote Embedding model in plugin settings. Memory text and search queries are sent to that provider. Indexing runs in the background; failures fall back to keyword search. Install missing dependencies here. No local model download is needed.',
      'vector.model_warning': 'Keep using the same underlying model that built the index; its name may differ between channels. Equal dimensions do not mean equal models. After changing the underlying model, rebuild the index manually. Rebuilding sends all memories for Embedding again and may incur significant costs. Model names or dimension changes never trigger an automatic rebuild.',
      'vector.dimensions': 'Index dimensions: {expected}; current response dimensions: {actual}.',
      'vector.phase.rebuild_required': 'Vector dimensions differ. Vector retrieval is paused; keyword search remains available. Verify the model, then rebuild manually under Statistics → Vector retrieval.',
      'vector.reason.dimension_mismatch': 'The index is preserved and will not be cleared or rebuilt automatically. Review the API costs before rebuilding manually.',
      'vector.install': 'Install vector dependencies',
      'vector.rebuild': 'Rebuild vector index',
      'vector.progress': '{indexed} / {total} memories indexed',
      'vector.phase.disabled': 'Disabled. Using local keyword search.',
      'vector.phase.starting': 'Checking vector retrieval…',
      'vector.phase.dependency_missing': 'Vector dependencies are missing. Using keyword search.',
      'vector.phase.model_missing': 'Embedding model unavailable. Select a model in plugin settings or configure a default Embedding model.',
      'vector.phase.installing': 'Installing dependencies…',
      'vector.phase.building': 'Building the vector index. Using keyword search until ready.',
      'vector.phase.ready': 'Vector index ready. Using hybrid keyword and semantic search.',
      'vector.phase.degraded': 'Vector retrieval unavailable. Using keyword search.',
      'vector.reason.embedding_failed': 'Embedding or vector index processing failed and will be retried. Check model settings or rebuild the index.',
      'vector.reason.install_failed': 'Dependency installation failed. Check the network or PyPI mirror and retry.',
      'vector.used_keyword': 'Retrieval used: keyword search',
      'vector.used_hybrid': 'Retrieval used: hybrid keyword and semantic search',
      'tab.recall': 'Recall preview',
      'recall.persona': 'Persona (optional)',
      'recall.session': 'Session (optional)',
      'recall.title': 'Test memory recall',
      'recall.note': 'Enter messages to test all memories, or optionally filter by persona and session. Uses the same retrieval and character budget as chat. Does not modify memories or call a chat model; enabling vector retrieval makes remote Embedding API calls.',
      'recall.context_hint': 'This test does not filter by current speakers, so results may differ from chat. No real messages are required.',
      'recall.messages': 'Recent messages',
      'recall.messages_placeholder': 'For example: What should I drink today?',
      'recall.messages_hint': 'One message per line. Uses the last three, up to 160 characters each. Leave empty for core memories only.',
      'recall.run': 'Preview recall',
      'recall.refresh_contexts': 'Refresh filters',
      'recall.idle': 'Enter messages to test recall. Persona and session can both stay set to All.',
      'recall.budget': 'Memory characters: {used} / {budget}',
      'recall.query': 'Effective search query',
      'recall.core': 'Core memories',
      'recall.retrieved': 'Retrieved memories (deduplicated)',
      'recall.truncated': 'Truncated to fit budget',
      'recall.details': 'View full details',
      'error.invalid_recall': 'Invalid preview context or messages. Check the input.',
      'app.title': 'Memory',
      'app.subtitle': 'Browse what your companion remembers, how it is scoped and how it is used',

      'tab.records': 'Memories',
      'tab.overview': 'Statistics',

      'common.loading': 'Loading…',
      'common.retry': 'Retry',
      'common.refresh': 'Refresh',
      'common.close': 'Close',
      'common.search': 'Search',
      'common.reset': 'Reset',
      'common.all': 'All',
      'common.select': 'Select an option',
      'common.no_options': 'No options available',
      'common.none': 'None',
      'common.unknown': 'Unknown',
      'common.load_failed': 'Failed to load: {msg}',
      'common.expired': 'Your session has expired. Refresh the page and sign in again.',
      'common.page_of': '{total} rows · page {page}/{pages}',
      'common.yes': 'Yes',
      'common.no': 'No',
      'common.yes_option': 'Yes',
      'common.no_option': 'No',

      'kind.semantic': 'Semantic',
      'kind.episodic': 'Episodic',
      'kind.procedural': 'Procedural',
      'status.active': 'Active',
      'status.completed': 'Completed',
      'status.cancelled': 'Cancelled',
      'status.superseded': 'Superseded',
      'owner.user': 'User',
      'owner.group': 'Group',
      'owner.self': 'Persona',
      'owner.legacy': 'Legacy',
      'origin.conversation': 'Conversation',
      'origin.legacy': 'core.txt',

      'filter.title': 'Filters',
      'filter.q': 'Search content',
      'filter.q_placeholder': 'Keywords in any language',
      'filter.kind': 'Kind',
      'filter.status': 'Status',
      'filter.owner_type': 'Owner',
      'filter.origin': 'Origin',
      'filter.core': 'Core only',

      'records.title': 'Memories',
      'records.count': '{total} total',
      'records.empty': 'No memories match these filters',
      'records.empty_hint': 'Memories are written by the model through memory_add during conversations, or widen the filters above.',
      'col.text': 'Content',
      'col.kind': 'Kind',
      'col.owner': 'Owner',
      'col.importance': 'Importance',
      'col.status': 'Status',
      'col.updated': 'Updated',
      'col.source': 'Source session',
      'records.core_tag': 'Core',
      'records.importance_value': 'Importance {value}/5',
      'records.prev': 'Previous',
      'records.next': 'Next',

      'edit.start': 'Edit',
      'edit.cancel': 'Cancel',
      'edit.save': 'Save',
      'edit.saving': 'Saving…',
      'edit.saved': 'Saved. Recall will use the updated memory.',
      'edit.reload': 'Reload latest version',
      'edit.text_hint': 'Text is required, up to 4000 characters.',
      'edit.expiry_hint': 'Uses local time. Leave empty for no expiration.',
      'error.invalid_update': 'The request includes fields that cannot be edited.',
      'error.invalid_revision': 'Invalid revision. Reload the memory.',
      'error.invalid_text': 'Text is required, up to 4000 characters, with no null characters.',
      'error.invalid_expiry': 'Invalid expiration time. Choose a valid time or leave it empty.',
      'error.conflict': 'This memory has changed. Your edits are still in the form. Copy anything you need before reloading the latest version.',
      'detail.title': 'Memory detail',
      'detail.id': 'Memory ID',
      'detail.revision': 'Revision',
      'detail.text': 'Content',
      'detail.kind': 'Kind',
      'detail.status': 'Status',
      'detail.owner': 'Owner',
      'detail.owner_key': 'Owner key',
      'detail.persona': 'Persona ID',
      'detail.adapter': 'Adapter',
      'detail.namespace': 'Namespace',
      'detail.session': 'Session ID',
      'detail.source_message': 'Source message',
      'detail.importance': 'Importance',
      'detail.core': 'Core memory',
      'detail.origin': 'Origin',
      'detail.created': 'Created',
      'detail.updated': 'Updated',
      'detail.expires': 'Expires',
      'detail.expires_never': 'Never',
      'detail.expires_expired': 'Expired',
      'detail.terms': 'Indexed terms',
      'detail.not_found': 'This memory no longer exists',

      'overview.title': 'Statistics',
      'overview.total': 'Total memories',
      'overview.active': 'Active',
      'overview.inactive': 'Not active',
      'overview.core': 'Core memories',
      'overview.expiring': 'With expiry',
      'overview.last_updated': 'Last updated',
      'overview.by_status': 'By status',
      'overview.by_kind': 'By kind',
      'overview.by_owner': 'By owner',
      'overview.by_origin': 'By origin',
      'overview.limits': 'Runtime settings in effect',
      'overview.limit_core': 'Core memories per request',
      'overview.limit_recall': 'Retrieved memories per request',
      'overview.limit_prompt': 'Injected character budget',
      'overview.limit_search': 'Search response character budget',
      'overview.limit_note': 'Change these in Add-ons → Default Memory; saved values take effect immediately.',
      'overview.settings_link': 'Open plugin configuration',
      'overview.unavailable': 'Statistics unavailable',

      'error.memory_unavailable': 'The memory store is not ready yet. Try again shortly.',
      'error.not_found': 'That memory does not exist.',
      'error.invalid_query': 'The search term is invalid.',
      'error.invalid_limit': 'The pagination parameters are invalid.',
      'error.invalid_category': 'Invalid type, status, or filter value.',
      'error.invalid_priority': 'Importance must be 1–5 and core must be Yes or No.',
      'error.unknown': 'Request failed ({msg})',
    },
  }

  var I18N = {
    locale: 'en',
    listeners: [],

    normalize: function (value) {
      var raw = String(value || '').toLowerCase()
      if (!raw) return null
      return raw.indexOf('zh') === 0 ? 'zh' : 'en'
    },

    t: function (key, params) {
      var table = STRINGS[I18N.locale] || STRINGS.en
      var template = table[key]
      if (template === undefined) template = STRINGS.en[key]
      if (template === undefined) return key
      if (!params) return template
      return template.replace(/\{(\w+)\}/g, function (match, name) {
        return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
      })
    },

    /** Translate a machine value such as a kind/status/owner; unknown values pass through. */
    value: function (group, raw) {
      var key = group + '.' + raw
      var table = STRINGS[I18N.locale] || STRINGS.en
      if (table[key] !== undefined || STRINGS.en[key] !== undefined) return I18N.t(key)
      return raw === null || raw === undefined || raw === '' ? '—' : String(raw)
    },

    setLocale: function (value) {
      var next = I18N.normalize(value)
      if (!next || next === I18N.locale) return false
      I18N.locale = next
      document.documentElement.setAttribute('lang', next === 'zh' ? 'zh-CN' : 'en')
      I18N.listeners.forEach(function (handler) {
        try { handler(next) } catch (err) { /* keep other listeners alive */ }
      })
      return true
    },

    onChange: function (handler) {
      I18N.listeners.push(handler)
      return function () {
        var index = I18N.listeners.indexOf(handler)
        if (index !== -1) I18N.listeners.splice(index, 1)
      }
    },
  }

  var browser = (navigator.language || '').toLowerCase()
  I18N.locale = browser.indexOf('zh') === 0 ? 'zh' : 'en'
  document.documentElement.setAttribute('lang', I18N.locale === 'zh' ? 'zh-CN' : 'en')

  window.I18N = I18N
  window.PLUGIN_STRINGS = STRINGS
})()
