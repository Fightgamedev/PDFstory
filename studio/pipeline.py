from __future__ import annotations

import json
from collections.abc import Callable

from .openai_api import generate_text, parse_json_response


Progress = Callable[[str], None]
CHUNK_LIMIT = 18000


def _chunks(pages: list[str]) -> list[dict]:
    chunks: list[dict] = []
    text_parts: list[str] = []
    used = 0
    first_page = 1
    last_page = 1

    for number, page in enumerate(pages, start=1):
        page = page.strip()
        if not page:
            continue
        paragraphs = page.split("\n\n")
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if len(paragraph) > CHUNK_LIMIT:
                paragraph_parts = [paragraph[i : i + CHUNK_LIMIT] for i in range(0, len(paragraph), CHUNK_LIMIT)]
            else:
                paragraph_parts = [paragraph]

            for part in paragraph_parts:
                if used and used + len(part) > CHUNK_LIMIT:
                    chunks.append({"pages": [first_page, last_page], "text": "\n\n".join(text_parts)})
                    text_parts = []
                    used = 0
                if not used:
                    first_page = number
                last_page = number
                text_parts.append(part)
                used += len(part)

    if text_parts:
        chunks.append({"pages": [first_page, last_page], "text": "\n\n".join(text_parts)})
    return chunks


def _json_for_prompt(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_outline(
    pages: list[str],
    api_key: str,
    model: str,
    mode: str,
    scene_count: int,
    progress: Progress,
) -> dict:
    chunks = _chunks(pages)
    if not chunks:
        raise ValueError("No readable text was found in this PDF.")

    summaries = []
    instructions = (
        "You are a careful book analyst preparing source notes for an adaptation. "
        "Return only a valid JSON object. Summarize in your own words; do not reproduce passages. "
        "Keep names, relationships, events, and page ranges distinct."
    )
    for index, chunk in enumerate(chunks, start=1):
        progress(f"Reading text section {index} of {len(chunks)}…")
        prompt = f"""Summarize this excerpt for a later visual-novel adaptation.
Return JSON with these keys. Keep the summary under 120 words and list only the most important events and characters:
{{"summary": string, "characters": [{{"name": string, "role": string}}], "events": [string], "themes": [string]}}
Source pages: {chunk['pages'][0]}-{chunk['pages'][1]}
Excerpt:
{chunk['text']}"""
        summary = parse_json_response(generate_text(api_key, model, instructions, prompt))
        summaries.append({"source_pages": chunk["pages"], **summary})

    level = 1
    while len(summaries) > 20:
        reduced = []
        groups = [summaries[i : i + 12] for i in range(0, len(summaries), 12)]
        for index, group in enumerate(groups, start=1):
            progress(f"Condensing book map {level}, group {index} of {len(groups)}…")
            first_page = group[0]["source_pages"][0]
            last_page = group[-1]["source_pages"][-1]
            prompt = f"""Combine these adjacent book notes into a compact continuity note.
Keep the summary under 180 words. Preserve important character names, relationships, events, and themes.
Return only JSON with keys: summary (string), characters (array of {{name, role}}), events (array of strings), themes (array of strings).
The notes cover source pages {first_page}-{last_page}:
{_json_for_prompt(group)}"""
            note = parse_json_response(generate_text(api_key, model, instructions, prompt))
            reduced.append({"source_pages": [first_page, last_page], **note})
        summaries = reduced
        level += 1

    progress("Building the editable outline…")
    mode_text = (
        "Create a faithful adaptation outline while using newly written dialogue."
        if mode == "faithful"
        else "Create a new story inspired only by broad themes and premises. Change characters, scenes, and specific expression."
    )
    prompt = f"""Use these source notes to make a concise, editable outline for a playable visual novel.
{mode_text}
Aim for {scene_count} scenes. Cover the main arc, but keep each scene brief enough for a short first prototype.
Return only JSON with this shape:
{{
  "title": string,
  "logline": string,
  "themes": [string],
  "characters": [{{"name": string, "role": string, "description": string}}],
  "outline": [{{"chapter": string, "summary": string, "source_pages": [integer, integer]}}],
  "scene_plan": [{{"title": string, "purpose": string, "location": string, "beats": [string], "source_pages": [integer, integer]}}]
}}
The source notes are page-aware. Preserve useful page ranges. Do not include long quotations.
Source notes:
{_json_for_prompt(summaries)}"""
    outline = parse_json_response(generate_text(api_key, model, instructions, prompt))
    outline["adaptation_mode"] = mode
    outline["source_page_count"] = len(pages)
    outline["source_summaries"] = summaries
    return outline


def build_screenplay(
    outline: dict,
    api_key: str,
    model: str,
    scene_count: int,
    progress: Progress,
) -> dict:
    progress("Writing scene dialogue and narration…")
    instructions = (
        "You write concise, playable visual-novel scripts. Return only a valid JSON object. "
        "Use original dialogue, natural scene pacing, and short speakable lines. "
        "Do not copy passages from the source notes. Keep the cast and plot consistent with the approved outline."
    )
    prompt = f"""Turn this approved outline into a short linear visual-novel screenplay.
Create at most {scene_count} scenes. Each scene should have 6-12 dialogue/narration lines and one visual description.
Return only JSON with this shape:
{{
  "title": string,
  "logline": string,
  "scenes": [{{
    "id": string,
    "title": string,
    "location": string,
    "source_pages": [integer, integer],
    "visual_description": string,
    "dialogue": [{{"speaker": string, "text": string}}]
  }}]
}}
Use "Narrator" for narration. Keep all dialogue original; do not include long verbatim source text.
Approved outline:
{_json_for_prompt(outline)}"""
    screenplay = parse_json_response(generate_text(api_key, model, instructions, prompt))
    scenes = screenplay.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError("The generated screenplay did not contain any scenes.")
    screenplay["scenes"] = scenes[:scene_count]
    screenplay.setdefault("title", outline.get("title", "Untitled Story"))
    screenplay.setdefault("logline", outline.get("logline", ""))
    return screenplay
