"""Deterministic assertions and telemetry metrics evaluation."""

from __future__ import annotations

import re
from typing import List, Optional
from voice_agent_testing_platform.core.models import DeterministicMetrics, ScenarioStep, Turn, TurnRole


class DeterministicEvaluator:
    """Evaluates rule-based constraints, latency benchmarks, keywords, and DTMF tones."""

    @staticmethod
    def evaluate(
        turns: List[Turn],
        steps: Optional[List[ScenarioStep]] = None,
        max_latency_ms_threshold: float = 4000.0,
    ) -> DeterministicMetrics:
        """Calculate deterministic metrics from conversation turns."""
        metrics = DeterministicMetrics()

        latencies = [t.latency_ms for t in turns if t.latency_ms is not None and t.role == TurnRole.AGENT]
        if latencies:
            metrics.avg_latency_ms = round(sum(latencies) / len(latencies), 1)
            metrics.min_latency_ms = round(min(latencies), 1)
            metrics.max_latency_ms = round(max(latencies), 1)

        metrics.total_turns = len(turns)
        metrics.total_duration_seconds = sum(t.audio_duration for t in turns)

        # Barge-in check
        barge_in_turns = [t for t in turns if t.is_interruption]
        if barge_in_turns:
            metrics.barge_in_tested = True
            # Verified if an agent response turn followed the interruption
            last_barge_in_idx = barge_in_turns[-1].turn_index
            followed_by_agent = any(
                t.role == TurnRole.AGENT and t.turn_index > last_barge_in_idx for t in turns
            )
            metrics.barge_in_successful = followed_by_agent

        # Keyword checks from scenario steps
        agent_texts = " ".join([t.text.lower() for t in turns if t.role == TurnRole.AGENT])
        unmatched = []

        if steps:
            for step in steps:
                if step.expected_keywords:
                    for kw in step.expected_keywords:
                        if not re.search(r"\b" + re.escape(kw.lower()) + r"\b", agent_texts):
                            unmatched.append(kw)

                if step.forbidden_keywords:
                    for kw in step.forbidden_keywords:
                        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", agent_texts):
                            unmatched.append(f"FORBIDDEN: {kw}")

                if step.dtmf_digit:
                    metrics.dtmf_tested = True

        metrics.unmatched_keywords = unmatched
        metrics.keywords_matched = len(unmatched) == 0

        return metrics

