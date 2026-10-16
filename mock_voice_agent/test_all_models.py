"""Smoke-test listed Gemini models with a probe suited to each modality.

Media-producing probes are skipped unless --include-costly-generations is passed.
Results are written to test_all_models_output as timestamped JSON and CSV files.
"""

import argparse
import asyncio
import csv
import io
import json
import os
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

from google import genai


MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.5-pro",
    "models/gemini-2.5-flash-preview-tts",
    "models/gemini-2.5-pro-preview-tts",
    "models/gemma-4-26b-a4b-it",
    "models/gemma-4-31b-it",
    "models/gemini-flash-latest",
    "models/gemini-flash-lite-latest",
    "models/gemini-pro-latest",
    "models/gemini-2.5-flash-lite",
    "models/gemini-2.5-flash-image",
    "models/gemini-3-flash-preview",
    "models/gemini-3.1-pro-preview",
    "models/gemini-3.1-pro-preview-customtools",
    "models/gemini-3.1-flash-lite-preview",
    "models/gemini-3.1-flash-lite",
    "models/gemini-3-pro-image-preview",
    "models/gemini-3-pro-image",
    "models/nano-banana-pro-preview",
    "models/gemini-3.1-flash-image-preview",
    "models/gemini-3.1-flash-image",
    "models/gemini-3.1-flash-lite-image",
    "models/gemini-nano-banana-2.1",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-omni-flash-preview",
    "models/gemini-omni-1.1-flash",
    "models/gemini-3.5-transcribe",
    "models/gemini-3.6-flash",
    "models/gemini-3.7-flash",
    "models/gemini-3.8-flash",
    "models/gemini-4-argon",
    "models/lyria-3-clip-preview",
    "models/lyria-3-pro-preview",
    "models/lyria-3.5",
    "models/gemini-3.1-flash-tts-preview",
    "models/gemini-3.8-flash-tts",
    "models/gemini-3.8-flash-lite-tts",
    "models/gemini-robotics-er-2-preview",
    "models/gemini-2.5-computer-use-preview-10-2025",
    "models/antigravity-preview-05-2026",
    "models/antigravity-preview-09-2026",
    "models/antigravity-preview-latest",
    "models/deep-research-max-preview-04-2026",
    "models/deep-research-preview-04-2026",
    "models/deep-research-pro-preview-12-2025",
    "models/gemini-embedding-001",
    "models/gemini-embedding-2-preview",
    "models/gemini-embedding-2",
    "models/aqa",
    "models/veo-3.1-generate-preview",
    "models/veo-3.1-fast-generate-preview",
    "models/veo-3.1-lite-generate-preview",
    "models/gemini-3.5-transcribe-live",
    "models/gemini-2.5-flash-native-audio-latest",
    "models/gemini-2.5-flash-native-audio-preview-09-2025",
    "models/gemini-2.5-flash-native-audio-preview-12-2025",
    "models/gemini-3.1-flash-live-preview",
    "models/gemini-3.8-live",
    "models/gemini-3.8-live-extended-thinking",
    "models/gemini-robotics-er-2-streaming-preview",
    "models/gemini-3.5-live-translate-preview",
    "models/lyria-realtime-exp",
]

OUTPUT_DIR = Path(__file__).resolve().parent / "test_all_models_output"
FIELDS = ["model", "category", "status", "method", "details"]


def model_id(model_name):
    return model_name.removeprefix("models/")


def make_silent_wav():
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\0\0" * 1600)
    return audio.getvalue()


async def probe_live_model(client, name):
    async with client.aio.live.connect(
        model=name,
        config={"response_modalities": ["TEXT"]},
    ):
        pass


