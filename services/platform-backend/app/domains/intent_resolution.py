"""Keep explicit writes behind business rules and classify general task semantics."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domains.conversation_actions import plan_action
from app.domains.general_intent import INTENT_PROMPT, parse_intent
from app.domains.preference_learning import is_preference_only
from app.model_gateway import active_route_snapshot, generate_with_frozen_route
from app.models import Message, Task
from app.providers import ModelProvider, SecretProvider


async def resolve_intent(
    session: AsyncSession,
    *,
    task: Task,
    text: str,
    recent: list[Message],
    fallback: str,
    model: ModelProvider,
    secrets: SecretProvider,
    settings: Settings,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    action = await plan_action(session, task, text, recent)
    decision = {"source": "rules", "fallback": fallback, "operation": None, "domain": "business"}
    if action:
        decision["operation"] = action["operation"]
        decision["steps"] = [action["operation"]] + (
            ["article_generation"] if action.get("then_article") else []
        )
        return (
            ("article_generation" if action.get("then_article") else "discussion"),
            action,
            decision,
        )
    route = await active_route_snapshot(session, purpose="fast_task", settings=settings)
    routed = await generate_with_frozen_route(
        snapshot=route,
        fallback_model=model,
        secrets=secrets,
        purpose="intent_detection",
        prompt=INTENT_PROMPT,
        context={
            "untrusted_user_input": text,
            "has_article": bool(task.current_article_id),
            "recent_user_messages": [
                {"text": m.plain_text} for m in reversed(recent[:8]) if m.role == "user"
            ],
        },
        default_timeout_seconds=min(settings.model_timeout_seconds, 30),
        session=session,
    )
    resolved = parse_intent(routed.result.text)
    intent = resolved["intent"]
    if (
        resolved["domain"] == "general" or resolved["needs_clarification"]
        or is_preference_only(text)
    ):
        intent = "discussion"
    elif fallback in {"clarification", "article_conflict_confirmation"}:
        # Semantic understanding does not bypass existing article replacement confirmation.
        intent = fallback
    decision.update({**resolved, "source": "semantic_classifier", "resolved": intent})
    return intent, None, decision
