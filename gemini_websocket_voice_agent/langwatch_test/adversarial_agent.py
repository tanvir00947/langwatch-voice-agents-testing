"""Adversarial Gemini Live Voice Agent for Scenario evaluation.

Uses gemini-2.5-flash-native-audio-latest directly via the Gemini Live API
to natively produce spoken audio and transcripts for the caller.
No discrete STT + text LLM + TTS pipeline is used.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

from google import genai
from google.genai import types

from scenario.user_simulator_agent import UserSimulatorAgent
from scenario.voice.audio_chunk import AudioChunk
from scenario.voice.messages import create_audio_message, extract_audio

logger = logging.getLogger("langwatch_test.adversarial_agent")


class AdversarialGeminiLiveAgent(UserSimulatorAgent):
    """Adversarial Voice Agent generating native spoken audio via gemini-2.5-flash-native-audio-latest."""

    def __init__(
        self,
        model: str = "gemini-2.5-flash-native-audio-latest",
        voice: str = "Puck",
        persona: Optional[str] = None,
        system_instruction: Optional[str] = None,
        api_key: Optional[str] = None,
        audio_effects: Optional[List[Callable[[bytes], bytes]]] = None,
        transcript_path: Optional[Path] = None,
    ) -> None:
        default_persona = (
            "An impatient and skeptical customer calling LangWatch customer support to test their system. "
            "You ask demanding questions about high pricing, self-hosting privacy, real-time voice evaluation latency, "
            "and interrupt mid-conversation if the agent gives vague answers."
        )
        super().__init__(
            voice=voice,
            persona=persona or default_persona,
            audio_effects=audio_effects or [],
        )
        self.model = model
        self.voice_name = voice
        self.transcript_path = transcript_path
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._client: Optional[genai.Client] = None
        self._session = None
        self._session_task: Optional[asyncio.Task] = None
        self._session_ready: Optional[asyncio.Event] = None
        self._shutdown: Optional[asyncio.Event] = None
        self._turn_index = 0

        self.system_instruction = system_instruction or (
            f"<persona>\n{self.persona}\n</persona>\n"
            "You are speaking aloud on a live telephone call to customer support. "
            "Speak naturally with real human cadence, tone, and inflection. "
            "Keep your spoken responses concise (1 to 2 short sentences), as your words are spoken directly over the phone. "
            "Do NOT include meta-descriptions, markdown, or stage directions. Output only your spoken words."
        )

    def _append_transcript(self, entry: str) -> None:
        """Immediately append turn text to transcript file and flush to disk in real time."""
        if self.transcript_path:
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n\n")
                f.flush()

    async def _ensure_connected(self) -> None:
        """Ensure connection to Gemini Live API session."""
        if self._session is not None:
            return

        self._client = genai.Client(api_key=self._api_key)
        self._session_ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        session_future: asyncio.Future[Any] = loop.create_future()

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice_name)
                )
            ),
            system_instruction=self.system_instruction,
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

        async def _lifetime():
            try:
                async with self._client.aio.live.connect(model=self.model, config=config) as session:
                    if not session_future.done():
                        session_future.set_result(session)
                    self._session_ready.set()
                    await self._shutdown.wait()
            except Exception as exc:
                if not session_future.done():
                    session_future.set_exception(exc)
                self._session_ready.set()

        self._session_task = asyncio.create_task(_lifetime())
        await self._session_ready.wait()
        self._session = await session_future
        logger.info(
            "Adversarial Voice Agent connected to Gemini Live (%s, voice: %s)",
            self.model,
            self.voice_name,
        )

    async def _generate_native_voice(self, prompt: str) -> AudioChunk:
        """Query Gemini Live natively to produce raw PCM16 audio and transcript."""
        await self._ensure_connected()

        logger.info("[Adversarial Agent] Prompting Gemini Live native speech: %r", prompt[:80])
        await self._session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            turn_complete=True,
        )

        audio_bytes = b""
        transcript = ""

        async for msg in self._session.receive():
            sc = getattr(msg, "server_content", None)
            if not sc:
                continue

            if sc.output_transcription and sc.output_transcription.text:
                transcript += sc.output_transcription.text

            if sc.model_turn and sc.model_turn.parts:
                for part in sc.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        audio_bytes += part.inline_data.data

            if sc.turn_complete:
                if not audio_bytes and not transcript:
                    continue  # Skip spurious empty interrupt markers
                break

        # Apply acoustic audio effects if configured (cafe background noise, telephony filter)
        effects = self._effective_audio_effects()
        processed_audio = audio_bytes
        for effect in effects:
            try:
                processed_audio = effect(processed_audio)
            except Exception as e:
                logger.warning("Error applying audio effect: %s", e)

        logger.info(
            "🗣️ [Adversarial Caller Spoke] %d bytes audio. Transcript: %r",
            len(processed_audio),
            transcript,
        )
        return AudioChunk(data=processed_audio, transcript=transcript)

    async def _voiceify(self, text_message: dict) -> Any:
        """Produce native Gemini Live spoken speech for a scripted text turn."""
        content = text_message.get("content", "")
        if not isinstance(content, str) or not content:
            return text_message

        self._turn_index += 1
        curr_turn = self._turn_index
        t_start = datetime.now().strftime("%H:%M:%S")

        prompt = (
            f"Speak the following words aloud naturally, expressively, and impatiently as the caller: {content}"
        )
        chunk = await self._generate_native_voice(prompt)

        # Log caller turn immediately into live transcript
        display_text = chunk.transcript or content
        self._append_transcript(f"[{t_start}] [Turn {curr_turn}] 👤 Adversarial Caller:\n{display_text}")

        return create_audio_message(chunk, role="user")

    async def call(self, input: Any) -> Any:
        """Generate the next adversarial conversational turn natively with Gemini Live."""
        self._turn_index += 1
        curr_turn = self._turn_index
        t_start = datetime.now().strftime("%H:%M:%S")

        # Extract context from previous agent message
        last_agent_text = ""
        if hasattr(input, "messages") and input.messages:
            for m in reversed(input.messages):
                if m.get("role") in ("assistant", "agent"):
                    c = m.get("content")
                    if isinstance(c, str):
                        last_agent_text = c
                        break
                    elif isinstance(c, list):
                        for p in c:
                            if isinstance(p, dict) and p.get("type") == "text":
                                last_agent_text = p.get("text", "")
                                break
                    audio_chk = extract_audio(m)
                    if not last_agent_text and audio_chk and audio_chk.transcript:
                        last_agent_text = audio_chk.transcript
                    if last_agent_text:
                        break

        if last_agent_text:
            prompt = (
                f"The support agent just said: '{last_agent_text}'. "
                "Respond as the adversarial caller with your next spoken reaction. "
                "Be direct, challenging, and speak in 1 to 2 short conversational sentences."
            )
        else:
            prompt = (
                "Start the phone call to LangWatch customer support. "
                "Demand to know what LangWatch is, express skepticism about claims, and speak in 1 short sentence."
            )

        chunk = await self._generate_native_voice(prompt)

        display_text = chunk.transcript or "(caller spoken audio)"
        self._append_transcript(f"[{t_start}] [Turn {curr_turn}] 👤 Adversarial Caller:\n{display_text}")

        return create_audio_message(chunk, role="user")

    async def disconnect(self) -> None:
        """Teardown Gemini Live connection safely."""
        try:
            if self._shutdown is not None and not self._shutdown.is_set():
                self._shutdown.set()
        except Exception:
            pass
        if self._session_task is not None and not self._session_task.done():
            self._session_task.cancel()
            try:
                await asyncio.wait_for(self._session_task, timeout=1.0)
            except Exception:
                pass
        self._session = None
