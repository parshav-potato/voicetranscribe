# VoiceTranscribe

Minimalistic voice transcription tool using the Whisper API (via Siemens LLM gateway). Includes a small always-on-top GUI and a full-featured CLI.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (Python package manager)
- [ffmpeg](https://ffmpeg.org/download.html) on PATH (for audio conversion) — install with `winget install ffmpeg`
- API key saved to `~/.secret/siemens_api_key`

## Setup

```sh
git clone https://code.siemens.com/gert.massa/voicetranscribe.git
cd voicetranscribe
uv sync
```

`uv sync` installs Python (if needed) and all dependencies into a local `.venv`.

## Usage

### GUI

```sh
uv run python voice_transcribe_gui.py
```

Or on Windows, double-click `whistper_gui.cmd`.

The GUI is a small always-on-top window:
- Click the microphone button to start recording
- Click the stop button to finish
- The transcription is automatically copied to your clipboard

### CLI

Record from microphone and print transcription to stdout:

```sh
uv run python voice_transcribe.py
```

Transcribe an audio file:

```sh
uv run python voice_transcribe.py recording.mp3
```

Transcribe to a file with subtitle format:

```sh
uv run python voice_transcribe.py recording.mp3 output.srt -f srt
```

Translate to English:

```sh
uv run python voice_transcribe.py recording.mp3 --translate
```

Record system audio (Windows, requires PyAudioWPatch):

```sh
uv run python voice_transcribe.py --loopback
```

List audio devices:

```sh
uv run python voice_transcribe.py --list-devices
```

### CLI Options

| Option | Description |
|---|---|
| `-l`, `--language` | ISO-639-1 language code (e.g. `en`, `de`). Omit for auto-detect |
| `-p`, `--prompt` | Guide the model with context (names, terms, style) |
| `-f`, `--format` | Output format: `json`, `text`, `srt`, `vtt`, `verbose_json` |
| `-t`, `--temperature` | Sampling temperature 0-1 (lower = more deterministic) |
| `--translate` | Translate audio to English |
| `--loopback` | Record system audio instead of microphone (Windows/WASAPI) |
| `-d`, `--device` | Record from a specific audio device index |
| `--list-devices` | List available audio devices and exit |

## How it works

Audio is recorded via PyAudio, converted to MP3 with ffmpeg, and sent to the Whisper API (`whisper-large-v3-turbo` model). Large files are automatically split into 10-minute chunks with overlap to avoid cutting words at boundaries.

Live recordings are saved to `~/Documents/Sound Recordings/` with timestamps.
