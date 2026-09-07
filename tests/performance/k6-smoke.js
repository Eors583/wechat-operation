import crypto from 'k6/crypto'
import execution from 'k6/execution'
import http from 'k6/http'
import { check, sleep } from 'k6'

const profile = __ENV.PROFILE || 'smoke'
const baseUrl = (__ENV.BASE_URL || 'http://localhost:9000').replace(/\/$/, '')
const accessToken = __ENV.ACCESS_TOKEN || ''
const adminToken = __ENV.ADMIN_ACCESS_TOKEN || ''
const taskIds = (__ENV.TASK_IDS || '').split(',').map((value) => value.trim()).filter(Boolean)
const runIds = (__ENV.RUN_IDS || '').split(',').map((value) => value.trim()).filter(Boolean)
const jobIds = (__ENV.JOB_IDS || '').split(',').map((value) => value.trim()).filter(Boolean)
const duration = __ENV.DURATION || '30s'
const vus = Number(__ENV.VUS || (profile === 'ai' ? 50 : 20))
const rate = Number(__ENV.RATE || 50)

const profileScenarios = {
  smoke: { executor: 'constant-vus', exec: 'ordinaryReads', vus: 1, duration: '10s' },
  api: {
    executor: 'constant-arrival-rate', exec: 'ordinaryReads', rate, timeUnit: '1s',
    duration, preAllocatedVUs: Math.max(10, vus), maxVUs: Math.max(50, vus * 4),
  },
  library: { executor: 'constant-vus', exec: 'libraryReads', vus, duration },
  sse: { executor: 'constant-vus', exec: 'sseReconnects', vus, duration },
  upload: { executor: 'constant-vus', exec: 'uploads', vus, duration },
  worker: { executor: 'constant-vus', exec: 'workerReads', vus, duration },
  ai: { executor: 'constant-vus', exec: 'aiQueue', vus, duration },
}

if (!profileScenarios[profile]) throw new Error(`Unsupported PROFILE: ${profile}`)

export const options = {
  scenarios: { [profile]: profileScenarios[profile] },
  thresholds: {
    checks: ['rate>0.99'],
    http_req_failed: ['rate<0.01'],
    'http_req_duration{endpoint:ordinary}': ['p(95)<300'],
    'http_req_duration{endpoint:library}': ['p(95)<300'],
    'http_req_duration{endpoint:ai_accept}': ['p(95)<1000'],
    'http_req_duration{endpoint:upload_register}': ['p(95)<1000'],
  },
}

const authHeaders = (token = accessToken) => ({
  Accept: 'application/json',
  Authorization: `Bearer ${token}`,
})
const uniqueId = (prefix) => `${prefix}-${execution.vu.idInTest}-${execution.scenario.iterationInTest}`
const selected = (values) => values[execution.scenario.iterationInTest % values.length]
const jsonResponse = (response) => {
  try { return response.json() } catch { return null }
}

export function setup() {
  const needsUser = ['library', 'sse', 'upload', 'ai'].includes(profile)
  if (needsUser && !accessToken) throw new Error(`${profile} profile requires ACCESS_TOKEN`)
  if (profile === 'sse' && !runIds.length) throw new Error('sse profile requires RUN_IDS')
  if (profile === 'ai' && !taskIds.length) throw new Error('ai profile requires TASK_IDS')
  if (profile === 'worker' && (!adminToken || !jobIds.length)) {
    throw new Error('worker profile requires ADMIN_ACCESS_TOKEN and JOB_IDS')
  }
}

export function ordinaryReads() {
  const ready = http.get(`${baseUrl}/health/ready`, { tags: { endpoint: 'ordinary' } })
  check(ready, { 'ready endpoint succeeds': (response) => response.status === 200 })
  const settings = http.get(`${baseUrl}/api/v1/public-settings`, {
    tags: { endpoint: 'ordinary' },
  })
  check(settings, { 'public settings succeeds': (response) => response.status === 200 })
  sleep(0.1)
}

