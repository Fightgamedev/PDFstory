from __future__ import annotations

import json
import urllib.error
import urllib.request


API_URL = "https://api.openai.com/v1/responses"


class ModelError(Exception):
    pass


def generate_text(api_key: str, model: str, instructions: str, prompt: str) -> str:
    payload = {
        "model": model,
        "instructions": instructions,
        "input": prompt,
        "store": False,
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(5000).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error", {}).get("message", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ModelError(f"Model request failed ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelError(f"Could not reach the model API: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModelError("The model API returned invalid JSON.") from exc

    pieces: list[str] = []
    for item in result.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                pieces.append(part["text"])

    text = "\n".join(pieces).strip()
    if not text:
        raise ModelError("The model returned no text. Try again or choose another model.")
    return text


def parse_json_response(text: str) -> dict:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end < start:
        raise ModelError("The model response did not contain a JSON object. Please retry generation.")
    try:
        value = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ModelError(f"The model returned malformed JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelError("The model response must be a JSON object.")
    return value
