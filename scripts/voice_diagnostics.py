"""Check Nova's local Vosk model and active microphone.

Run a passive configuration check:
    python scripts/voice_diagnostics.py

Run a real wake-word listening test for 20 seconds:
    python scripts/voice_diagnostics.py --listen 20
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sounddevice as sd

from modules.input_hub.wake_word import WakeWordConfig, WakeWordDetector


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Nova wake word")
    parser.add_argument(
        "--listen",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="listen for the wake word for a bounded number of seconds",
    )
    args = parser.parse_args()

    config = WakeWordConfig.from_environment()
    print(f"Vosk model: {config.model_path}")
    print(f"Wake word: {config.wake_word!r}")
    print(f"Detector available: {config.available}")

    try:
        default_input = sd.default.device[0]
        device = sd.query_devices(default_input, "input")
        print(f"Input device: [{default_input}] {device['name']}")
        sd.check_input_settings(
            device=default_input,
            channels=1,
            dtype="int16",
            samplerate=config.sample_rate,
        )
        print(f"Audio format: OK ({config.sample_rate} Hz mono int16)")
    except Exception as exc:
        print(f"Microphone error: {exc}", file=sys.stderr)
        return 2

    if not config.available:
        print(
            "Install the model with: python -m vosk_install",
            file=sys.stderr,
        )
        return 3

    detector = WakeWordDetector(config)
    try:
        from vosk import SetLogLevel

        SetLogLevel(-1)
        detector._load_model()
    except Exception as exc:
        print(f"Vosk load error: {exc}", file=sys.stderr)
        return 4
    print("Vosk runtime: OK")

    if args.listen <= 0:
        return 0

    deadline = time.monotonic() + max(1.0, args.listen)
    print(f"Say «{config.wake_word.title()}» (timeout {args.listen:g}s)…")
    capture = detector.wait_for_command(
        should_abort=lambda: time.monotonic() >= deadline,
    )
    if not capture.success:
        print(f"Not detected: {capture.error}", file=sys.stderr)
        return 5
    print(f"Detected by Vosk: {capture.detected_text!r}")
    if capture.audio_path is not None:
        capture.audio_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
