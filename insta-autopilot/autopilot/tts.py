from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts

from .media import probe_duration


async def _synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words: list[dict] = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})
    return words


def synthesize(text: str, voice: str, rate: str, out: Path, retries: int = 3):
    """Speak `text` to an mp3. Returns (word timings, duration in seconds).

    If the voice service sends no word timings, they are spread evenly instead.
    """
    last: Exception | None = None
    for _ in range(retries):
        try:
            words = asyncio.run(_synth(text, voice, rate, out))
            break
        except Exception as exc:  # network hiccups are common
            last = exc
    else:
        raise RuntimeError(f"Text-to-speech failed: {last}")

    duration = probe_duration(out)
    if not words:
        tokens = text.split()
        step = duration / max(len(tokens), 1)
        words = [{"text": t, "start": i * step, "end": (i + 1) * step}
                 for i, t in enumerate(tokens)]
    return words, duration


def chunk_words(words: list[dict], per_chunk: int = 3, max_chars: int = 24):
    """Group words into short on-screen caption chunks: [(text, start, end)]."""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x["text"] for x in cur)
        ends_sentence = w["text"].endswith((".", "!", "?", ","))
        if len(cur) >= per_chunk or len(text) >= max_chars or ends_sentence:
            chunks.append([text, cur[0]["start"], cur[-1]["end"]])
            cur = []
    if cur:
        chunks.append([" ".join(x["text"] for x in cur), cur[0]["start"], cur[-1]["end"]])
    # hold each caption until the next one starts so nothing flickers
    for i in range(len(chunks) - 1):
        chunks[i][2] = max(chunks[i][2], chunks[i + 1][1])
    return [tuple(c) for c in chunks]
