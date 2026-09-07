import { ElMessage } from 'element-plus'

type NoticeType = 'positive' | 'negative' | 'warning' | 'info'

export function useAdminNotifier() {
  return {
    notify({ type = 'info', message }: { type?: NoticeType; message: string }): void {
      const elementType = type === 'positive' ? 'success' : type === 'negative' ? 'error' : type
      ElMessage({ type: elementType, message, showClose: true })
    },
  }
}
