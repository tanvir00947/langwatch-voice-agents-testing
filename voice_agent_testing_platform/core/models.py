"""Data models and schemas for the Voice Agent & IVA/IVR Testing Platform."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TurnRole(str, Enum):
    CALLER = "caller"
    AGENT = "agent"
    SYSTEM = "system"
    JUDGE = "judge"


class TurnAction(str, Enum):
    SAY = "say"
    INTERRUPT = "interrupt"
    DTMF = "dtmf"
    WAIT = "wait"
    SILENCE = "silence"


class AudioChunk(BaseModel):
    """Represents a chunk or complete stream of audio data."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: bytes = Field(default=b"")
    sample_rate: int = 24000
    format: str = "pcm16"  # "pcm16", "mulaw", etc.
    transcript: Optional[str] = None
    duration_seconds: float = 0.0


class Turn(BaseModel):
    """A single turn in the voice conversation."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    turn_index: int
    timestamp: str
    role: TurnRole
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_duration: float = 0.0
    start_time_s: Optional[float] = None
    end_time_s: Optional[float] = None
    latency_ms: Optional[float] = None  # Latency from caller speech end to agent response start
    is_interruption: bool = False
    dtmf_digits: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScenarioStep(BaseModel):
    """A discrete scripted action in a test scenario."""
    action: TurnAction = TurnAction.SAY
    text: Optional[str] = None
    audio_file: Optional[str] = None
    dtmf_digit: Optional[str] = None
    delay_seconds: float = 0.0
    wait_for_speech_timeout: float = 5.0
    expected_keywords: List[str] = Field(default_factory=list)
    forbidden_keywords: List[str] = Field(default_factory=list)
    expected_dtmf: Optional[str] = None


class MetricScores(BaseModel):
    """Multi-dimensional evaluation metric scores (0-100)."""
    comprehension_under_noise: Optional[float] = None
    accent_handling: Optional[float] = None
    politeness_and_tone: Optional[float] = None
    interruption_recovery: Optional[float] = None
    goal_completion: Optional[float] = None
    overall_score: float = 0.0
    criteria_breakdown: Dict[str, bool] = Field(default_factory=dict)


class DeterministicMetrics(BaseModel):
    """Deterministic, objective telemetry and timing measurements."""
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    total_turns: int = 0
    total_duration_seconds: float = 0.0
    barge_in_tested: bool = False
    barge_in_successful: bool = False
    dtmf_tested: bool = False
    dtmf_matched: bool = True
    keywords_matched: bool = True
    unmatched_keywords: List[str] = Field(default_factory=list)


class TestScenario(BaseModel):
    """Complete specification of a test run."""
    id: str
    name: str
    description: str = ""
    adapter_type: str = "websocket"  # "websocket", "twilio", "telnyx", "mock_telephony"
    adapter_config: Dict[str, Any] = Field(default_factory=dict)
    caller_type: str = "scripted"  # "scripted", "dynamic"
    caller_config: Dict[str, Any] = Field(default_factory=dict)
    steps: List[ScenarioStep] = Field(default_factory=list)
    criteria: List[str] = Field(default_factory=list)
    evaluate_metrics: bool = True
    max_turns: int = 10


class TestResult(BaseModel):
    """Final test report structure."""
    scenario_id: str
    scenario_name: str
    success: bool
    status: str = "passed"  # "passed", "failed", "error"
    turns: List[Turn] = Field(default_factory=list)
    deterministic_metrics: DeterministicMetrics = Field(default_factory=DeterministicMetrics)
    metric_scores: Optional[MetricScores] = None
    judge_reasoning: str = ""
    audio_file_path: Optional[str] = None
    caller_audio_path: Optional[str] = None
    agent_audio_path: Optional[str] = None
    stereo_audio_path: Optional[str] = None
    transcript_file_path: Optional[str] = None
    started_at: str = ""
    finished_at: str = ""
    error_message: Optional[str] = None

