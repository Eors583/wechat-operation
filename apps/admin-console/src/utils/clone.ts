import { toRaw } from 'vue'

/** Clone serializable form data even when Vue has wrapped it in a reactive Proxy. */
export function cloneData<T>(value: T): T {
  return structuredClone(toRaw(value))
}
