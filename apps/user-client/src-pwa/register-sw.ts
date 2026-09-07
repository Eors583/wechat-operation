import { register } from 'register-service-worker'

register(import.meta.env.QUASAR_SERVICE_WORKER_FILE, {
  error(error) {
    console.error('Service worker registration failed', error)
  },
})
