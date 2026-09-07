# WeChat AI Platform Backend

Python 3.12 FastAPI modular monolith shared by the user and administration clients.
It keeps the two authentication domains separate, scopes every user resource to the
authenticated owner, records high-risk idempotency keys, and emits transactional Outbox
events for Celery workers.

## Local start

```powershell
docker compose -f ../../deploy/compose/compose.dev.yml up -d --build
```

Development and production both use Docker PostgreSQL: `business-db` for business data
and `retrieval-db` for the separate pgvector index. SQLite is rejected outside isolated
tests (`APP_ENV=test`); there is no local-file fallback. Prefer the Compose backend on
port 8000. If running the backend on the host, explicitly export the two PostgreSQL URLs
from `.env.example` with credentials matching the root `.env`, and use the same token and
model encryption secrets as Compose. Run `uv run alembic upgrade head` before the API
starts. Do not start a second database for the admin console.
`MOCK_EXTERNAL_SERVICES=true` keeps model, object storage, SMS, and WeChat
operations explicit and non-production: mocked WeChat operations are recorded as `mocked`
and never reported as externally successful.

Web login keeps the rotating refresh token in `ua_session` and uses the script-readable
`ua_csrf` double-submit cookie. Windows/iOS/Android login returns the rotating refresh token
in the JSON body and does not create browser cookies. Every request or worker task creates its
own SQLAlchemy `AsyncSession`; sessions are never shared across concurrent tasks.

## Stable workflow contracts

- File upload is `POST /api/v1/uploads` → part upload → `POST .../complete`. Clients poll
  `GET /api/v1/documents/{id}` until `completed`; `failed` and `blocked_external` are terminal.
  `POST /api/v1/uploads` requires `Idempotency-Key`; its response declares
  `part_size_bytes`. Each uploaded part must retain the response `ETag`, and completion sends
  the complete contiguous `{part_number, etag}` list. The storage adapter finalizes the
  multipart upload before object size/hash verification. Mock upload URLs are usable local
  HTTP PUT endpoints. With both mock and inline-worker flags
  enabled, UTF-8 text/Markdown/CSV/HTML is read from those uploaded bytes as
  `parser_version=mock-text-bytes-v1`, while PPTX text is extracted per slide as
  `parser_version=local-pptx-xml-v1`; other formats return explicitly labelled
  `mock-metadata-v1` content. Neither mode claims a real malware scan, OCR or ASR. A production
  adapter must perform the actual scan, parse, OCR/ASR and index.
  Parsed text is split with versioned settings (default 800 characters and 120-character
  overlap), then the dedicated embedding worker writes vectors only to the independent
  retrieval PostgreSQL database. Business rows retain ownership, source text and index state
  but not the production vector payload.
- A message may contain up to 20 `document_ids` and 20 HTTPS/HTTP `links`. Completed,
  owner-scoped documents are frozen into the AI context. Links are frozen as untrusted URL
  strings only: this service does not fetch or claim to ingest arbitrary webpages.
- AI output and article versions use the shared canonical Tiptap/ProseMirror schema. The
  renderer preserves the supported StarterKit/Link/Image nodes and marks and only emits
  allow-listed, grammar-validated style tokens. Lead, body, highlight, and caption paragraphs
  remain standard `paragraph` nodes and select their module through
  `attrs.module=lead|body|highlight|caption`; custom node types are not part of the contract.
- Every AI run freezes the selected documents, current article baseline, latest deterministic
  task summary, recent messages, project requirements, matching personal/project preferences,
  prompt version, skill version, and model route. A follow-up run versions the same current
  article with optimistic locking instead of silently creating an unrelated article.
- New article runs classify intent at the deterministic API boundary instead of spending a
  model request on classification. Simple articles go directly to generation; planning is
  reserved for runs with source documents, external knowledge, an existing article, or an
  explicit request of at least 3,000 Chinese characters. Content checking remains in the main
  path, while model-based memory/preference enrichment is emitted through the transactional
  Outbox after the article version is committed, so it cannot delay `article.ready`.
- Task detail includes only the latest 30 messages in chronological order and exposes
  `messages_next_cursor`. Older history is loaded from
  `GET /api/v1/tasks/{task_id}/messages?cursor=...&limit=...`; each page is chronological and
  `next_cursor` continues toward older messages for prepend-style clients.
- `POST /api/v1/articles/{id}/revisions` creates an idempotent, asynchronous AI replacement
  proposal. Read it from `GET /api/v1/article-revisions/{id}`; it never mutates the article.
  Applying an accepted proposal is an explicit optimistic-locking `PUT .../content` request.
- A cover must be an owner-scoped image whose scan status is ready/clean. A newly uploaded
  image returns `COVER_ASSET_NOT_READY` until processing is complete.
- WeChat draft/publish aggregation mirrors the operation fact. Only an explicit provider
  `succeeded` result becomes `wechat_draft` or `published`; queued, unknown, failed and mock
  outcomes retain their corresponding `wechat_draft_*` or `publish_*` states. A `submitting`
  checkpoint and any returned draft identifier are committed before the next external side
  effect; a crash or indeterminate response must be reconciled and is never blindly replayed.

