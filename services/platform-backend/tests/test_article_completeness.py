import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.domains.ai import (
    article_minimum_length,
    process_ai_run,
    validate_article_completeness,
    validate_publish_ready_article,
)
from app.errors import ApiError
from app.models import AIRun, Article, ArticleVersion, Task, User
from app.providers import EnvironmentSecretProvider, ModelResult
from tests.fakes import AllowAllContentSafetyProvider


def document(text: str) -> dict:
    return {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def test_intro_cannot_pass_as_full_article_even_with_valid_json() -> None:
    with pytest.raises(ApiError) as error:
        validate_article_completeness(
            document("这是导语" * 50),
            {
                "untrusted_user_input": "继续生成完整文章",
                "ai_settings": {"min_article_length": 300, "max_article_length": 12000},
            },
        )
    assert error.value.code == "AI_ARTICLE_INCOMPLETE"
    assert error.value.details["actual_length"] == 200


def test_title_and_whitespace_do_not_inflate_body_length() -> None:
    doc = document("正文" + " \n" * 3000)
    doc["content"].insert(
        0,
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "标题" * 1000}],
        },
    )
    with pytest.raises(ApiError):
        validate_article_completeness(doc, {})


def test_explicit_short_article_takes_precedence() -> None:
    context = {"untrusted_user_input": "写一篇300字短文"}
    assert article_minimum_length(context) == 240
    assert validate_article_completeness(document("正文内容" * 70), context) == 280


def test_requested_length_range_and_valid_full_article() -> None:
    assert article_minimum_length({"untrusted_user_input": "写2000到3000字"}) == 1600
    assert validate_article_completeness(document("完整文章内容" * 250), {}) == 1500


def test_meta_explanation_and_bullet_dump_are_not_publishable() -> None:
    doc = document("本资料围绕企业战略管理的核心方法，系统梳理相关内容。")
    doc["content"].append(
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        document(f"论点{i}：" + "只有展开原因与案例才是完整正文。" * 8)["content"][
                            0
                        ]
                    ],
                }
                for i in range(8)
            ],
        }
    )

    with pytest.raises(ApiError) as error:
        validate_publish_ready_article(doc, {"untrusted_user_input": "根据资料写一篇文章"})

    assert error.value.code == "AI_ARTICLE_NOT_PUBLISHABLE"
    assert len(error.value.details["issues"]) == 2
    assert error.value.details["metrics"]["list_ratio"] > 0.9


def test_small_supporting_list_is_allowed_in_prose_article() -> None:
    doc = document("这是一段完整展开的正文。" * 100)
    doc["content"].append(
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [document("用于辅助理解的短要点")["content"][0]],
                }
                for _ in range(2)
            ],
        }
    )

    metrics = validate_publish_ready_article(doc, {"untrusted_user_input": "写一篇文章"})
    assert metrics["list_items"] == 2
    assert metrics["list_ratio"] < 0.1


async def test_pipeline_never_saves_intro_after_one_completion_attempt(app: FastAPI) -> None:
    calls: list[str] = []

    class ShortModel:
        async def generate(self, *, purpose: str, prompt: str, context: dict) -> ModelResult:
            calls.append(purpose)
            return ModelResult(
                text="这只是导语",
                structured=document("这只是导语" * 30),
                input_tokens=1,
                output_tokens=1,
                provider_request_id="test",
            )

    async with app.state.database.session_maker() as session:
        session.add(User(id="complete-owner", display_name="Test", password_hash="test"))
        await session.flush()
        session.add(Task(id="complete-task", owner_id="complete-owner", title="Test"))
        await session.flush()
        run = AIRun(
            id="complete-run",
            task_id="complete-task",
            owner_id="complete-owner",
            run_type="article_generation",
            idempotency_key="complete-test",
            context_snapshot={
                "untrusted_user_input": "继续生成完整文章",
                "route_purpose": "article_generation",
            },
            model_route_snapshot={
                "pipeline_routes": {
                    "intent_detection": {},
                    "article_planning": {},
                }
            },
        )
        session.add(run)
        await session.flush()
        with pytest.raises(ApiError) as error:
            await process_ai_run(
                session,
                run_id=run.id,
                model=ShortModel(),
                safety=AllowAllContentSafetyProvider(),
                secrets=EnvironmentSecretProvider(),
            )
        assert error.value.code == "AI_ARTICLE_INCOMPLETE"
        assert calls.count("article_generation") == 2
        assert "content_check" not in calls
        assert await session.scalar(select(func.count()).select_from(Article)) == 0
        assert await session.scalar(select(func.count()).select_from(ArticleVersion)) == 0


