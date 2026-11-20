"""Shared evaluation helpers: WER, invoice ID hit-rate, resource probes."""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import psutil
from jiwer import wer as jiwer_wer

# Canonical INV-#### plus common ASR spellings (Invi/envy, spaced I N V, glued INV1042).
_INVOICE_RE = re.compile(
    r"\b(?:inv(?:oice)?|invi|envy|invee|env)\s*[-\s]?\s*(\d{3,6})\b",
    re.IGNORECASE,
)
_INVOICE_SPACED_RE = re.compile(
    r"\bi\s*n\s*v\s*[-\s]?\s*(\d{3,6})\b",
    re.IGNORECASE,
)
_LETTER_DIGIT = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"[^\w\s\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_wer(reference: str, hypothesis: str) -> float:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return float(jiwer_wer(ref, hyp))


def extract_invoice_ids(text: str) -> set[str]:
    """Pull INV-#### style IDs, including lightly spoken / ASR-mangled variants."""
    ids: set[str] = set()
    for pattern in (_INVOICE_RE, _INVOICE_SPACED_RE):
        for match in pattern.finditer(text):
            ids.add(f"INV-{match.group(1)}")

    # "I N V one zero four two" / "invoice one zero four two"
    spoken = re.search(
        r"(?:i\s*n\s*v|invoice|invi|envy)\s+((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|\d)\s*){3,6})",
        text.lower(),
    )
    if spoken:
        digits = []
        for tok in spoken.group(1).split():
            if tok.isdigit():
                digits.append(tok)
            elif tok in _LETTER_DIGIT:
                digits.append(_LETTER_DIGIT[tok])
        if digits:
            ids.add("INV-" + "".join(digits))
    return ids


def invoice_recall(expected: list[str], hypothesis: str) -> dict[str, Any]:
    if not expected:
        return {"applicable": False, "expected": [], "found": [], "hit_rate": None}
    found = extract_invoice_ids(hypothesis)
    exp = {e.upper().replace(" ", "") for e in expected}
    # normalize INV-1042 forms
    exp_norm = set()
    for e in exp:
        m = _INVOICE_RE.search(e) or _INVOICE_RE.search(e.replace("INV", "INV-"))
        if m:
            exp_norm.add(f"INV-{m.group(1)}")
        elif e.startswith("INV"):
            exp_norm.add(e if "-" in e else e.replace("INV", "INV-", 1))
        else:
            exp_norm.add(e)
    hits = exp_norm & found
    return {
        "applicable": True,
        "expected": sorted(exp_norm),
        "found": sorted(found),
        "hit_rate": (len(hits) / len(exp_norm)) if exp_norm else None,
        "hits": sorted(hits),
    }


@dataclass
class ResourceSample:
    rss_mb: float
    cpu_percent: float


@dataclass
class ResourceMonitor:
    samples: list[ResourceSample] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    interval_s: float = 0.05

    def start(self) -> None:
        proc = psutil.Process()
        proc.cpu_percent(interval=None)  # prime

        def _loop() -> None:
            while not self._stop.wait(self.interval_s):
                rss = proc.memory_info().rss / (1024 * 1024)
                cpu = proc.cpu_percent(interval=None)
                self.samples.append(ResourceSample(rss_mb=rss, cpu_percent=cpu))

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, float]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if not self.samples:
            proc = psutil.Process()
            rss = proc.memory_info().rss / (1024 * 1024)
            return {
                "rss_mb_mean": round(rss, 1),
                "rss_mb_peak": round(rss, 1),
                "cpu_percent_mean": 0.0,
                "cpu_percent_peak": 0.0,
            }
        return {
            "rss_mb_mean": round(sum(s.rss_mb for s in self.samples) / len(self.samples), 1),
            "rss_mb_peak": round(max(s.rss_mb for s in self.samples), 1),
            "cpu_percent_mean": round(sum(s.cpu_percent for s in self.samples) / len(self.samples), 1),
            "cpu_percent_peak": round(max(s.cpu_percent for s in self.samples), 1),
        }


@contextmanager
def measure_inference(sample_resources: bool = True):
    monitor = ResourceMonitor() if sample_resources else None
    t0 = time.perf_counter()
    if monitor:
        monitor.start()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - t0
        resources = monitor.stop() if monitor else {}
        # stash on the context via a simple namespace
        measure_inference.last = {"latency_s": elapsed, "resources": resources}  # type: ignore[attr-defined]


def last_measurement() -> dict[str, Any]:
    return getattr(measure_inference, "last", {"latency_s": None, "resources": {}})
