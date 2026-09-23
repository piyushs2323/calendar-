import json
from datetime import date
from openai import OpenAI
import config

client = OpenAI(api_key=config.OPENAI_API_KEY)

EXTRACT_PROMPT = """You extract buyer-account entries from spoken, informal English.
The speaker gives an account they sold: a buyer's name, an email, and the date it was given (may be relative like "today", "yesterday", "3rd of this month").
Today's date is {today}.

Return ONLY a JSON object, no prose, in this exact shape:
{{"buyer_name": "<name or null>", "email": "<email or null>", "date_given": "<YYYY-MM-DD or null>", "plan_days": <integer number of days the plan should last, default 30 if not mentioned>}}

If a field truly cannot be determined, use null for it. Resolve relative dates using today's date.
"""


def transcribe(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(model="whisper-1", file=f)
    return result.text


def extract_fields(transcript: str) -> dict:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT.format(today=date.today().isoformat())},
            {"role": "user", "content": transcript},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    return data


def transcribe_and_extract(file_path: str):
    transcript = transcribe(file_path)
    fields = extract_fields(transcript)
    return transcript, fields
