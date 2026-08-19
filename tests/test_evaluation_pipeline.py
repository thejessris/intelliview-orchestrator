"""
Tests for the evaluation pipeline's handling of malformed LLM JSON output,
and for its per-stage structured logging/tracing.

Covers issue #114: LLM JSON parsing crashes Celery worker tasks due to
missing exception handling.

Covers issue #33: Pipeline stage logging/tracing — structured logging at
each stage of the evaluation pipeline so failures can be traced to a
specific stage.
"""

import logging
from unittest.mock import patch

import pytest

from workers import evaluation_pipeline


def test_evaluate_answer_quality_falls_back_on_invalid_json():
    """If the LLM returns invalid JSON, evaluate_answer_quality should not
    raise, and should fall back to the seeded stub instead of crashing
    the Celery task."""
    with (
        patch("workers.ai_client.HAS_OPENAI", True),
        patch("workers.ai_client.chat_completion", return_value="not valid json {"),
    ):
        result = evaluation_pipeline.evaluate_answer_quality("session-123")

    assert result is not None
    assert "overall_quality_score" in result


def test_evaluate_technical_accuracy_falls_back_on_invalid_json():
    with (
        patch("workers.ai_client.HAS_OPENAI", True),
        patch("workers.ai_client.chat_completion", return_value="{bad json"),
    ):
        result = evaluation_pipeline.evaluate_technical_accuracy("session-123")

    assert result is not None
    assert "accuracy_score" in result


def test_evaluate_communication_falls_back_on_invalid_json():
    with patch("workers.ai_client.chat_completion", return_value="not json at all"):
        result = evaluation_pipeline.evaluate_communication("session-123")

    assert result is not None
    assert "clarity_score" in result


def test_generate_feedback_falls_back_on_invalid_json():
    with patch("workers.ai_client.chat_completion", return_value="<<<invalid>>>"):
        result = evaluation_pipeline.generate_feedback("session-123")

    assert result is not None
    assert "recommendation" in result


def test_full_pipeline_does_not_crash_on_invalid_json():
    """End-to-end: the whole evaluate_answers() pipeline should complete
    and return a well-formed result even when every LLM call returns
    malformed JSON."""
    with (
        patch("workers.ai_client.HAS_OPENAI", True),
        patch("workers.ai_client.chat_completion", return_value="{not valid json"),
    ):
        result = evaluation_pipeline.evaluate_answers("session-123")

    assert result["session_id"] == "session-123"
    assert 0.0 <= result["risk_score"] <= 1.0


def test_score_answer_falls_back_on_invalid_json():
    with (
        patch("workers.ai_client.HAS_GEMINI", True),
        patch(
            "workers.ai_client.gemini_generate",
            return_value=(
                "not valid json",
                {"provider": "google", "model": "x", "total_tokens": 0},
            ),
        ),
    ):
        result = evaluation_pipeline.score_answer(
            "What is a hash map?", "It's a key-value store."
        )

    assert result["score"] == 5.0
    assert "strengths" in result and "gaps" in result


def test_stage_failure_is_traced_to_the_failing_stage(caplog):
    """Simulated failure: if a single stage (technical_accuracy) blows up,
    the logs should clearly identify that exact stage and session, the
    pipeline should stop there (no swallowed exception, no unrelated
    'succeeded' log for that stage), and earlier stages should still show
    as completed."""
    with (
        caplog.at_level(logging.INFO, logger="workers.evaluation_pipeline"),
        patch(
            "workers.evaluation_pipeline.evaluate_technical_accuracy",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        evaluation_pipeline.evaluate_answers("session-failure-test")

    messages = [r.getMessage() for r in caplog.records]

    # The prior stage completed...
    assert any(
        "evaluation_pipeline_stage_complete" in m and "stage=answer_quality" in m
        for m in messages
    )
    # ...the failing stage was entered...
    assert any(
        "evaluation_pipeline_stage_start" in m and "stage=technical_accuracy" in m
        for m in messages
    )
    # ...and logged as failed, at ERROR level, tagged with the right stage
    # and session, with the traceback captured.
    failure_records = [
        r
        for r in caplog.records
        if "evaluation_pipeline_stage_failed" in r.getMessage()
    ]
    assert len(failure_records) == 1
    failure_record = failure_records[0]
    assert failure_record.levelno == logging.ERROR
    assert "stage=technical_accuracy" in failure_record.getMessage()
    assert "session_id=session-failure-test" in failure_record.getMessage()
    assert failure_record.exc_info is not None

    # Later stages never ran.
    assert not any("stage=communication_clarity" in m for m in messages)
