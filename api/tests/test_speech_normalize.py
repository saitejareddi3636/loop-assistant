from app.voice.speech_normalize import normalize_for_speech, normalize_transcript_ids
from app.voice.pocket_tts import speakable_sentences


def test_normalize_invoice_ticket_and_money():
    text = "Refund INV-1042 for $29.00. Ticket TCK-BAB92050 is open."
    out = normalize_for_speech(text)
    assert "invoice I N V one zero four two" in out
    assert "twenty-nine dollars" in out
    assert "ticket T C K" in out
    assert "b a b" in out.lower() or "BAB" not in out


def test_no_duplicate_invoice_or_ticket_wording():
    inv = normalize_for_speech("Refund on invoice INV-1042 please.")
    assert inv.count("invoice") == 1
    assert "invoice invoice" not in inv.lower()
    assert "invoice I N V one zero four two" in inv

    tck = normalize_for_speech("I opened ticket TCK-BAB92050 for you.")
    assert tck.lower().count("ticket") == 1
    assert "ticket ticket" not in tck.lower()
    assert "ticket T C K" in tck


def test_money_with_cents():
    out = normalize_for_speech("The charge was $29.50.")
    assert "twenty-nine dollars and fifty cents" in out
    assert "five zero" not in out

    out_one = normalize_for_speech("That is $1.01.")
    assert "one dollar and one cent" in out_one


def test_speakable_sentences_applies_normalization():
    parts = speakable_sentences("Your refund for **INV-1042** is $29.50.")
    joined = " ".join(parts)
    assert "invoice I N V" in joined
    assert "twenty-nine dollars and fifty cents" in joined
    assert "**" not in joined


def test_normalize_transcript_restores_invoice_hyphen():
    assert normalize_transcript_ids("charged twice on INV1042 for $29") == (
        "charged twice on INV-1042 for $29"
    )
    assert normalize_transcript_ids("ticket TCKBAB92050") == "ticket TCK-BAB92050"
