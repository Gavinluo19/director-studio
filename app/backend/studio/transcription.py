"""Local-only ASR. Run in a disposable subprocess to release MLX memory."""
from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path

MODEL = "mlx-community/whisper-large-v3-turbo"


def model_path() -> Path | None:
    root = Path.home()/".cache/huggingface/hub"/("models--"+MODEL.replace("/", "--"))
    ref = root/"refs/main"
    if ref.exists():
        path = root/"snapshots"/ref.read_text().strip()
        if (path/"config.json").exists() and any(path.glob("*.safetensors")):
            return path
    return next((p for p in sorted((root/"snapshots").glob("*"), reverse=True)
                 if (p/"config.json").exists() and any(p.glob("*.safetensors"))), None)


def readiness() -> dict:
    installed = importlib.util.find_spec("mlx_whisper") is not None
    cached = model_path() is not None
    supported = platform.system() == "Darwin" and platform.machine() == "arm64"
    return {"id":"local-whisper", "name":"本地 Whisper", "model":MODEL,
            "ready":installed and cached and supported, "installed":installed,
            "cached":cached, "supported":supported, "cash_cost":0,
            "note":"素材留在本机；使用本地计算资源。" if installed and cached and supported
            else "需要 Apple Silicon、transcription 可选依赖和本地 Whisper 权重；不会自动上传到云端。"}


def main():
    source, destination, language = sys.argv[1:4]
    if not readiness()["ready"]:
        raise RuntimeError(readiness()["note"])
    import mlx_whisper
    options = {"language":language} if language not in {"auto", ""} else {}
    result = mlx_whisper.transcribe(source, path_or_hf_repo=str(model_path()),
                                   word_timestamps=False, verbose=False, **options)
    segments = [{"start":s["start"], "end":s["end"], "original_text":s["text"].strip(),
                 "text":s["text"].strip()} for s in result["segments"] if s["end"]>s["start"] and s["text"].strip()]
    if not segments:
        raise RuntimeError("没有识别出可用语音；请检查录音或导入带时间戳字幕。")
    Path(destination).write_text(json.dumps({"segments":segments,"language":result.get("language",language)},ensure_ascii=False))


if __name__ == "__main__":
    main()
