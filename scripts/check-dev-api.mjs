import assert from 'node:assert/strict'

// Run with the dev backend, gateway, and both standalone frontends started.
// Empty login payloads exercise routing without credentials or login attempts.
for (const [port, path] of [
  [8000, '/api/v1/auth/login'],
  [9000, '/api/v1/auth/login'],
  [9000, '/admin-api/v1/auth/login'],
  [9003, '/api/v1/auth/login'],
  [9004, '/admin-api/v1/auth/login'],
]) {
  const url = `http://127.0.0.1:${port}${path}`
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    signal: AbortSignal.timeout(10000),
  })
  assert.equal(response.status, 422, `${url}: expected backend validation response`)
  assert.match(response.headers.get('content-type') ?? '', /application\/json/)
  assert.ok(response.headers.get('x-request-id'), `${url}: missing backend request ID`)
  console.log(`PASS ${url}: backend reachable (422 validation, not a network error)`)
}
