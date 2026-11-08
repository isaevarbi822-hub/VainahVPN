"""Replace the narration track of the storefront introduction video.

Requires FFmpeg + ffprobe and an existing ElevenLabs audio file.
Example:
    python scripts/replace_intro_voice.py /path/to/elevenlabs-voice.mp3

The original video is never modified. Review the output before copying it
over storefront/assets/video/vainah-orbit-30.mp4. No API keys required.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "storefront/assets/video/vainah-orbit-30.mp4"
OUTPUT = ROOT / "storefront/assets/video/vainah-orbit-30.elevenlabs.mp4"


def probe_seconds(file: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(file)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="ElevenLabs narration MP3/WAV")
    parser.add_argument("--video", type=Path, default=ORIGINAL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    for file in (args.audio, args.video):
        if not file.is_file():
            parser.error(f"File not found: {file}")
    if args.output.resolve() == args.video.resolve():
        parser.error("Refusing to overwrite the original video")

    video_duration = probe_seconds(args.video)
    audio_duration = probe_seconds(args.audio)
    if not 29.5 <= video_duration <= 30.5:
        parser.error(f"Unexpected source video duration: {video_duration:.2f}s")
    if audio_duration <= 0:
        parser.error("Audio has no valid duration")
    # Small tempo adjustment preserves complete speech without abrupt cuts.
    # Longer narration needs rewriting/re-generating to match the six scenes.
    tempo = audio_duration / (video_duration - 0.5)
    if not 0.85 <= tempo <= 1.15:
        parser.error(
            f"Audio is {audio_duration:.1f}s; target ~{video_duration - 0.5:.1f}s. "
            "Please re-generate a shorter/longer narration instead of clipping words."
        )
    if args.output.exists():
        parser.error(f"Output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n",
         "-i", str(args.video), "-i", str(args.audio),
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-af", f"atempo={tempo:.6f},aresample=48000",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-ac", "2", "-t", f"{video_duration:.3f}",
         "-movflags", "+faststart", str(args.output)],
        check=True,
    )
    print(f"Prepared: {args.output}")
    print("Review audio/visual timing and VTT captions before deployment.")


if __name__ == "__main__":
    main()