export function libraryReads() {
  const query = encodeURIComponent(__ENV.LIBRARY_QUERY || '')
  const response = http.get(`${baseUrl}/api/v1/library-items?limit=50&query=${query}`, {
    headers: authHeaders(), tags: { endpoint: 'library' },
  })
  check(response, { 'library list succeeds': (value) => value.status === 200 })
  sleep(0.1)
}

export function sseReconnects() {
  const response = http.get(`${baseUrl}/api/v1/ai-runs/${selected(runIds)}/events`, {
    headers: { ...authHeaders(), 'Last-Event-ID': __ENV.LAST_EVENT_ID || '0' },
    tags: { endpoint: 'sse' }, timeout: __ENV.SSE_TIMEOUT || '30s',
  })
  check(response, {
    'SSE resumes successfully': (value) => value.status === 200,
    'SSE response is event stream': (value) => String(value.headers['Content-Type'] || '').includes('text/event-stream'),
    'SSE contains sequenced events': (value) => /\nid:\s*\d+/m.test(String(value.body || '')),
  })
}

export function uploads() {
  const payload = `wechat-ai-upload-${uniqueId('payload')}`
  const digest = crypto.sha256(payload, 'hex')
  const key = uniqueId('upload')
  const registered = http.post(`${baseUrl}/api/v1/uploads`, JSON.stringify({
    filename: `${key}.txt`, mime_type: 'text/plain', size_bytes: payload.length, sha256: digest,
  }), {
    headers: { ...authHeaders(), 'Content-Type': 'application/json', 'Idempotency-Key': key },
    tags: { endpoint: 'upload_register' },
  })
  const body = jsonResponse(registered)
  const partUrl = body?.part_urls?.[0]
  check(registered, {
    'upload registration succeeds': (value) => value.status === 201,
    'upload part URL returned': () => typeof partUrl === 'string' && partUrl.length > 0,
  })
  if (!partUrl) return
  const absolutePartUrl = partUrl.startsWith('http') ? partUrl : `${baseUrl}${partUrl}`
  const uploaded = http.put(absolutePartUrl, payload, {
    headers: { 'Content-Type': 'text/plain' }, tags: { endpoint: 'upload_part' },
  })
  const etag = uploaded.headers.ETag || uploaded.headers.Etag || uploaded.headers.etag
  check(uploaded, {
    'upload part succeeds': (value) => value.status >= 200 && value.status < 300,
    'upload ETag returned': () => typeof etag === 'string' && etag.length > 0,
  })
  if (!etag) return
  const completed = http.post(`${baseUrl}/api/v1/uploads/${body.upload.id}/complete`, JSON.stringify({
    size_bytes: payload.length,
    sha256: digest,
    completed_parts: [{ part_number: 1, etag }],
    save_to_library: true,
  }), {
    headers: { ...authHeaders(), 'Content-Type': 'application/json', 'Idempotency-Key': `${key}-complete` },
    tags: { endpoint: 'upload_complete' },
  })
  check(completed, { 'upload completion succeeds': (value) => value.status === 200 })
}

export function workerReads() {
  const response = http.get(`${baseUrl}/admin-api/v1/jobs/${selected(jobIds)}`, {
    headers: authHeaders(adminToken), tags: { endpoint: 'worker' },
  })
  check(response, { 'worker job status succeeds': (value) => value.status === 200 })
  sleep(0.1)
}

export function aiQueue() {
  const key = uniqueId('ai')
  const response = http.post(`${baseUrl}/api/v1/tasks/${selected(taskIds)}/messages`, JSON.stringify({
    text: __ENV.AI_PROMPT || '围绕组织变革写一篇简短公众号文章。',
    client_message_id: key,
  }), {
    headers: { ...authHeaders(), 'Content-Type': 'application/json', 'Idempotency-Key': key },
    tags: { endpoint: 'ai_accept' }, timeout: __ENV.AI_ACCEPT_TIMEOUT || '15s',
  })
  const body = jsonResponse(response)
  check(response, {
    'AI run accepted': (value) => value.status === 202,
    'AI run id returned': () => typeof body?.ai_run?.id === 'string',
  })
  sleep(Number(__ENV.AI_THINK_TIME_SECONDS || 1))
}
