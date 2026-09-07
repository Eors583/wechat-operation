from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.production_providers import HttpRerankProvider, OpenAICompatibleEmbeddingProvider
from app.providers import EnvironmentSecretProvider
from app.retrieval import PostgresRetrievalBackend, RetrievalHit, RetrievalService


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    owner_id: str
    project_id: str | None
    document_ids: list[str]
    query: str
    expected_chunk_ids: frozenset[str]
    expected_document_ids: frozenset[str]


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def load_cases(path: Path, minimum: int, maximum: int) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            value: Any = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON on line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"Line {line_number} must be a JSON object")
        owner_id = value.get("owner_id")
        query = value.get("query")
        document_ids = value.get("document_ids")
        expected_chunks = value.get("expected_chunk_ids", [])
        expected_documents = value.get("expected_document_ids", [])
        if not isinstance(owner_id, str) or not owner_id:
            raise SystemExit(f"Line {line_number} has no owner_id")
        if not isinstance(query, str) or not query.strip():
            raise SystemExit(f"Line {line_number} has no query")
        if not isinstance(document_ids, list) or not document_ids or not all(
            isinstance(item, str) and item for item in document_ids
        ):
            raise SystemExit(f"Line {line_number} must contain document_ids")
        if not isinstance(expected_chunks, list) or not all(
            isinstance(item, str) and item for item in expected_chunks
        ):
            raise SystemExit(f"Line {line_number} has invalid expected_chunk_ids")
        if not isinstance(expected_documents, list) or not all(
            isinstance(item, str) and item for item in expected_documents
        ):
            raise SystemExit(f"Line {line_number} has invalid expected_document_ids")
        if not expected_chunks and not expected_documents:
            raise SystemExit(f"Line {line_number} must declare at least one expected result")
        project_id = value.get("project_id")
        if project_id is not None and not isinstance(project_id, str):
            raise SystemExit(f"Line {line_number} has invalid project_id")
        cases.append(
            EvaluationCase(
                owner_id=owner_id,
                project_id=project_id,
                document_ids=document_ids,
                query=query.strip(),
                expected_chunk_ids=frozenset(expected_chunks),
                expected_document_ids=frozenset(expected_documents),
            )
        )
    if not minimum <= len(cases) <= maximum:
        raise SystemExit(
            f"Dataset must contain {minimum}-{maximum} non-empty cases; found {len(cases)}"
        )
    return cases


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def recall_at_ten(case: EvaluationCase, hits: list[RetrievalHit]) -> float:
    expected = {
        *(f"chunk:{identifier}" for identifier in case.expected_chunk_ids),
        *(f"document:{identifier}" for identifier in case.expected_document_ids),
    }
    retrieved = {
        *(f"chunk:{hit.chunk_id}" for hit in hits[:10]),
        *(f"document:{hit.document_id}" for hit in hits[:10]),
    }
    return len(expected & retrieved) / len(expected)


def permission_leaks(case: EvaluationCase, hits: list[RetrievalHit]) -> int:
    allowed_documents = set(case.document_ids)
    return sum(hit.document_id not in allowed_documents for hit in hits)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(Path(args.dataset), args.minimum_cases, args.maximum_cases)
    secrets = EnvironmentSecretProvider()
    embedding = OpenAICompatibleEmbeddingProvider(
        api_base=required_environment("EMBEDDING_API_BASE"),
        api_key=secrets.resolve(required_environment("EMBEDDING_API_KEY_REF")),
        model=required_environment("EMBEDDING_MODEL"),
        dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
    )
    rerank = HttpRerankProvider(
        api_base=required_environment("RERANK_API_BASE"),
        api_key=secrets.resolve(required_environment("RERANK_API_KEY_REF")),
        model=required_environment("RERANK_MODEL"),
    )
    backend = PostgresRetrievalBackend(required_environment("RETRIEVAL_DATABASE_URL"))
    service = RetrievalService(backend=backend, embedding=embedding, rerank=rerank)
    pure_durations: list[float] = []
    full_durations: list[float] = []
    pure_recalls: list[float] = []
    full_recalls: list[float] = []
    leaks = 0
    try:
        await backend.check_ready()
        for case in cases:
            embedded = await embedding.embed([case.query])
            pure_started = time.perf_counter()
            pure_hits = await backend.candidates(
                owner_id=case.owner_id,
                project_id=case.project_id,
                document_ids=case.document_ids,
                query=case.query,
                query_vector=embedded.vectors[0],
                limit=10,
            )
            pure_durations.append((time.perf_counter() - pure_started) * 1000)
            pure_recalls.append(recall_at_ten(case, pure_hits))
            leaks += permission_leaks(case, pure_hits)

            full_started = time.perf_counter()
            full_hits = await service.search(
                owner_id=case.owner_id,
                task_id=None,
                project_id=case.project_id,
                document_ids=case.document_ids,
                query=case.query,
                context_count=10,
            )
            full_durations.append((time.perf_counter() - full_started) * 1000)
            full_recalls.append(recall_at_ten(case, full_hits))
            leaks += permission_leaks(case, full_hits)
    finally:
        await backend.dispose()

    report: dict[str, Any] = {
        "dataset_cases": len(cases),
        "permission_leaks": leaks,
        "pure_retrieval": {
            "p50_ms": round(percentile(pure_durations, 0.50), 2),
            "p95_ms": round(percentile(pure_durations, 0.95), 2),
            "recall_at_10": round(sum(pure_recalls) / len(pure_recalls), 4),
        },
        "full_retrieval": {
            "p50_ms": round(percentile(full_durations, 0.50), 2),
            "p95_ms": round(percentile(full_durations, 0.95), 2),
            "recall_at_10": round(sum(full_recalls) / len(full_recalls), 4),
        },
        "thresholds": {
            "pure_p95_ms": args.pure_p95_ms,
            "full_p95_ms": args.full_p95_ms,
            "recall_at_10": args.minimum_recall,
            "permission_leaks": 0,
        },
    }
    failures: list[str] = []
    if report["pure_retrieval"]["p95_ms"] >= args.pure_p95_ms:
        failures.append("pure retrieval P95")
    if report["full_retrieval"]["p95_ms"] > args.full_p95_ms:
        failures.append("full retrieval P95")
    if report["pure_retrieval"]["recall_at_10"] < args.minimum_recall:
        failures.append("pure retrieval Recall@10")
    if report["full_retrieval"]["recall_at_10"] < args.minimum_recall:
        failures.append("full retrieval Recall@10")
    if leaks:
        failures.append("permission isolation")
    report["passed"] = not failures
    report["failures"] = failures
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark real PostgreSQL hybrid retrieval with a labeled JSONL dataset."
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output")
    parser.add_argument("--minimum-cases", type=int, default=100)
    parser.add_argument("--maximum-cases", type=int, default=300)
    parser.add_argument("--minimum-recall", type=float, default=0.90)
    parser.add_argument("--pure-p95-ms", type=float, default=300.0)
    parser.add_argument("--full-p95-ms", type=float, default=2000.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        Path(args.output).write_text(serialized + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
