"""
POC layer 2 — Annotation export for CamemBERT fine-tuning.

Pulls N CVs and/or job offers from the local DB, pre-annotates their text
using simple heuristics (taxonomy + regex), and writes a Label Studio-ready
JSON file. The annotator then *corrects* spans rather than starting from
scratch — typically 5x faster than blank-page annotation.

Usage:
    python -m backend.scripts.export_ner_annotations \\
        --count 100 --output ./labels/cv_batch_1.json --kind cv

Recommended workflow:
1. Run this for 200 CVs and 100 job offers.
2. Import into Label Studio with the printed labeling config.
3. Two annotators correct in parallel (target inter-annotator agreement > 0.85).
4. Export the corrected dataset, train CamemBERT (see notebooks/finetune.ipynb).

Labels emitted (Label Studio config below):
- PERSON_CANDIDATE
- JOB_TITLE
- COMPANY
- SKILL
- DEGREE
- LANGUAGE
- YEARS_EXP
- LOCATION
- EMAIL
- PHONE
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from pathlib import Path
from typing import Iterable

# Make `from app...` work when running as a module from the backend dir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import SessionLocal  # type: ignore
from app.models import CvDocument, ExtractedText, JobDocument  # type: ignore
from app.services.taxonomy import find_skills  # type: ignore

logger = logging.getLogger(__name__)

LABEL_STUDIO_CONFIG = """\
<View>
  <Labels name="label" toName="text">
    <Label value="PERSON_CANDIDATE" background="#FFA39E"/>
    <Label value="JOB_TITLE" background="#FFC069"/>
    <Label value="COMPANY" background="#AD8B00"/>
    <Label value="SKILL" background="#D3F261"/>
    <Label value="DEGREE" background="#389E0D"/>
    <Label value="LANGUAGE" background="#5CDBD3"/>
    <Label value="YEARS_EXP" background="#096DD9"/>
    <Label value="LOCATION" background="#ADC6FF"/>
    <Label value="EMAIL" background="#9254DE"/>
    <Label value="PHONE" background="#F759AB"/>
  </Labels>
  <Text name="text" value="$text"/>
