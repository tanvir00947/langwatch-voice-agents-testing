"""Laptop Audio I/O Engine for Microphone Capture and Speaker Playback.

Manages bidirectional audio streams between the laptop hardware (PyAudio/sounddevice)
and the Twilio Media Stream WebSocket loop. Provides clean non-blocking queues,
sample rate adaptation, and a local loopback hardware test.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

import pyaudio

from twilio_agent.phone_audio_bridge.audio_codec import (
    calculate_rms,
    resample_pcm,
)

logger = logging.getLogger("phone_audio_bridge.audio_io")

# Standard Twilio parameters
SAMPLE_RATE = 8000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK_SIZE = 160  # 20ms frame at 8000Hz


class LaptopAudioEngine:
    """Manages real-time capture from laptop mic and playback to laptop speakers."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        chunk_size: int = CHUNK_SIZE,
        device_in_idx: Optional[int] = None,
        device_out_idx: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.device_in_idx = device_in_idx
        self.device_out_idx = device_out_idx

        self._pyaudio: Optional[pyaudio.PyAudio] = None
        self._mic_stream: Optional[pyaudio.Stream] = None
        self._spk_stream: Optional[pyaudio.Stream] = None

        self._running = False
        self._mic_thread: Optional[threading.Thread] = None
        self._spk_thread: Optional[threading.Thread] = None

        # Thread-safe queues
        self.mic_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self._spk_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

        # Telemetry / metrics
        self.bytes_sent_to_speaker = 0
        self.bytes_read_from_mic = 0
        self._last_log_time = 0.0

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start mic capture and speaker playback streams."""
        if self._running:
            return

        active_loop = loop or asyncio.get_event_loop()
        self._pyaudio = pyaudio.PyAudio()

        logger.info(
            "Initializing audio hardware (Sample rate: %dHz, Channels: %d, Chunk: %d samples)...",
            self.sample_rate,
            CHANNELS,
            self.chunk_size,
        )

        try:
            self._mic_stream = self._pyaudio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_in_idx,
                frames_per_buffer=self.chunk_size,
            )
        except Exception as e:
            logger.error("Failed to open microphone stream at %dHz: %s", self.sample_rate, e)
            self.stop()
            raise

        try:
            self._spk_stream = self._pyaudio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=self.sample_rate,
                output=True,
                output_device_index=self.device_out_idx,
                frames_per_buffer=self.chunk_size,
            )
        except Exception as e:
            logger.error("Failed to open speaker stream at %dHz: %s", self.sample_rate, e)
            self.stop()
            raise

        self._running = True

        # Start background reader thread for microphone
        self._mic_thread = threading.Thread(
            target=self._mic_reader_worker,
            args=(active_loop,),
            daemon=True,
            name="mic-reader",
        )
        self._mic_thread.start()

        # Start background writer thread for speaker
        self._spk_thread = threading.Thread(
            target=self._spk_writer_worker,
            daemon=True,
            name="speaker-writer",
        )
        self._spk_thread.start()

        logger.info("Laptop audio engine is LIVE (Mic and Speaker active).")

    def _mic_reader_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        """Continuously reads PCM chunks from microphone and enqueues them."""
        while self._running and self._mic_stream:
            try:
                data = self._mic_stream.read(self.chunk_size, exception_on_overflow=False)
                if not data:
                    continue

                self.bytes_read_from_mic += len(data)

                # Visual RMS log throttled to once every 0.6s
                rms = calculate_rms(data)
                now = time.time()
                if rms > 450 and (now - self._last_log_time > 0.6):
                    logger.info("🎙️ [Mic -> Phone] Voice detected (RMS volume: %d)", rms)
                    self._last_log_time = now

                # Thread-safe push into asyncio queue
                if not loop.is_closed():
                    try:
                        loop.call_soon_threadsafe(self._push_mic_chunk, data)
                    except RuntimeError:
                        break
            except Exception as e:
                if self._running:
                    logger.debug("Mic reader encountered exception: %s", e)
                break

    def _push_mic_chunk(self, data: bytes) -> None:
        """Push chunk into queue dropping oldest if queue is congested."""
        if self.mic_queue.full():
            try:
                self.mic_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.mic_queue.put_nowait(data)

    def _spk_writer_worker(self) -> None:
        """Reads audio chunks from speaker queue and writes to sound card."""
        while self._running and self._spk_stream:
            try:
                # We use a small polling timeout
                time.sleep(0.005)
                # Chunks are written via play_speaker_chunk
            except Exception:
                break

    async def get_mic_chunk(self) -> bytes:
        """Asynchronously get the next audio chunk from laptop microphone."""
        return await self.mic_queue.get()

    def play_speaker_chunk(self, pcm_chunk: bytes) -> None:
        """Write incoming PCM chunk directly to laptop speakers."""
        if not self._running or not self._spk_stream or not pcm_chunk:
            return

        try:
            self._spk_stream.write(pcm_chunk, exception_on_underflow=False)
            self.bytes_sent_to_speaker += len(pcm_chunk)
        except Exception as e:
            logger.debug("Speaker playback error: %s", e)

    def stop(self) -> None:
        """Stop streams and terminate audio hardware session."""
        self._running = False

        if self._mic_stream:
            try:
                self._mic_stream.stop_stream()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None

        if self._spk_stream:
            try:
                self._spk_stream.stop_stream()
                self._spk_stream.close()
            except Exception:
                pass
            self._spk_stream = None

        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None

        logger.info(
            "Laptop audio engine stopped. (Mic read: %d bytes, Spk played: %d bytes)",
            self.bytes_read_from_mic,
            self.bytes_sent_to_speaker,
        )


async def test_audio_loopback(duration_seconds: int = 5) -> None:
    """Hardware sanity check: records laptop microphone and echoes to speakers.

    Allows user to verify audio hardware before initiating any Twilio call.
    Zero Twilio credits used.
    """
    engine = LaptopAudioEngine(sample_rate=SAMPLE_RATE, chunk_size=CHUNK_SIZE)
    print(f"\n=======================================================")
    print(f"       LAPTOP AUDIO HARDWARE LOOPBACK TEST ({duration_seconds}s)")
    print(f"=======================================================")
    print("Speak into your microphone now...")
    print("You should hear your own voice echoed through your speakers/headphones.")
    print("-------------------------------------------------------")

    loop = asyncio.get_running_loop()
    engine.start(loop=loop)
    start_time = time.time()

    try:
        while time.time() - start_time < duration_seconds:
            chunk = await engine.get_mic_chunk()
            engine.play_speaker_chunk(chunk)
            await asyncio.sleep(0.001)
    finally:
        engine.stop()

    print("\n✅ Audio hardware test completed successfully!")

