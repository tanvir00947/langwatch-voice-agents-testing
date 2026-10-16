"""Metric aggregation and report synthesis."""

from __future__ import annotations

from typing import List, Optional
from voice_agent_testing_platform.core.models import (
    DeterministicMetrics,
    MetricScores,
    TestResult,
    Turn,
)
from voice_agent_testing_platform.evaluator.deterministic import DeterministicEvaluator
from voice_agent_testing_platform.evaluator.judge import LLMJudge


class MetricAggregator:
    """Combines deterministic metrics and qualitative LLM-as-a-Judge evaluations."""

    @staticmethod
    def aggregate(
        scenario_id: str,
        scenario_name: str,
        turns: List[Turn],
        deterministic: DeterministicMetrics,
        llm_success: bool,
        llm_reasoning: str,
        metric_scores: Optional[MetricScores],
        audio_path: Optional[str] = None,
        transcript_path: Optional[str] = None,
        started_at: str = "",
        finished_at: str = "",
    ) -> TestResult:
        # Test passes if LLM criteria passed AND deterministic assertions (keywords, DTMF) passed
        overall_pass = llm_success and deterministic.keywords_matched and deterministic.dtmf_matched

        status = "passed" if overall_pass else "failed"

        return TestResult(
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            success=overall_pass,
            status=status,
            turns=turns,
            deterministic_metrics=deterministic,
            metric_scores=metric_scores,
            judge_reasoning=llm_reasoning,
            audio_file_path=audio_path,
            transcript_file_path=transcript_path,
            started_at=started_at,
            finished_at=finished_at,
        )

