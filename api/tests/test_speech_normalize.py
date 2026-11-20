from app.voice.speech_normalize import normalize_for_speech, normalize_transcript_ids
from app.voice.pocket_tts import speakable_sentences


def test_normalize_invoice_ticket_and_money():
    text = "Refund INV-1042 for $29.00. Ticket TCK-BAB92050 is open."
    out = normalize_for_speech(text)
    assert "invoice I N V one zero four two" in out
    assert "twenty-nine dollars" in out
    assert "ticket T C K" in out
    assert "b a b" in out.lower() or "BAB" not in out


def test_speakable_sentences_applies_normalization():
    parts = speakable_sentences("Your refund for **INV-1042** is $29.00.")
    joined = " ".join(parts)
    assert "invoice I N V" in joined
    assert "twenty-nine dollars" in joined
    assert "**" not in joined


def test_normalize_transcript_restores_invoice_hyphen():
    assert normalize_transcript_ids("charged twice on INV1042 for $29") == (
        "charged twice on INV-1042 for $29"
    )
    assert normalize_transcript_ids("ticket TCKBAB92050") == "ticket TCK-BAB92050"