async def probe_model(client, model_name, include_costly_generations, api_key):
    name = model_id(model_name)
    lowered = name.lower()

    if "embedding" in lowered:
        client.models.embed_content(model=name, contents="A short test.")
        return "embedding", "WORKED", "models.embed_content", "One short text embedding created."

    if "deep-research" in lowered:
        return (
            "research agent",
            "SKIPPED",
            "interactions.create",
            "Not run: research may launch lengthy, tool-using work and incur additional cost.",
        )

    if "antigravity" in lowered:
        client.interactions.create(
            model=name,
            input="Reply OK.",
            generation_config={"max_output_tokens": 1},
        )
        return "agent", "WORKED", "interactions.create", "One-token interaction request completed."

    if "computer-use" in lowered:
        client.interactions.create(
            model=name,
            input="Reply OK without taking any browser actions.",
            tools=[{"type": "computer_use", "environment": "browser"}],
            generation_config={"max_output_tokens": 1},
        )
        return "computer use", "WORKED", "interactions.create(computer_use)", "Tool-enabled request completed."

    if "veo" in lowered:
        if not include_costly_generations:
            return (
                "video generation",
                "SKIPPED",
                "models.generate_videos",
                "Video generation is billable; rerun with --include-costly-generations to test it.",
            )
        operation = client.models.generate_videos(
            model=name, prompt="A still view of a blue sphere."
        )
        deadline = time.monotonic() + 600
        while not operation.done and time.monotonic() < deadline:
            time.sleep(10)
            operation = client.operations.get(operation)
        if not operation.done:
            return (
                "video generation",
                "IN_PROGRESS",
                "models.generate_videos",
                "Generation did not finish within 10 minutes; it may continue and incur charges.",
            )
        if operation.error:
            raise RuntimeError(str(operation.error))
        if not operation.response or not operation.response.generated_videos:
            raise RuntimeError("Video operation completed without a generated video.")
        return "video generation", "WORKED", "models.generate_videos", "One video generated."

    if "lyria" in lowered and "realtime" not in lowered:
        if not include_costly_generations:
            return (
                "music generation",
                "SKIPPED",
                "interactions.create",
                "Music generation is billable; rerun with --include-costly-generations to test it.",
            )
        client.interactions.create(model=name, input="A short, quiet instrumental note.")
        return "music generation", "WORKED", "interactions.create", "Music generation request completed."

    if "tts" in lowered:
        if not include_costly_generations:
            return (
                "text-to-speech",
                "SKIPPED",
                "interactions.create",
                "Audio generation is billable; rerun with --include-costly-generations to test it.",
            )
        if "2.5" in lowered:
            from google.genai import types

            client.models.generate_content(
                model=name,
                contents="Hello.",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name="Kore"
                            )
                        )
                    ),
                ),
            )
            return "text-to-speech", "WORKED", "models.generate_content(AUDIO)", "Audio generation completed."
        client.interactions.create(
            model=name,
            input="Hello.",
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": "Kore"}]},
        )
        return "text-to-speech", "WORKED", "interactions.create", "Audio generation request completed."

    if "image" in lowered or "banana" in lowered:
        if not include_costly_generations:
            return (
                "image generation",
                "SKIPPED",
                "interactions.create",
                "Image generation is billable; rerun with --include-costly-generations to test it.",
            )
        client.interactions.create(model=name, input="A small blue circle on a plain white background.")
        return "image generation", "WORKED", "interactions.create", "Image generation request completed."

    if "deep-research" not in lowered and "research" in lowered:
        return (
            "research agent",
            "SKIPPED",
            "interactions.create",
            "Not run: research may launch lengthy, tool-using work and incur additional cost.",
        )

    if (
        "live" in lowered
        or "native-audio" in lowered
        or "streaming" in lowered
        or "lyria-realtime" in lowered
    ):
        await probe_live_model(client, name)
        return "live audio", "CONNECTED", "live.connect", "Live API session connected; no audio was generated."

    if "transcribe" in lowered:
        from google.genai import types

        response = client.models.generate_content(
            model=name,
            contents=[
                types.Part.from_bytes(data=make_silent_wav(), mime_type="audio/wav"),
                "Transcribe this short audio. If it is silent, reply with one word.",
            ],
            config=types.GenerateContentConfig(max_output_tokens=8),
        )
        return (
            "audio transcription",
            "WORKED",
            "models.generate_content(audio/wav)",
            "Audio input request completed; " + ("transcription returned." if response.text else "no text returned."),
        )

    if "robotics" in lowered:
        from google.genai import types

        client.models.generate_content(
            model=name,
            contents="Name one safe action for a stationary robot. Do not execute it.",
            config=types.GenerateContentConfig(max_output_tokens=8),
        )
        return "robotics reasoning", "WORKED", "models.generate_content", "Short action-reasoning request completed."

    if lowered == "aqa":
        request_data = json.dumps(
            {
                "contents": [
                    {
                        "parts": [
                            {"text": "Context: One plus one equals two. Question: What is one plus one?"}
                        ]
                    }
                ],
                "answerStyle": "ABSTRACTIVE",
            }
        ).encode("utf-8")
        request = Request(
            "https://generativelanguage.googleapis.com/v1beta/models/aqa:generateAnswer",
            data=request_data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise RuntimeError(f"AQA returned HTTP {response.status}.")
        return "question answering", "WORKED", "models.generate_answer REST", "Answer request completed."

    from google.genai import types

    client.models.generate_content(
        model=name,
        contents="Reply OK.",
        config=types.GenerateContentConfig(max_output_tokens=1),
    )
    return "text generation", "WORKED", "models.generate_content", "One-token response request completed."


def save_results(results, csv_path, json_path):
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(results)
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")


async def run_probes(api_key, include_costly_generations, csv_path, json_path):
    results = []
    with genai.Client(api_key=api_key) as client:
        for model_name in MODELS:
            started = time.monotonic()
            try:
                category, status, method, details = await probe_model(
                    client, model_name, include_costly_generations, api_key
                )
            except Exception as exc:
                category = "model-specific"
                status = "FAILED"
                method = "modality-specific probe"
                details = f"{type(exc).__name__}: {str(exc).replace(api_key, '[REDACTED]')[:400]}"

            result = {
                "model": model_name,
                "category": category,
                "status": status,
                "method": method,
                "details": details,
            }
            results.append(result)
            save_results(results, csv_path, json_path)
            print(f"{status:9} {model_name} [{category}] ({time.monotonic() - started:.1f}s)")
        await client.aio.aclose()
    return results


def main():
    parser = argparse.ArgumentParser(description="Probe the supplied Gemini models by modality.")
    parser.add_argument(
        "--include-costly-generations",
        action="store_true",
        help="Also generate image, speech, music, and video outputs (may incur additional charges).",
    )
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit("Error: GEMINI_API_KEY is not set.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    csv_path = OUTPUT_DIR / f"model_test_results_{run_id}.csv"
    json_path = OUTPUT_DIR / f"model_test_results_{run_id}.json"

    try:
        results = asyncio.run(
            run_probes(api_key, args.include_costly_generations, csv_path, json_path)
        )
    except Exception as exc:
        raise RuntimeError(f"Could not run model probes: {exc}") from exc

    worked = sum(result["status"] in {"WORKED", "CONNECTED"} for result in results)
    failed = sum(result["status"] == "FAILED" for result in results)
    skipped = sum(result["status"] == "SKIPPED" for result in results)
    in_progress = sum(result["status"] == "IN_PROGRESS" for result in results)
    print(
        f"\nSummary: {worked} worked/connected, {failed} failed, "
        f"{skipped} skipped, {in_progress} still in progress."
    )
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
