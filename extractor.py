import json
import logging
import time
from datetime import date

from google import genai
from google.genai import types

import config

log = logging.getLogger("extractor")

# 45s timeout so a stuck request fails instead of hanging forever
client = genai.Client(
    api_key=config.GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=45000),
)

EXTRACT_PROMPT = """You extract buyer-account entries from a spoken, informal English voice note.
The speaker gives an account they sold: a buyer's name, an email, and the date it was given (may be relative like "today", "yesterday", "3rd of this month").
Today's date is {today}.

Listen to the audio, then return ONLY a JSON object, no prose, in this exact shape:
{{"transcript": "<what was said>", "buyer_name": "<name or null>", "email": "<email or null>", "date_given": "<YYYY-MM-DD or null>", "plan_days": <integer number of days the plan should last, default 30 if not mentioned>}}

If a field truly cannot be determined, use null for it. Resolve relative dates using today's date.
Spoken emails: "at" means @, "dot" means a period. Write the email in normal form.
"""


def _call_gemini(audio_bytes: bytes) -> dict:
    prompt = EXTRACT_PROMPT.format(today=date.today().isoformat())
    last_err = None
    for attempt in range(2):
        try:
            log.info("Gemini call attempt %d, model=%s", attempt + 1, config.GEMINI_MODEL)
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=audio_bytes, mime_type="audio/ogg"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
            text = (resp.text or "").replace("```json", "").replace("```", "").strip()
            log.info("Gemini raw reply: %s", text[:500])
            return json.loads(text)
        except Exception as e:
            last_err = e
            log.error("Gemini attempt %d failed: %r", attempt + 1, e)
            time.sleep(2)
    raise last_err


def transcribe_and_extract(file_path: str):
    with open(file_path, "rb") as f:
        audio_bytes = f.read()
    data = _call_gemini(audio_bytes)
    transcript = data.pop("transcript", "") or ""
    return transcript, data
