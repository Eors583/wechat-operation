import { Capacitor } from '@capacitor/core'
import { capacitorPlatform } from './capacitor'
import { electronPlatform } from './electron'
import { webPlatform } from './web'

export const platform = window.desktopBridge
  ? electronPlatform
  : Capacitor.isNativePlatform()
    ? capacitorPlatform
    : webPlatform
