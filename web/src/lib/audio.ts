/** Encode mono PCM16 as a WAV Blob for dictation upload. */
export function encodeWav(pcm16: Int16Array, sampleRate: number): Blob {
  const dataSize = pcm16.byteLength;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, dataSize, true);

  new Uint8Array(buffer, 44).set(new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcm16.byteLength));
  return new Blob([buffer], { type: "audio/wav" });
}

/** Box-filter downsample to 16 kHz PCM16 (matches live voice capture). */
export function toPcm16k(input: Float32Array, inputRate: number): Int16Array {
  const ratio = inputRate / 16000;
  const newLen = Math.max(0, Math.floor(input.length / ratio));
  const out = new Int16Array(newLen);
  for (let i = 0; i < newLen; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.max(start + 1, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j] ?? 0;
    const s = Math.max(-1, Math.min(1, sum / (end - start)));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

export function formatTimer(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function writeString(view: DataView, offset: number, value: string) {
  for (let i = 0; i < value.length; i++) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}
