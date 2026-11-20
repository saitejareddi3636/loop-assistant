#!/usr/bin/env python3
"""Isolated STT backend loaders for the benchmarking suite.

These adapters intentionally do not import from api/app so production code
is never modified or coupled to benchmark-only models.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import soundfile as sf
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


class STTBackend(ABC):
    id: str
    display_name: str

    @abstractmethod
    def load(self) -> float:
        """Load weights; return load latency seconds."""

    @abstractmethod
    def transcribe(self, wav_path: Path) -> str:
        """Return hypothesis text for a 16 kHz mono WAV."""

    def unload_hint(self) -> None:
        """Best-effort release of large handles between model families."""
        return


class MoonshineTinyBackend(STTBackend):
    id = "moonshine_tiny"
    display_name = "Moonshine Tiny (ONNX)"

    def __init__(self, model_name: str = "moonshine/tiny") -> None:
        self.model_name = model_name
        self._moonshine = None

    def load(self) -> float:
        import time

        import moonshine_onnx as moonshine

        t0 = time.perf_counter()
        self._moonshine = moonshine
        asset = moonshine.ASSETS_DIR / "beckett.wav"
        if asset.exists():
            moonshine.transcribe(asset, self.model_name)
        return time.perf_counter() - t0

    def transcribe(self, wav_path: Path) -> str:
        assert self._moonshine is not None
        result = self._moonshine.transcribe(wav_path, self.model_name)
        if isinstance(result, list):
            return (result[0] if result else "").strip()
        return str(result).strip()


class MoonshineStreamingMediumBackend(STTBackend):
    """Offline full-utterance decode of Immortalizer merged-decoder INT8 export."""

    id = "moonshine_streaming_medium"
    display_name = "Moonshine Streaming Medium (ONNX INT8)"

    def __init__(self, hf_repo: str = "Immortalizer/moonshine-streaming-medium-onnx") -> None:
        self.hf_repo = hf_repo
        self._encoder: ort.InferenceSession | None = None
        self._decoder: ort.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._cfg: dict[str, Any] = {}
        self._past_names: list[str] = []

    def load(self) -> float:
        import time

        t0 = time.perf_counter()
        CACHE.mkdir(parents=True, exist_ok=True)
        enc_path = hf_hub_download(
            self.hf_repo,
            "encoder_model_quantized.onnx",
            cache_dir=str(CACHE / "hf"),
        )
        dec_path = hf_hub_download(
            self.hf_repo,
            "decoder_model_merged_quantized.onnx",
            cache_dir=str(CACHE / "hf"),
        )
        tok_path = hf_hub_download(
            self.hf_repo,
            "tokenizer.json",
            cache_dir=str(CACHE / "hf"),
        )
        # Architecture metadata lives on the upstream Useful Sensors card.
        cfg_path = hf_hub_download(
            "UsefulSensors/moonshine-streaming-medium",
            "config.json",
            cache_dir=str(CACHE / "hf"),
        )
        self._cfg = json.loads(Path(cfg_path).read_text())
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        providers = ["CPUExecutionProvider"]
        self._encoder = ort.InferenceSession(enc_path, sess_options=opts, providers=providers)
        self._decoder = ort.InferenceSession(dec_path, sess_options=opts, providers=providers)
        self._tokenizer = Tokenizer.from_file(tok_path)
        self._past_names = [
            i.name
            for i in self._decoder.get_inputs()
            if i.name.startswith("past_key_values")
        ]
        self._present_names = [
            o.name for o in self._decoder.get_outputs() if o.name.startswith("present.")
        ]
        return time.perf_counter() - t0

    def _empty_past(self, batch: int) -> dict[str, np.ndarray]:
        cfg = self._cfg
        n_heads = int(cfg["num_key_value_heads"])
        head_dim = int(cfg.get("head_dim") or (cfg["hidden_size"] // cfg["num_attention_heads"]))
        past: dict[str, np.ndarray] = {}
        for name in self._past_names:
            past[name] = np.zeros([batch, n_heads, 0, head_dim], dtype=np.float32)
        return past

    def transcribe(self, wav_path: Path) -> str:
        assert self._encoder and self._decoder and self._tokenizer
        audio, sr = sf.read(wav_path, dtype="float32", always_2d=False)
        if getattr(audio, "ndim", 1) > 1:
            audio = np.mean(audio, axis=1)
        if sr != 16000 and audio.size:
            duration = audio.size / float(sr)
            target = max(1, int(duration * 16000))
            x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
            x_new = np.linspace(0.0, 1.0, num=target, endpoint=False)
            audio = np.interp(x_new, x_old, audio).astype(np.float32)
        audio = np.asarray(audio, dtype=np.float32)
        # Streaming encoder reshape expects length divisible by 80 (5 ms @ 16 kHz).
        frame = 80
        remainder = audio.size % frame
        if remainder:
            audio = np.pad(audio, (0, frame - remainder))
        audio = audio[None, :]
        attention_mask = np.ones(audio.shape, dtype=np.int64)

        enc_feeds: dict[str, Any] = {"input_values": audio}
        enc_input_names = {i.name for i in self._encoder.get_inputs()}
        if "attention_mask" in enc_input_names:
            enc_feeds["attention_mask"] = attention_mask
        encoder_outputs = self._encoder.run(None, enc_feeds)[0]

        cfg = self._cfg
        bos = int(cfg.get("decoder_start_token_id", cfg.get("bos_token_id", 1)))
        eos = int(cfg.get("eos_token_id", 2))
        max_pos = int(cfg.get("max_position_embeddings", 2048))
        batch = encoder_outputs.shape[0]
        generated = np.array([[bos]] * batch, dtype=np.int64)
        past = self._empty_past(batch)

        # Bound generation: ~6 tokens/sec of audio (Moonshine heuristic) + small pad.
        audio_s = audio.shape[-1] / 16000.0
        max_len = min(max(8, int(audio_s * 6) + 8), max_pos)

        dec_input_names = {i.name for i in self._decoder.get_inputs()}
        present_to_past = {
            pname: "past_key_values." + pname[len("present.") :]
            for pname in self._present_names
        }

        for step in range(max_len):
            use_cache = step > 0
            feeds: dict[str, Any] = {
                "input_ids": generated[:, -1:].astype(np.int64),
                "encoder_hidden_states": encoder_outputs,
                **past,
            }
            if "use_cache_branch" in dec_input_names:
                feeds["use_cache_branch"] = np.array([use_cache], dtype=bool)

            out_names = [o.name for o in self._decoder.get_outputs()]
            outputs = self._decoder.run(None, feeds)
            out_map = dict(zip(out_names, outputs))
            logits = out_map["logits"]
            next_tokens = logits[:, -1].argmax(-1, keepdims=True).astype(np.int64)

            for present_name, past_name in present_to_past.items():
                # Refresh decoder self-attn every step; encoder cross-attn only on step 0.
                if (not use_cache) or (".decoder." in past_name):
                    past[past_name] = out_map[present_name]

            generated = np.concatenate([generated, next_tokens], axis=-1)
            if (next_tokens == eos).all():
                break

        text = self._tokenizer.decode(generated[0].tolist(), skip_special_tokens=True)
        return text.strip()

    def unload_hint(self) -> None:
        self._encoder = None
        self._decoder = None
        self._tokenizer = None


class ParakeetBackend(STTBackend):
    id = "parakeet_0_6b"
    display_name = "NVIDIA Parakeet TDT 0.6B V2 (ONNX)"

    def __init__(self, model_name: str = "nemo-parakeet-tdt-0.6b-v2") -> None:
        self.model_name = model_name
        self._model = None

    def load(self) -> float:
        import time

        import onnx_asr

        t0 = time.perf_counter()
        # Prefer int8 when available to keep RAM realistic on 8 GB hosts.
        try:
            self._model = onnx_asr.load_model(self.model_name, quantization="int8")
            self.quantization = "int8"
        except Exception:
            self._model = onnx_asr.load_model(self.model_name)
            self.quantization = "fp32"
        return time.perf_counter() - t0

    def transcribe(self, wav_path: Path) -> str:
        assert self._model is not None
        result = self._model.recognize(str(wav_path))
        if isinstance(result, list):
            return (result[0] if result else "").strip()
        return str(result).strip()

    def unload_hint(self) -> None:
        self._model = None


def build_backend(cfg: dict[str, Any]) -> STTBackend:
    backend = cfg["backend"]
    if backend == "moonshine_onnx":
        return MoonshineTinyBackend(model_name=cfg.get("model_name", "moonshine/tiny"))
    if backend == "moonshine_streaming_onnx":
        return MoonshineStreamingMediumBackend(hf_repo=cfg.get("hf_repo"))
    if backend == "onnx_asr":
        return ParakeetBackend(model_name=cfg.get("model_name", "nemo-parakeet-tdt-0.6b-v2"))
    raise ValueError(f"Unknown STT backend: {backend}")
