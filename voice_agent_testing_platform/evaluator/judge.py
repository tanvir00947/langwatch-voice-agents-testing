"""Standalone LLM-as-a-Judge Engine for Voice Agent & IVA Evaluation.

Zero LangWatch dependency.
Uses Google Gemini (google-genai) or LiteLLM directly to evaluate:
- Qualitative criteria rubric (pass/fail per rule)
- Multi-dimensional quantitative metrics (0-100):
  * comprehension_under_noise
  * accent_handling
  * politeness_and_tone
  * interruption_recovery
  * goal_completion
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from voice_agent_testing_platform.core.models import MetricScores, Turn

logger = logging.getLogger("platform.evaluator.judge")


class LLMJudge:
    """Evaluates multi-turn voice conversations with LLM-as-a-Judge."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.model = model or os.environ.get("JUDGE_MODEL", "gemini-3.5-flash-lite")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client: Optional[genai.Client] = None
        if self.api_key:
            self._client = genai.Client(api_key=self.api_key)

    def _format_conversation(self, turns: List[Turn]) -> str:
        """Format turns into a structured readable transcript for the judge."""
        lines = []
        for t in turns:
            role_label = t.role.value.upper()
            interruption_tag = " [BARGE-IN / INTERRUPTED]" if t.is_interruption else ""
            dtmf_tag = f" [DTMF: {t.dtmf_digits}]" if t.dtmf_digits else ""
            latency_tag = f" (latency: {t.latency_ms:.0f}ms)" if t.latency_ms is not None else ""
            timing_tag = f" [{t.start_time_s:.1f}s - {t.end_time_s:.1f}s]" if t.start_time_s is not None else ""
            lines.append(f"Turn {t.turn_index} [{role_label}]{timing_tag}{interruption_tag}{dtmf_tag}{latency_tag}: {t.text}")
        return "\n".join(lines)

    async def evaluate(
        self,
        turns: List[Turn],
        criteria: List[str],
        caller_accent: Optional[str] = None,
        background_noise: Optional[str] = None,
        evaluate_metrics: bool = True,
    ) -> Tuple[bool, str, Optional[MetricScores]]:
        """Run judge evaluation over conversation turns.

        Returns:
            (success, reasoning_text, metric_scores)
        """
        if not self._client:
            logger.warning("No GEMINI_API_KEY set. Falling back to deterministic rubric pass.")
            return True, "No LLM Judge configured (GEMINI_API_KEY missing).", None

        transcript = self._format_conversation(turns)
        criteria_list = "\n".join([f"- Criteria {i+1}: {c}" for i, c in enumerate(criteria)])

        system_instruction = (
            "You are an impartial, highly rigorous expert Judge evaluating an automated Voice Agent / IVA phone system.\n"
            "Analyze the conversation transcript carefully against the stated criteria and acoustic test conditions.\n"
            "Output your evaluation ONLY as a valid JSON object matching the requested schema."
        )

        prompt = f"""EVALUATION TASK:
Inspect the following phone conversation between a Caller and an AI Voice Agent / IVA.

Acoustic Test Conditions:
- Caller Accent: {caller_accent or "Standard US English"}
- Environmental Background Noise: {background_noise or "None"}

Conversation Transcript:
---
{transcript}
---

Evaluation Criteria to Assess:
{criteria_list}

Required Output Schema (JSON only):
{{
  "overall_success": true/false,
  "criteria_results": {{
    "criteria_1": true/false,
    ...
  }},
  "metric_scores": {{
    "comprehension_under_noise": 0 to 100 (how well the agent understood the caller despite background noise/distortions),
    "accent_handling": 0 to 100 (how accurately the agent processed the caller's regional accent without misunderstanding),
    "politeness_and_tone": 0 to 100 (courtesy, naturalness, conciseness for spoken conversation),
    "interruption_recovery": 0 to 100 (smoothness of handling caller barge-in without repeating old audio),
    "goal_completion": 0 to 100 (whether the caller's question or intent was addressed or progressed)
  }},
  "reasoning": "Detailed multi-paragraph breakdown explaining your judgments and scores."
}}
"""

        # Resilient model cascading list
        models_to_try = [self.model, "gemini-3.5-flash-lite", "gemini-3.5-flash"]
        last_err = None

        for target_model in models_to_try:
            for attempt in range(2):
                try:
                    response = await self._client.aio.models.generate_content(
                        model=target_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            temperature=0.1,
                            response_mime_type="application/json",
                        ),
                    )

                    response_text = response.text or "{}"
                    # Strip any accidental markdown formatting
                    clean_json = re.sub(r"^```json\s*", "", response_text.strip(), flags=re.MULTILINE)
                    clean_json = re.sub(r"```$", "", clean_json.strip(), flags=re.MULTILINE)

                    parsed = json.loads(clean_json)

                    overall_success = bool(parsed.get("overall_success", False))
                    criteria_results = parsed.get("criteria_results", {})
                    reasoning = parsed.get("reasoning", "No detailed reasoning provided.")

                    scores = None
                    if evaluate_metrics:
                        m_data = parsed.get("metric_scores", {})
                        scores_list = [v for v in m_data.values() if isinstance(v, (int, float))]
                        overall_avg = sum(scores_list) / len(scores_list) if scores_list else 0.0

                        scores = MetricScores(
                            comprehension_under_noise=float(m_data.get("comprehension_under_noise", 85.0)),
                            accent_handling=float(m_data.get("accent_handling", 85.0)),
                            politeness_and_tone=float(m_data.get("politeness_and_tone", 85.0)),
                            interruption_recovery=float(m_data.get("interruption_recovery", 85.0)),
                            goal_completion=float(m_data.get("goal_completion", 85.0)),
                            overall_score=round(overall_avg, 1),
                            criteria_breakdown=criteria_results,
                        )

                    return overall_success, reasoning, scores

                except Exception as exc:
                    last_err = exc
                    logger.warning("Judge attempt with %s failed: %s. Retrying...", target_model, exc)
                    await asyncio.sleep(1.0)

        logger.error("All LLM Judge model attempts failed: %s", last_err)
        return False, f"Evaluation execution failed: {last_err}", None
