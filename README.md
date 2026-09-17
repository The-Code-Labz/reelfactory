# ReelFactory

Batch video generator daemon: TTS narration + AI images + ffmpeg subtitle burn, content-hash cached, single-binary CLI. Feed it a JSON job manifest, get `final_<job_id>_<track>.mp4` files.

## Features

- **Manifest-driven** — one JSON file describes tracks → segments (text, image prompt/file, duration, transition)
- **TTS providers** — `none` (silence, default), `edge` (edge-tts), `custom` (OpenAI-compatible `/audio/speech` endpoint). Stubs ready for openai/elevenlabs/fal/azure
- **Image providers** — `none` (rendered title card, default), `pollinations`, `local` (`image_file` per segment)
- **Subtitle burn** — drawtext-based, configurable font/size/color/outline/position
- **Content-hash caching** — identical text+voice reuses audio; identical prompt reuses images; identical segment reuses rendered mp4. Re-running a job is near-instant
- **Retry** — exponential backoff 1s/2s/4s, 3 attempts per step
- **Daemon mode** — watches manifest mtime (5s poll), re-runs on change
- **State & report** — `state.json` + `report.json` under `<output_dir>/.reelfactory/`
- **Secrets** — API keys/webhook secrets never logged; report stores a redacted config copy
- **Permissions** — `.reelfactory/` created mode 0700

## Requirements

- Python 3.11+ (stdlib only for `none` providers)
- `ffmpeg` + `ffprobe` on PATH
- Optional: `edge-tts` (`pip install edge-tts`) for the `edge` voice provider

## Install

```bash
git clone https://github.com/The-Code-Labz/reelfactory.git
cd reelfactory
pip install -e .            # or just run: python -m reelfactory --help
```

## Usage

```bash
python -m reelfactory validate examples/jobs.example.json
python -m reelfactory run    examples/jobs.example.json
python -m reelfactory daemon examples/jobs.example.json   # watch + auto re-run
python -m reelfactory status examples/jobs.example.json
python -m reelfactory --version
```

Outputs land in `output/final_<job_id>_<track>.mp4` plus `output/.reelfactory/{state.json,report.json}`.

## Manifest schema

```jsonc
{
  "output_dir": "./output",
  "voice":    { "provider": "none|edge|custom", "voice": "en-US-AriaNeural",
                "rate": "+0%", "pitch": "+0Hz",
                "model": null, "base_url": null, "api_key": null },
  "subtitle": { "enabled": true, "font": "DejaVu Sans", "font_size": 48,
                "color": "white", "outline_color": "black", "outline": 2,
                "position": "bottom|center|top", "margin_v": 60 },
  "image":    { "provider": "none|pollinations|local", "width": 1080, "height": 1920,
                "seed": null, "model": null, "api_key": null },
  "render":   { "width": 1080, "height": 1920, "fps": 30,
                "video_codec": "libx264", "video_bitrate": "4M",
                "audio_codec": "aac", "audio_bitrate": "192k",
                "preset": "medium", "crf": null },
  "publish":  { "local_dir": null, "webhook_url": null, "webhook_secret": null },
  "tracks": [
    { "name": "intro",
      "segments": [
        { "text": "Hello world", "duration_sec": 3 },
        { "text": "Second line", "image_prompt": "a sunset over the ocean",
          "duration_sec": 4 }
      ] }
  ]
}
```

Each segment needs `text` and/or `image_file`/`image_prompt`. `duration_sec` required only when there is no TTS audio to size the segment.

## PyInstaller single binary

```bash
pip install pyinstaller
pyinstaller --onefile --name reelfactory -m reelfactory
# embed the git SHA: rebuild with --version-file or patch reelfactory/__init__.py
```

## GitHub Actions binaries

`.github/workflows/release.yml` builds Linux/macOS/Windows binaries with PyInstaller on every tag and attaches them to the release.

## License

MIT — see [LICENSE](LICENSE).
