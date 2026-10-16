"""Scenario Execution Engine driving voice agent & telephony test runs."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import time
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from voice_agent_testing_platform.adapters.base import BaseAgentAdapter
    from voice_agent_testing_platform.callers.base_caller import BaseCaller

from voice_agent_testing_platform.core.audio_utils import (
    extract_waveform_peaks,
    save_stereo_wav,
    save_wav,
)
from voice_agent_testing_platform.core.models import (
    AudioChunk,
    DeterministicMetrics,
    ScenarioStep,
    TestResult,
    TestScenario,
    Turn,
    TurnAction,
    TurnRole,
)
from voice_agent_testing_platform.evaluator.deterministic import DeterministicEvaluator
from voice_agent_testing_platform.evaluator.judge import LLMJudge
from voice_agent_testing_platform.evaluator.metrics import MetricAggregator

logger = logging.getLogger("platform.runner")


class ScenarioRunner:
    """Executes a test scenario against an adapter using a simulated caller."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        judge: Optional[LLMJudge] = None,
        on_turn_callback: Optional[Callable[[Turn], None]] = None,
    ):
        self.output_dir = output_dir or (Path(__file__).resolve().parent.parent / "outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.judge = judge or LLMJudge()
        self.on_turn_callback = on_turn_callback

    async def run(
        self,
        scenario: TestScenario,
        adapter: BaseAgentAdapter,
        caller: BaseCaller,
    ) -> TestResult:
        """Run the scenario from start to completion with dual-track audio recording."""
        started_at = datetime.now().isoformat()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        wav_path = self.output_dir / f"run_{scenario.id}_{timestamp}_mixed.wav"
        caller_wav_path = self.output_dir / f"run_{scenario.id}_{timestamp}_caller.wav"
        agent_wav_path = self.output_dir / f"run_{scenario.id}_{timestamp}_agent.wav"
        stereo_wav_path = self.output_dir / f"run_{scenario.id}_{timestamp}_stereo.wav"
        txt_path = self.output_dir / f"run_{scenario.id}_{timestamp}.txt"
        json_path = self.output_dir / f"run_{scenario.id}_{timestamp}.json"

        turns: List[Turn] = []
        full_audio_bytes = bytearray()
        timeline_caller_pcm = bytearray()
        timeline_agent_pcm = bytearray()
        current_time_s = 0.0
        turn_counter = 0

        logger.info("=" * 60)
        logger.info("🚀 STARTING SCENARIO TEST: %s", scenario.name)
        logger.info("Adapter: %s | Caller Accent: %s | Background Noise: %s", adapter.name, caller.accent, caller.background_noise)
        logger.info("=" * 60)

        # Write initial session header to transcript
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write(f"VOICE AGENT TEST SESSION: {scenario.name}\n")
            f.write(f"Started: {started_at}\n")
            f.write(f"Adapter: {adapter.name}\n")
            f.write(f"Caller Accent: {caller.accent} | Noise: {caller.background_noise or 'None'}\n")
            f.write("=" * 60 + "\n\n")

        try:
            # 1. Connect Adapter
            await adapter.connect()

            # 2. Multi-turn conversation loop
            for _ in range(scenario.max_turns):
                turn_counter += 1

                # A. Caller determines action
                caller_chunk, action, dtmf_digit = await caller.get_next_action(turn_counter, turns)
                if action == TurnAction.WAIT and not caller_chunk:
                    logger.info("Scenario complete: Caller has no further actions.")
                    break

                # Record Caller Turn
                is_interrupt = (action == TurnAction.INTERRUPT)
                caller_text = (caller_chunk.transcript if caller_chunk else "") or f"[{action.value.upper()}]"
                caller_audio = caller_chunk.data if caller_chunk else b""
                caller_duration = caller_chunk.duration_seconds if caller_chunk else 0.0
                if caller_duration == 0.0 and caller_audio:
                    caller_duration = (len(caller_audio) / 2.0) / 24000.0
                caller_duration = max(0.3, caller_duration)

                start_t = round(current_time_s, 2)
                end_t = round(current_time_s + caller_duration, 2)
                current_time_s = end_t

                if caller_audio:
                    full_audio_bytes.extend(caller_audio)
                    timeline_caller_pcm.extend(caller_audio)
                    timeline_agent_pcm.extend(b"\x00" * len(caller_audio))

                c_turn = Turn(
                    turn_index=turn_counter,
                    timestamp=datetime.now().strftime("%H:%M:%S"),
                    role=TurnRole.CALLER,
                    text=caller_text,
                    audio_duration=caller_duration,
                    start_time_s=start_t,
                    end_time_s=end_t,
                    is_interruption=is_interrupt,
                    dtmf_digits=dtmf_digit,
                )
                turns.append(c_turn)
                if self.on_turn_callback:
                    self.on_turn_callback(c_turn)

                self._append_transcript(txt_path, c_turn)

                # B. Execute caller action on adapter
                if is_interrupt:
                    await adapter.interrupt()
                    if caller_chunk and caller_chunk.data:
                        await adapter.send_audio(caller_chunk)
                elif action == TurnAction.DTMF and dtmf_digit:
                    await adapter.send_dtmf(dtmf_digit)
                elif caller_chunk and caller_chunk.data:
                    await adapter.send_audio(caller_chunk)

                # C. Await Agent response
                agent_chunk = await adapter.receive_response(timeout=45.0)
                turn_counter += 1

                agent_audio = agent_chunk.data if agent_chunk else b""
                agent_duration = agent_chunk.duration_seconds if agent_chunk else 0.0
                if agent_duration == 0.0 and agent_audio:
                    agent_duration = (len(agent_audio) / 2.0) / 24000.0
                agent_duration = max(0.5, agent_duration)

                start_t = round(current_time_s, 2)
                end_t = round(current_time_s + agent_duration, 2)
                current_time_s = end_t

                if agent_audio:
                    full_audio_bytes.extend(agent_audio)
                    timeline_agent_pcm.extend(agent_audio)
                    timeline_caller_pcm.extend(b"\x00" * len(agent_audio))

                agent_text = agent_chunk.transcript or "(agent spoken audio response)"
                agent_latency = getattr(adapter, "last_latency_ms", None)

                a_turn = Turn(
                    turn_index=turn_counter,
                    timestamp=datetime.now().strftime("%H:%M:%S"),
                    role=TurnRole.AGENT,
                    text=agent_text,
                    audio_duration=agent_duration,
                    start_time_s=start_t,
                    end_time_s=end_t,
                    latency_ms=agent_latency,
                )
                turns.append(a_turn)
                if self.on_turn_callback:
                    self.on_turn_callback(a_turn)

                self._append_transcript(txt_path, a_turn)

            # 3. Teardown
            await caller.teardown()
            await adapter.disconnect()

        except Exception as exc:
            logger.error("Error during scenario execution: %s", exc, exc_info=True)
            try:
                await adapter.disconnect()
            except Exception:
                pass
            return TestResult(
                scenario_id=scenario.id,
                scenario_name=scenario.name,
                success=False,
                status="error",
                turns=turns,
                error_message=str(exc),
                started_at=started_at,
                finished_at=datetime.now().isoformat(),
            )

        finished_at = datetime.now().isoformat()

        # 4. Save mixed, caller, agent, and 2-channel stereo WAV audio files
        caller_bytes = bytes(timeline_caller_pcm)
        agent_bytes = bytes(timeline_agent_pcm)

        if full_audio_bytes:
            save_wav(str(wav_path), bytes(full_audio_bytes), sample_rate=24000)
            logger.info("Saved mixed conversation audio to: %s", wav_path)

        if caller_bytes:
            save_wav(str(caller_wav_path), caller_bytes, sample_rate=24000)
        if agent_bytes:
            save_wav(str(agent_wav_path), agent_bytes, sample_rate=24000)
        if caller_bytes or agent_bytes:
            save_stereo_wav(str(stereo_wav_path), caller_bytes, agent_bytes, sample_rate=24000)
            logger.info("Saved dual-channel stereo audio to: %s", stereo_wav_path)

        # 5. Extract waveform peaks for UI visualization
        caller_peaks = extract_waveform_peaks(caller_bytes, num_peaks=250)
        agent_peaks = extract_waveform_peaks(agent_bytes, num_peaks=250)

        # 6. Deterministic Assertions & Timing Metrics
        deterministic = DeterministicEvaluator.evaluate(turns, steps=scenario.steps)
        deterministic.total_duration_seconds = round(current_time_s, 2)

        # 7. LLM-as-a-Judge Evaluation (Qualitative Rubric + 0-100 Dimension Scores)
        llm_pass = True
        llm_reasoning = "Deterministic evaluation only."
        metric_scores = None

        if scenario.criteria:
            logger.info("Running LLM-as-a-Judge evaluation with model: %s ...", self.judge.model)
            llm_pass, llm_reasoning, metric_scores = await self.judge.evaluate(
                turns=turns,
                criteria=scenario.criteria,
                caller_accent=caller.accent,
                background_noise=caller.background_noise,
                evaluate_metrics=scenario.evaluate_metrics,
            )

        # 8. Aggregate Result
        result = MetricAggregator.aggregate(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            turns=turns,
            deterministic=deterministic,
            llm_success=llm_pass,
            llm_reasoning=llm_reasoning,
            metric_scores=metric_scores,
            audio_path=str(wav_path) if full_audio_bytes else None,
            transcript_path=str(txt_path),
            started_at=started_at,
            finished_at=finished_at,
        )

        result.caller_audio_path = str(caller_wav_path) if caller_bytes else None
        result.agent_audio_path = str(agent_wav_path) if agent_bytes else None
        result.stereo_audio_path = str(stereo_wav_path) if (caller_bytes or agent_bytes) else None

        # Write footer to transcript
        with open(txt_path, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write(f"EVALUATION RESULT: {'PASSED' if result.success else 'FAILED'}\n")
            f.write(f"Total Call Duration: {deterministic.total_duration_seconds:.1f}s\n")
            f.write(f"Average Response Latency: {deterministic.avg_latency_ms:.1f}ms\n")
            if metric_scores:
                f.write(f"Overall Metric Score: {metric_scores.overall_score}/100\n")
                f.write(f"  • Comprehension Under Noise: {metric_scores.comprehension_under_noise}/100\n")
                f.write(f"  • Regional Accent Handling: {metric_scores.accent_handling}/100\n")
                f.write(f"  • Politeness & Tone: {metric_scores.politeness_and_tone}/100\n")
                f.write(f"  • Interruption Recovery: {metric_scores.interruption_recovery}/100\n")
            f.write(f"Judge Reasoning:\n{llm_reasoning}\n")
            f.write("=" * 60 + "\n")

        # Save JSON result with peaks metadata for UI
        res_dict = result.model_dump()
        res_dict["caller_peaks"] = caller_peaks
        res_dict["agent_peaks"] = agent_peaks
        res_dict["total_duration_s"] = current_time_s

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(res_dict, f, indent=2)

        logger.info("=" * 60)
        logger.info("🏁 SCENARIO COMPLETE: %s (Status: %s)", scenario.name, result.status.upper())
        logger.info("=" * 60)

        return result

    def _append_transcript(self, path: Path, turn: Turn) -> None:
        role_label = "👤 CALLER" if turn.role == TurnRole.CALLER else "🤖 AGENT"
        interrupt_note = " ⚡ [BARGE-IN / INTERRUPTION]" if turn.is_interruption else ""
        dtmf_note = f" 📞 [KEYPAD DTMF: {turn.dtmf_digits}]" if turn.dtmf_digits else ""
        latency_note = f" (response latency: {turn.latency_ms:.0f}ms)" if turn.latency_ms else ""
        timing_note = f" [{turn.start_time_s:.1f}s - {turn.end_time_s:.1f}s]" if turn.start_time_s is not None else ""

        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{turn.timestamp}]{timing_note} [Turn {turn.turn_index}] {role_label}{interrupt_note}{dtmf_note}{latency_note}:\n")
            f.write(f"{turn.text}\n\n")
            f.flush()
