#!/usr/bin/env python3
"""Lightweight checks for metric helpers (no model downloads)."""

from __future__ import annotations

from metrics import compute_wer, extract_invoice_ids, invoice_recall, normalize_text


def test_normalize_and_wer() -> None:
    assert normalize_text("Hello, World!") == "hello world"
    assert compute_wer("a b c", "a b c") == 0.0
    assert compute_wer("a b c", "a x c") > 0.0


def test_invoice_extraction() -> None:
    assert "INV-1042" in extract_invoice_ids("Please refund INV-1042 now")
    assert "INV-1042" in extract_invoice_ids("invoice one zero four two")
    recall = invoice_recall(["INV-1042"], "Looking at inv-1042")
    assert recall["applicable"] is True
    assert recall["hit_rate"] == 1.0


if __name__ == "__main__":
    test_normalize_and_wer()
    test_invoice_extraction()
    print("test_metrics: ok")