async def test_pipeline_never_saves_unpublishable_rewrite(app: FastAPI) -> None:
    calls: list[str] = []
    invalid = document("本资料围绕团队管理方法，系统梳理相关内容。")
    invalid["content"].append(
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [document("完整论证内容" * 30)["content"][0]],
                }
                for _ in range(8)
            ],
        }
    )

    class InvalidRewriteModel:
        async def generate(self, *, purpose: str, prompt: str, context: dict) -> ModelResult:
            calls.append(purpose)
            return ModelResult(
                text="无效草稿",
                structured=invalid,
                input_tokens=1,
                output_tokens=1,
                provider_request_id="test",
            )

    async with app.state.database.session_maker() as session:
        session.add(User(id="publish-owner", display_name="Test", password_hash="test"))
        await session.flush()
        session.add(Task(id="publish-task", owner_id="publish-owner", title="Test"))
        await session.flush()
        run = AIRun(
            id="publish-run",
            task_id="publish-task",
            owner_id="publish-owner",
            run_type="article_generation",
            idempotency_key="publish-test",
            context_snapshot={
                "untrusted_user_input": "根据资料写一篇公众号文章",
                "route_purpose": "article_generation",
            },
            model_route_snapshot={
                "pipeline_routes": {
                    "article_revision": {},
                }
            },
        )
        session.add(run)
        await session.flush()

        with pytest.raises(ApiError) as error:
            await process_ai_run(
                session,
                run_id=run.id,
                model=InvalidRewriteModel(),
                safety=AllowAllContentSafetyProvider(),
                secrets=EnvironmentSecretProvider(),
            )

        assert error.value.code == "AI_ARTICLE_NOT_PUBLISHABLE"
        assert calls == ["article_generation", "article_revision"]
        assert await session.scalar(select(func.count()).select_from(Article)) == 0
        assert await session.scalar(select(func.count()).select_from(ArticleVersion)) == 0


async def test_pipeline_saves_article_without_model_content_check(app: FastAPI) -> None:
    calls: list[str] = []

    class ArticleModel:
        async def generate(self, *, purpose: str, prompt: str, context: dict) -> ModelResult:
            calls.append(purpose)
            if purpose == "content_check":
                raise AssertionError("content_check must not run")
            article = document("完整正文内容与事实分析" * 200)
            return ModelResult(
                text="完整文章",
                structured=article,
                input_tokens=1,
                output_tokens=1,
                provider_request_id="article",
            )

    async with app.state.database.session_maker() as session:
        session.add(User(id="check-owner", display_name="Test", password_hash="test"))
        await session.flush()
        session.add(Task(id="check-task", owner_id="check-owner", title="Test"))
        await session.flush()
        run = AIRun(
            id="check-run",
            task_id="check-task",
            owner_id="check-owner",
            run_type="article_generation",
            idempotency_key="check-test",
            context_snapshot={
                "untrusted_user_input": "根据资料写一篇公众号文章",
                "route_purpose": "article_generation",
            },
            model_route_snapshot={"pipeline_routes": {}},
        )
        session.add(run)
        await session.flush()

        await process_ai_run(
            session,
            run_id=run.id,
            model=ArticleModel(),
            safety=AllowAllContentSafetyProvider(),
            secrets=EnvironmentSecretProvider(),
        )

        assert calls == ["article_generation"]
        assert await session.scalar(select(func.count()).select_from(Article)) == 1
        assert await session.scalar(select(func.count()).select_from(ArticleVersion)) == 1


async def test_pipeline_extracts_native_file_before_selected_text_model(app: FastAPI) -> None:
    calls: list[str] = []

    class StagedModel:
        async def generate(self, *, purpose: str, prompt: str, context: dict) -> ModelResult:
            calls.append(purpose)
            if purpose == "file_extraction":
                assert context["untrusted_model_files"][0]["filename"] == "reference.pptx"
                return ModelResult("原文件事实" * 300, {}, 1, 1, "extract")
            if purpose == "article_planning":
                assert context["untrusted_model_files"] == []
                assert context["untrusted_extracted_files"][0]["text"].startswith("原文件事实")
                return ModelResult("完整提纲", {}, 1, 1, "plan")
            article = document("完整正文内容与事实论证" * 200)
            return ModelResult("完整正文", article, 1, 1, "article")

    async with app.state.database.session_maker() as session:
        session.add(User(id="extract-owner", display_name="Test", password_hash="test"))
        await session.flush()
        session.add(Task(id="extract-task", owner_id="extract-owner", title="Test"))
        await session.flush()
        run = AIRun(
            id="extract-run",
            task_id="extract-task",
            owner_id="extract-owner",
            run_type="article_generation",
            idempotency_key="extract-test",
            context_snapshot={
                "untrusted_user_input": "根据附件写一篇公众号文章",
                "untrusted_model_files": [
                    {
                        "filename": "reference.pptx",
                        "provider_file_id": "provider-file",
                        "delivery": "provider-files-api",
                        "content": "",
                    }
                ],
                "route_purpose": "article_generation",
            },
            model_route_snapshot={
                "pipeline_routes": {
                    "file_extraction": {},
                    "article_planning": {},
                }
            },
        )
        session.add(run)
        await session.flush()

        await process_ai_run(
            session,
            run_id=run.id,
            model=StagedModel(),
            safety=AllowAllContentSafetyProvider(),
            secrets=EnvironmentSecretProvider(),
        )

        assert calls == [
            "file_extraction",
            "article_planning",
            "article_generation",
        ]
        assert await session.scalar(select(func.count()).select_from(Article)) == 1
        assert await session.scalar(select(func.count()).select_from(ArticleVersion)) == 1
