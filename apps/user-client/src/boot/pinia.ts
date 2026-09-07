import { createPinia } from 'pinia'
import { defineBoot } from '#q-app'

export default defineBoot(({ app }) => {
  app.use(createPinia())
})
