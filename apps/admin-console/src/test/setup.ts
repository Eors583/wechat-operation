import { afterEach, vi } from 'vitest'
import { config } from '@vue/test-utils'
import ElementPlus from 'element-plus'

config.global.plugins = [ElementPlus]

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

class ResizeObserverMock {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

Object.defineProperty(window, 'ResizeObserver', { writable: true, value: ResizeObserverMock })
Object.defineProperty(globalThis, 'ResizeObserver', { writable: true, value: ResizeObserverMock })
Object.defineProperty(Element.prototype, 'scrollIntoView', { writable: true, value: vi.fn() })

afterEach(() => {
  sessionStorage.clear()
  localStorage.clear()
})
