"""Merge YouTube auto-caption cues into sentence-level cues.

Auto-generated captions are emitted as short rolling fragments, and each new
fragment usually repeats the tail of the previous one ("One of the" → "One of
the" → "One of the most popular OCR"). Concatenating them naively duplicates
text, which then gets translated twice. This module removes the overlap before
the fragments are handed to the translator.
"""

import re


def _overlap(previous, upcoming):
    """Length of the longest suffix of `previous` that is a prefix of `upcoming`."""
    for size in range(min(len(previous), len(upcoming)), 0, -1):
        if previous.endswith(upcoming[:size]):
            return size
    return 0


def merge_rolling(cues, max_chars=110, min_sentence=25):
    """Return sentence-ish cues built from rolling caption fragments."""
    merged, buffer = [], None

    def flush():
        nonlocal buffer
        if buffer and buffer["text"].strip():
            merged.append(buffer)
        buffer = None

    for cue in cues:
        text = " ".join(cue["text"].split())
        if not text:
            continue
        if buffer is None:
            buffer = dict(cue)
            buffer["text"] = text
            continue

        previous = buffer["text"]
        if text == previous:
            buffer["end"] = cue["end"]
        elif text.startswith(previous):
            buffer["text"] = text
            buffer["end"] = cue["end"]
        elif previous.endswith(text):
            buffer["end"] = cue["end"]
        else:
            combined = (previous + " " + text[_overlap(previous, text):]).strip()
            if len(combined) > max_chars:
                flush()
                buffer = dict(cue)
                buffer["text"] = text
            else:
                buffer["text"] = combined
                buffer["end"] = cue["end"]

        if buffer and len(buffer["text"]) >= min_sentence and re.search(r"[.?!]$", buffer["text"]):
            flush()

    flush()
    for position, cue in enumerate(merged, start=1):
        cue["index"] = position
    return merged
