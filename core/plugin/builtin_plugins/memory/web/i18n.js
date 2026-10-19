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
      'detail.title': '记忆详情',
      'detail.id': '记忆 ID',
      'detail.revision': '修订号',
      'detail.text': '记忆内容',
      'detail.kind': '类型',
      'detail.status': '状态',
      'detail.owner': '归属',
      'detail.owner_key': '归属键',
      'detail.persona': '人格 ID',
      'detail.namespace': '命名空间',
      'detail.session': '会话 ID',
      'detail.source_message': '来源消息',
      'detail.importance': '重要度',
      'detail.core': '核心记忆',
      'detail.origin': '来源',
      'detail.legacy_line': 'core.txt 行号',
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
      'error.invalid_category': '筛选值无效。',
      'error.invalid_priority': '筛选值无效。',
      'error.unknown': '请求失败（{msg}）',
    },

    en: {
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

      'detail.title': 'Memory detail',
      'detail.id': 'Memory ID',
      'detail.revision': 'Revision',
      'detail.text': 'Content',
      'detail.kind': 'Kind',
      'detail.status': 'Status',
      'detail.owner': 'Owner',
      'detail.owner_key': 'Owner key',
      'detail.persona': 'Persona ID',
      'detail.namespace': 'Namespace',
      'detail.session': 'Session ID',
      'detail.source_message': 'Source message',
      'detail.importance': 'Importance',
      'detail.core': 'Core memory',
      'detail.origin': 'Origin',
      'detail.legacy_line': 'core.txt line',
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
      'error.invalid_category': 'The filter value is invalid.',
      'error.invalid_priority': 'The filter value is invalid.',
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
