-- Canonical idempotent schema for the independent PostgreSQL + pgvector retrieval database.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TABLE IF NOT EXISTS retrieval_chunks (
  id varchar(36) PRIMARY KEY,
  owner_id varchar(36) NOT NULL,
  project_id varchar(36),
  document_id varchar(36) NOT NULL,
  source_type varchar(40) NOT NULL DEFAULT 'document',
  source_name varchar(255) NOT NULL,
  section_id varchar(36),
  section_title varchar(255),
  page_no integer,
  start_ms integer,
  end_ms integer,
  chunk_no integer NOT NULL,
  chunking_version varchar(40) NOT NULL,
  text text NOT NULL,
  token_count integer NOT NULL,
  embedding halfvec(1024) NOT NULL,
  embedding_model varchar(120) NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (
    to_tsvector('simple'::regconfig, coalesce(text, ''))
  ) STORED,
  indexed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, chunk_no)
);

ALTER TABLE retrieval_chunks ADD COLUMN IF NOT EXISTS section_title varchar(255);
ALTER TABLE retrieval_chunks ADD COLUMN IF NOT EXISTS start_ms integer;
ALTER TABLE retrieval_chunks ADD COLUMN IF NOT EXISTS end_ms integer;

CREATE INDEX IF NOT EXISTS ix_retrieval_chunks_scope
  ON retrieval_chunks (owner_id, project_id, document_id);
CREATE INDEX IF NOT EXISTS ix_retrieval_chunks_fulltext
  ON retrieval_chunks USING gin (search_vector);
CREATE INDEX IF NOT EXISTS ix_retrieval_chunks_trigram
  ON retrieval_chunks USING gin (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_retrieval_chunks_embedding_hnsw
  ON retrieval_chunks USING hnsw (embedding halfvec_cosine_ops)
  WITH (m = 16, ef_construction = 128);

CREATE TABLE IF NOT EXISTS retrieval_queries (
  id varchar(36) PRIMARY KEY,
  owner_id varchar(36) NOT NULL,
  task_id varchar(36),
  original_query text NOT NULL,
  normalized_query text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}'::jsonb,
  embedding_model varchar(120) NOT NULL,
  embedding_request_id varchar(180),
  rerank_request_id varchar(180),
  total_duration_ms integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_retrieval_queries_owner_created
  ON retrieval_queries (owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_results (
  query_id varchar(36) NOT NULL,
  chunk_id varchar(36) NOT NULL,
  fulltext_score double precision,
  vector_score double precision,
  fused_score double precision NOT NULL,
  rerank_score double precision,
  rank integer NOT NULL,
  entered_context boolean NOT NULL DEFAULT false,
  PRIMARY KEY (query_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS ix_retrieval_results_query_rank
  ON retrieval_results (query_id, rank);
