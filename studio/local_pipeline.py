from __future__ import annotations

import re
from collections import Counter


STOP = set("about above after again against all also and any are around because been before being between book both came can could did does down each even from get give have her here him his how into its just like make many more most much must never not now off one only other our out over said same should since some still such than that the their them then there these they thing this through time too under until upon very was were what when where which while who will with would your".split())


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if len(part.strip()) > 35]


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text) if w.lower() not in STOP]


def _place(words: list[str], index: int) -> str:
    groups = [
        ("the old house", {"house", "room", "hall", "wallpaper", "window", "door", "stairs", "home"}),
        ("a quiet garden", {"garden", "tree", "flower", "grass", "path", "woods", "forest", "field"}),
        ("a city after dark", {"city", "street", "light", "train", "shop", "road", "building", "neon"}),
        ("the shore at dusk", {"sea", "water", "shore", "river", "boat", "wave", "coast", "island"}),
        ("a shadowed passage", {"night", "dark", "shadow", "dream", "strange", "fear", "ghost", "secret"}),
    ]
    counts = [(sum(word in keys for word in words), name) for name, keys in groups]
    score, place = max(counts, default=(0, ""))
    if score == 0:
        return ["a lonely road", "an unfamiliar room", "a distant hillside"][index % 3]
    return place


def build_local_outline(pages: list[str], mode: str, scene_count: int, progress=lambda _message: None) -> dict:
    text_pages = [(i, p.strip()) for i, p in enumerate(pages, 1) if p.strip()]
    if not text_pages:
        raise ValueError("No readable text was found in this PDF.")
    all_text = "\n".join(p for _, p in text_pages)
    words = _words(all_text)
    common = Counter(words).most_common(8)
    themes = [word.title() for word, _ in common[:4]] or ["Change", "Courage"]
    # Repeated capitalized words are useful character candidates in novels; filter common headings.
    names = Counter(re.findall(r"\b[A-Z][a-z]{2,}\b", all_text))
    candidates = [name for name, count in names.most_common() if count >= 3 and name.lower() not in STOP]
    characters = [{"name": name, "role": "A recurring figure in the source"} for name in candidates[:3]]
    if not characters:
        characters = [{"name": "The Traveler", "role": "A figure moving through the story"}]
    count = max(3, min(8, scene_count))
    scenes = []
    for idx in range(count):
        progress(f"Finding story moments locally ({idx + 1}/{count})…")
        page_pos = round(idx * max(0, len(text_pages) - 1) / max(1, count - 1))
        page_num, page_text = text_pages[page_pos]
        sentences = _sentences(page_text)
        excerpt = sentences[min(len(sentences) - 1, len(sentences) * (idx % 3) // 3)] if sentences else "A new moment begins, and the next choice is still unknown."
        excerpt = excerpt[:240].rsplit(" ", 1)[0] if len(excerpt) > 240 else excerpt
        local_words = _words(page_text)
        location = _place(local_words, idx)
        scenes.append({
            "chapter": f"Moment {idx + 1}", "summary": excerpt,
            "source_pages": [page_num, page_num], "title": ["A Door Opens", "A Strange Sign", "The Long Walk", "A New Clue", "At the Turning Point", "Beyond the Familiar", "A Quiet Promise", "The Next Morning"][idx],
            "location": location,
        })
    return {
        "title": "A Story Between Pages", "logline": "A new, locally assembled visual story inspired by recurring words and moments in the uploaded book.",
        "themes": themes, "characters": characters, "outline": scenes,
        "scene_plan": [{"title": s["title"], "purpose": "Move the journey forward", "location": s["location"], "beats": [s["summary"]], "source_pages": s["source_pages"]} for s in scenes],
        "adaptation_mode": mode, "source_page_count": len(pages), "generation_mode": "local",
    }


def build_local_screenplay(outline: dict, scene_count: int, progress=lambda _message: None) -> dict:
    cast = outline.get("characters") or [{"name": "The Traveler"}]
    lead = str(cast[0].get("name") or "The Traveler")
    themes = outline.get("themes") or ["change", "memory"]
    plans = outline.get("scene_plan") or outline.get("outline") or []
    plans = plans[:max(3, min(8, scene_count))]
    scenes = []
    openings = ["The air feels different here.", "Something in this place seems to be waiting.", "I have seen this moment before—or dreamed that I had.", "There has to be a reason I was brought here.", "Even the silence feels like a message.", "One small step may change everything.", "The past has a way of finding us.", "For now, I will keep going."]
    for idx, plan in enumerate(plans):
        progress(f"Writing scene {idx + 1} locally…")
        summary = str(plan.get("summary") or (plan.get("beats") or ["A new possibility appears."])[0])
        location = str(plan.get("location") or "an unfamiliar place")
        theme = str(themes[idx % len(themes)]).lower()
        scenes.append({
            "id": f"scene_{idx + 1}", "title": str(plan.get("title") or f"Scene {idx + 1}"),
            "location": location, "source_pages": plan.get("source_pages", [1, 1]),
            "visual_description": f"Cinematic illustrated view of {location}, atmospheric {theme} mood, vivid magenta and teal light, layered foreground and distant scenery.",
            "dialogue": [
                {"speaker": "Narrator", "text": f"{lead} arrives at {location}."},
                {"speaker": lead, "text": openings[idx % len(openings)]},
                {"speaker": "Narrator", "text": summary},
                {"speaker": lead, "text": f"Maybe {theme} is the clue I have been missing."},
                {"speaker": "Narrator", "text": "A distant light flickers, and the moment slowly comes into focus."},
                {"speaker": lead, "text": "Whatever happens next, I will meet it with open eyes."},
            ],
        })
    return {"title": outline.get("title", "A Story Between Pages"), "logline": outline.get("logline", ""), "scenes": scenes, "generation_mode": "local"}
