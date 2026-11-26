"""Deterministic structural quality rules for staging records."""

import re
from collections import Counter

from tools.corpus_workflow import CJK


FILTER_VERSION = "0.2.0"
CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
PLACEHOLDER = re.compile(r"(?:_COUNT_|<[^>]{1,80}>|\{[^{}]{1,80}\})")
REPEATED = re.compile(r"(.)\1{3,}")
META_PREFIX = re.compile(r"^(?:记者|本报讯|原标题|来源[:：]|责任编辑)")
TRAILING_CONNECTOR = re.compile(r"(?:与|和|及|但|因为|如果|以及|将|为|并)$")
PUNCTUATION = set("，。！？；：、,.!?;:")
OPENERS = {"（": "）", "(": ")", "[": "]", "【": "】"}


def classify(row):
    text = row.get("text", "") if isinstance(row, dict) else ""
    flags = []
    if not isinstance(text, str):
        flags.append("text_not_string")
        text = ""
    if "\n" in text or "\r" in text:
        flags.append("internal_newline")
    if "\\n" in text:
        flags.append("escaped_newline")
    if CONTROL.search(text):
        flags.append("control_character")
    if PLACEHOLDER.search(text):
        flags.append("placeholder")
    if len(text) < 4:
        flags.append("too_short")
    if len(text) > 160:
        flags.append("too_long")
    if not CJK.search(text):
        flags.append("no_chinese")
    if REPEATED.search(text):
        flags.append("repeated_character")
    if len(text) and sum(char in PUNCTUATION for char in text) / len(text) > 0.45:
        flags.append("punctuation_heavy")
    if META_PREFIX.search(text):
        flags.append("metadata_prefix")
    if TRAILING_CONNECTOR.search(text):
        flags.append("trailing_connector")
    for opener, closer in OPENERS.items():
        if text.count(opener) != text.count(closer):
            flags.append("unmatched_bracket")
            break
    hard = {"text_not_string", "control_character", "placeholder", "too_short", "too_long", "no_chinese",
            "repeated_character"}
    status = "rejected" if hard.intersection(flags) else "review" if flags else "accepted"
    return {"status": status, "flags": sorted(set(flags)), "filter_version": FILTER_VERSION}


def filter_rows(rows, accepted, review, rejected, filter_out):
    counts = Counter()
    flags = Counter()
    sources = Counter()
    for row in rows:
        quality = classify(row)
        output = {**row, "quality": quality}
        status = quality["status"]
        counts[status] += 1
        sources[row.get("source_id", "unknown")] += 1
        flags.update(quality["flags"])
        target = accepted if status == "accepted" else review if status == "review" else rejected
        line = __import__("json").dumps(output, ensure_ascii=False, sort_keys=True) + "\n"
        target.write(line)
        if status != "accepted":
            filter_out.write(line)
    return {"counts": dict(sorted(counts.items())), "flags": dict(sorted(flags.items())),
            "sources": dict(sorted(sources.items())), "filter_version": FILTER_VERSION}