## Processes

```powershell
uv run uvicorn app.main:app
uv run celery -A app.celery_app:celery worker -Q ai,files,embedding,wechat,sync,maintenance
uv run celery -A app.celery_app:celery beat
```

The AI worker consumes both the foreground generation task and the non-blocking memory
enrichment task. Before production traffic, publish model routes for `article_generation`,
`article_planning`, `content_check`, and `memory_summary`; publish `vision` as well when image
inputs are enabled. Use the strongest long-output model for `article_generation` and smaller,
low-latency models for the three auxiliary routes. A user-selected model controls only the
main generation call. Auxiliary routes use their published platform routes; legacy
installations without an auxiliary route temporarily fall back to the selected deployment.

For the web and native clients, configure exact origins. Production permits HTTPS origins and
the single native iOS WebView origin `capacitor://localhost`; all other non-HTTPS origins and
wildcards are rejected:

```powershell
$env:ALLOWED_ORIGINS='https://app.example.com,capacitor://localhost'
```

The bundled S3-compatible storage adapter requires the bucket CORS policy to expose the
`ETag` response header. It records the expected SHA-256 and request token as object metadata,
uses presigned `UploadPart` URLs, completes with the client-returned ETags, then checks both
object length and the frozen SHA-256 metadata before accepting the upload.

Create the first administrator with an account and password:

```powershell
uv run wechat-admin create-admin --username admin --password 'change-me-now'
```

## Verification

```powershell
uv run ruff check .
uv run mypy app
uv run pytest
uv run alembic upgrade head
uv run python scripts/export_openapi.py
```

The generated `openapi.json` is the integration contract for all clients. User routes live
under `/api/v1`, administrator routes under `/admin-api/v1`, and signed WeChat callbacks
under `/callbacks/v1`; credentials from one authentication domain are rejected by the other.

## External integration boundary

The repository ships Provider protocols, explicit local mocks, and production adapters for
OpenAI-compatible Responses/Chat Completions, OpenAI-compatible Moderations, S3-compatible
multipart storage, and signed internal HTTP services for verification delivery, file
scan/parser/OCR/ASR, controlled layout extraction, and the WeChat gateway. API and Celery
workers use the same `build_providers` factory, so a task cannot silently select a different
integration from the request process. Production startup rejects every mock mode, incomplete
URL/secret-reference configuration, insecure cookies, SQLite, and non-HTTPS browser origins.

Set `MODEL_PROVIDER_MODE=openai_compatible`, `MODEL_API_STYLE=responses` (or
`chat_completions`), `CONTENT_SAFETY_PROVIDER_MODE=openai`, `STORAGE_PROVIDER_MODE=s3`,
`EMBEDDING_PROVIDER_MODE=openai_compatible`, `RERANK_PROVIDER_MODE=http`,
`VERIFICATION_PROVIDER_MODE=http`, `DOCUMENT_PROVIDER_MODE=http`,
`LAYOUT_PROVIDER_MODE=http`, and `WECHAT_PROVIDER_MODE=direct` (or `http_gateway` when a
separate gateway is intentionally deployed). Direct WeChat authorization credentials are
loaded from the published encrypted admin configuration or the `WECHAT_*` environment
values documented in the suite README. `WECHAT_PUBLIC_BASE_URL` derives both callback URLs;
the optional domain-verification filename/content pair serves the downloaded
`MP_verify_*.txt` file from the public root. Other credentials are
resolved only through `env:VARIABLE_NAME` references; they are not returned by admin APIs or
written into audit details. See `.env.example` for the complete required variable set.

`RETRIEVAL_DATABASE_URL` must point to a PostgreSQL database separate from `DATABASE_URL`.
Run `uv run python scripts/migrate_retrieval.py` during deployment. The idempotent retrieval
schema uses `halfvec(1024)`, owner/project/document filtering, GIN full-text and trigram
indexes, and an HNSW cosine index. Query execution retrieves full-text Top 50 and vector Top
50, fuses them with RRF to Top 30, reranks, applies source diversity, freezes Top 8 by default,
and records exactly which chunks entered model context.

Each signed internal service verifies `X-Service-Timestamp` and
`X-Service-Signature=HMAC-SHA256(secret, timestamp + "\\n" + canonical_json_body)`. The
verification, document, layout, and WeChat gateway routes are respectively
`/v1/verifications`, `/v1/documents/process`, `/v1/layouts/extract`, and the WeChat routes
`/v1/authorization-url`, `/v1/drafts`, `/v1/publishes`, `/v1/reconcile`. A draft/publish
transport timeout carries a stable request identifier into the `unknown` checkpoint and must
be reconciled; it is never submitted again blindly.

The callback API accepts official WeChat XML/AES ticket and authorization callbacks in direct
mode and retains the normalized HMAC boundary for a separately deployed gateway. The
development rate limiter is process-local; multi-replica deployments must replace it with a
shared Redis-backed limiter.
