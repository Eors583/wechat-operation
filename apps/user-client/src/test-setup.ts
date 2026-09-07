import { config } from '@vue/test-utils'
import {
  Dialog,
  Notify,
  QAvatar,
  QBadge,
  QBanner,
  QBtn,
  QCard,
  QCardActions,
  QCardSection,
  QDialog,
  QIcon,
  QSeparator,
  Quasar,
} from 'quasar'

config.global.plugins = [
  [
    Quasar,
    {
      components: {
        QAvatar,
        QBadge,
        QBanner,
        QBtn,
        QCard,
        QCardActions,
        QCardSection,
        QDialog,
        QIcon,
        QSeparator,
      },
      plugins: { Dialog, Notify },
    },
  ],
]

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
})
