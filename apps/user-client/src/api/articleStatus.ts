import type { ArticleStatus } from './types'

const labels: Record<ArticleStatus, string> = {
  editing: '编辑中',
  local_draft: '本地草稿',
  wechat_draft: '公众号草稿',
  published: '已发布',
  publishing: '发布处理中',
  wechat_draft_queued: '草稿排队中',
  wechat_draft_submitting: '正在写入草稿箱',
  wechat_draft_reconciling: '草稿结果核对中',
  wechat_draft_unknown: '草稿结果未知',
  wechat_draft_failed: '草稿写入失败',
  wechat_draft_cancelled: '草稿写入已取消',
  publish_queued: '发布排队中',
  publish_submitting: '正在发布',
  publish_reconciling: '发布结果核对中',
  publish_unknown: '发布结果未知',
  publish_failed: '发布失败',
  publish_cancelled: '发布已取消',
}

const processing = new Set<ArticleStatus>([
  'publishing',
  'wechat_draft_queued',
  'wechat_draft_submitting',
  'wechat_draft_reconciling',
  'publish_queued',
  'publish_submitting',
  'publish_reconciling',
])
const attention = new Set<ArticleStatus>([
  'wechat_draft_unknown',
  'wechat_draft_failed',
  'wechat_draft_cancelled',
  'publish_unknown',
  'publish_failed',
  'publish_cancelled',
])

export const articleStatusLabel = (status: ArticleStatus) => labels[status]
export const articleStatusColor = (status: ArticleStatus) => {
  if (attention.has(status)) return 'negative'
  if (processing.has(status)) return 'warning'
  if (status === 'published' || status === 'wechat_draft') return 'positive'
  return 'info'
}