</View>
"""

# ---- regex pre-annotators -------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")
_YEARS_RE = re.compile(r"\b(\d{1,2})\s*(?:ans|années|annees|years|yrs)\b", re.IGNORECASE)
_DEGREE_RE = re.compile(
    r"\b(?:master|licence|bachelor|baccalauréat|baccalaureat|doctorat|phd|"
    r"ingénieur|ingenieur|bts|dut|mba|deug|deust)\b",
    re.IGNORECASE,
)


def _spans_for_regex(text: str, pattern: re.Pattern[str], label: str) -> list[dict]:
    spans = []
    for m in pattern.finditer(text):
        spans.append({"start": m.start(), "end": m.end(), "label": label})
    return spans


def _spans_for_skills(text: str) -> list[dict]:
    """Match skills from the curated taxonomy as case-insensitive whole-word spans."""
    spans: list[dict] = []
    try:
        terms = find_skills(text) or []
    except Exception:
        return spans
    lower = text.lower()
    for term in terms:
        if not term:
            continue
        needle = term.lower()
        start = 0
        while True:
            idx = lower.find(needle, start)
            if idx < 0:
                break
            # whole-word check
            left_ok = idx == 0 or not lower[idx - 1].isalnum()
            right_ok = idx + len(needle) == len(lower) or not lower[idx + len(needle)].isalnum()
            if left_ok and right_ok:
                spans.append({"start": idx, "end": idx + len(needle), "label": "SKILL"})
            start = idx + len(needle)
    return spans


def _spans_for_name_hint(text: str) -> list[dict]:
    """Cheap heuristic for the candidate name: first 2-token capitalized run in the first 30 lines."""
    spans: list[dict] = []
    cursor = 0
    line_count = 0
    pattern = re.compile(r"\b([A-ZÀ-Ý][a-zà-ÿ]{1,}(?:\s+[A-ZÀ-Ý][a-zà-ÿ]{1,}){1,2})\b")
    for line in text.splitlines(keepends=True):
        if line_count >= 30:
            break
        line_count += 1
        m = pattern.search(line)
        if m:
            start = cursor + m.start(1)
            end = cursor + m.end(1)
            spans.append({"start": start, "end": end, "label": "PERSON_CANDIDATE"})
            break
        cursor += len(line)
    return spans


def _deduplicate(spans: Iterable[dict]) -> list[dict]:
    """Drop overlapping spans, keep the longer one — Label Studio dislikes overlaps."""
    sorted_spans = sorted(spans, key=lambda s: (s["start"], -(s["end"] - s["start"])))
    keep: list[dict] = []
    for s in sorted_spans:
        if any(not (s["end"] <= k["start"] or s["start"] >= k["end"]) for k in keep):
            continue
        keep.append(s)
    return keep


def build_predictions(text: str) -> list[dict]:
    """Run all heuristic pre-annotators and merge results."""
    raw: list[dict] = []
    raw.extend(_spans_for_regex(text, _EMAIL_RE, "EMAIL"))
    raw.extend(_spans_for_regex(text, _PHONE_RE, "PHONE"))
    raw.extend(_spans_for_regex(text, _YEARS_RE, "YEARS_EXP"))
    raw.extend(_spans_for_regex(text, _DEGREE_RE, "DEGREE"))
    raw.extend(_spans_for_skills(text))
    raw.extend(_spans_for_name_hint(text))
    return _deduplicate(raw)


def _to_label_studio(text: str, spans: list[dict], doc_meta: dict) -> dict:
    """Wrap a text + predicted spans into a Label Studio task with pre-annotations."""
    results = []
    for i, s in enumerate(spans):
        results.append(
            {
                "id": f"hint_{i}",
                "from_name": "label",
                "to_name": "text",
                "type": "labels",
                "value": {
                    "start": s["start"],
                    "end": s["end"],
                    "text": text[s["start"] : s["end"]],
                    "labels": [s["label"]],
                },
            }
        )
    return {
        "data": {"text": text, **doc_meta},
        "predictions": [
            {"model_version": "regex+taxonomy-v0", "result": results}
        ],
    }


def fetch_rows(kind: str, count: int, seed: int) -> list[tuple[str, str, dict]]:
    """Return [(file_path, text, meta)] for `count` random successful extractions of `kind`."""
    rng = random.Random(seed)
    rows: list[tuple[str, str, dict]] = []
    with SessionLocal() as session:
        if kind in ("cv", "both"):
            paths = [r.path for r in session.scalars(select(CvDocument)).all()]
            for p in paths:
                ext = session.scalar(select(ExtractedText).where(ExtractedText.file_path == p))
                if ext and ext.extraction_success and ext.extracted_text:
                    rows.append((p, ext.extracted_text, {"kind": "cv", "file_path": p}))
        if kind in ("job", "both"):
            paths = [r.path for r in session.scalars(select(JobDocument)).all()]
            for p in paths:
                ext = session.scalar(select(ExtractedText).where(ExtractedText.file_path == p))
                if ext and ext.extraction_success and ext.extracted_text:
                    rows.append((p, ext.extracted_text, {"kind": "job", "file_path": p}))
    rng.shuffle(rows)
    return rows[:count]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=100, help="Number of documents to export")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--kind", choices=("cv", "job", "both"), default="cv")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--print-config", action="store_true", help="Print Label Studio config and exit")
    args = parser.parse_args()

    if args.print_config:
        print(LABEL_STUDIO_CONFIG)
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    rows = fetch_rows(args.kind, args.count, args.seed)
    if not rows:
        logger.error("No matching documents found in DB (kind=%s)", args.kind)
        return 2

    tasks = []
    for path, text, meta in rows:
        spans = build_predictions(text)
        tasks.append(_to_label_studio(text, spans, meta))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)

    logger.info("Wrote %d tasks to %s", len(tasks), args.output)
    logger.info("Label Studio config (paste in Project → Labeling Setup → Code):\n%s", LABEL_STUDIO_CONFIG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
