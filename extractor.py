import json
import time
from datetime import date

from google import genai
from google.genai import types

import config

client = genai.Client(api_key=config.GEMINI_API_KEY)

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
    for attempt in range(3):
        try:
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
            return json.loads(text)
        except Exception as e:  # rate limit (429) or temporary error: wait and retry
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err


def transcribe_and_extract(file_path: str):
    with open(file_path, "rb") as f:
        audio_bytes = f.read()
    data = _call_gemini(audio_bytes)
    transcript = data.pop("transcript", "") or ""
    return transcript, data

