#!/usr/bin/env python3
"""Generate 16 kHz mono WAV fixtures from the utterance manifest.

Uses macOS `say` when available, otherwise `espeak-ng` / `espeak`.
Audio is written under fixtures/audio/ and is intentionally not committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def _synthesize_aiff(text: str, aiff_path: Path) -> str:
    if shutil.which("say"):
        subprocess.run(
            ["say", "-o", str(aiff_path), text],
            check=True,
            capture_output=True,
        )
        return "macos-say"
    for binary in ("espeak-ng", "espeak"):
        if shutil.which(binary):
            wav_tmp = aiff_path.with_suffix(".wav")
            subprocess.run(
                [binary, "-w", str(wav_tmp), text],
                check=True,
                capture_output=True,
            )
            # Convert to AIFF-compatible path name for the ffmpeg step.
            shutil.move(wav_tmp, aiff_path.with_suffix(".wav"))
            return binary
    raise RuntimeError("No speech synthesizer found (need `say` or `espeak-ng`).")


def _to_pcm16_mono(src: Path, dst: Path, sample_rate: int) -> None:
    if shutil.which("ffmpeg"):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-sample_fmt",
                "s16",
                str(dst),
            ],
            check=True,
            capture_output=True,
        )
        return

    # Fallback: soundfile + numpy resample (linear).
    audio, sr = sf.read(src, always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float32)
    if sr != sample_rate and audio.size:
        duration = audio.size / float(sr)
        target = max(1, int(duration * sample_rate))
        x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=target, endpoint=False)
        audio = np.interp(x_new, x_old, audio).astype(np.float32)
    sf.write(dst, audio, sample_rate, subtype="PCM_16")


def generate(manifest_path: Path, audio_dir: Path, sample_rate: int) -> dict:
    manifest = _load_manifest(manifest_path)
    audio_dir.mkdir(parents=True, exist_ok=True)
    engine = None
    index = {
        "sample_rate": sample_rate,
        "manifest": str(manifest_path.relative_to(ROOT)),
        "engine": None,
        "files": [],
    }

    with tempfile.TemporaryDirectory(prefix="loopp-bench-") as tmp:
        tmp_dir = Path(tmp)
        for utt in manifest["utterances"]:
            uid = utt["id"]
            out_wav = audio_dir / f"{uid}.wav"
            raw = tmp_dir / f"{uid}.aiff"
            engine = _synthesize_aiff(utt["text"], raw)
            src = raw if raw.exists() else raw.with_suffix(".wav")
            _to_pcm16_mono(src, out_wav, sample_rate)
            info = sf.info(out_wav)
            index["files"].append(
                {
                    "id": uid,
                    "path": str(out_wav.relative_to(ROOT)),
                    "duration_s": round(info.duration, 3),
                    "text": utt["text"],
                }
            )

    index["engine"] = engine
    index_path = audio_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    return index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "fixtures" / "manifests" / "utterances.json",
    )
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=ROOT / "fixtures" / "audio",
    )
    parser.add_argument("--sample-rate", type=int, default=16000)
    args = parser.parse_args()

    index = generate(args.manifest, args.audio_dir, args.sample_rate)
    print(f"Generated {len(index['files'])} WAVs via {index['engine']} → {args.audio_dir}")
    for item in index["files"]:
        print(f"  {item['id']}: {item['duration_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
