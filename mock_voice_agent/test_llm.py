import os
from google import genai
# from pathlib import Path
# from dotenv import load_dotenv
# _ENV_PATH = Path(__file__).resolve().parent / ".env"
# load_dotenv(_ENV_PATH, override=True)


client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY"),
)

print("Models available to this API key:")
for model in client.models.list():
    print(f"- {model.name}")

generation_config = {
    'temperature': 1,
    'max_output_tokens': 65536,
    'top_p': 0.95,
    'thinking_level': 'high',
}

interaction = client.interactions.create(
    model='models/gemini-3-flash-preview',
    input="""what is ai""",
    generation_config=generation_config,
)

print(interaction.output_text)






# """Test Google Gemini LLM using the official google-genai SDK.

# Loads GEMINI_API_KEY from mock_voice_agent/.env.
# """

# from __future__ import annotations

# import os
# import sys
# from pathlib import Path
# from dotenv import load_dotenv
# from google import genai

# # Prevent Windows console UnicodeEncodeError on cp1252
# if hasattr(sys.stdout, "reconfigure"):
#     sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# # Load .env located in the same directory as this script
# _ENV_PATH = Path(__file__).resolve().parent / ".env"
# load_dotenv(_ENV_PATH, override=True)

# api_key = os.environ.get("GEMINI_API_KEY", "").strip()
# model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()

# if not api_key:
#     print("Error: GEMINI_API_KEY is not set.")
#     print(f"Please check '{_ENV_PATH}' and add your GEMINI_API_KEY.")
#     sys.exit(1)

# print(f"Connecting to Gemini (model: '{model_name}')...")

# try:
#     client = genai.Client(api_key=api_key)
#     response = client.models.generate_content(
#         model=model_name,
#         contents="Explain how AI works in a single short sentence.",
#     )

#     print("\n[SUCCESS] Gemini Response:")
#     print("-" * 50)
#     print(response.text.strip())
#     print("-" * 50)
#     print("LLM test passed successfully!")

# except Exception as exc:
#     print(f"\n[ERROR] Gemini Request Failed: {exc}")
