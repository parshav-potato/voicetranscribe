# VoiceTranscribe

Windows voice transcription tool using the Whisper API via a Siemens LLM gateway. Includes a WPF GUI and a CLI, built on .NET 10.

## Prerequisites

- [.NET 10 SDK](https://dotnet.microsoft.com/download)
- [ffmpeg](https://ffmpeg.org/download.html) on PATH (for audio conversion) -- install with `winget install ffmpeg`

## Build

```sh
dotnet build
```

## Usage

### GUI

```sh
dotnet run --project src/VoiceTranscribe.Gui
```

Features: always-on-top window, global hotkey (Ctrl+Shift+R), system tray, drag-and-drop audio files, auto-paste to active window, idle transparency.

### CLI

Record from microphone:

```sh
dotnet run --project src/VoiceTranscribe.Cli
```

Transcribe an audio file:

```sh
dotnet run --project src/VoiceTranscribe.Cli -- recording.mp3
```

Transcribe with options:

```sh
dotnet run --project src/VoiceTranscribe.Cli -- recording.mp3 output.srt -f srt --translate
```

List audio devices:

```sh
dotnet run --project src/VoiceTranscribe.Cli -- --list-devices
```

## API Key

Create `~/.secret/siemens_api_key` with your Siemens API key.

## Architecture

Three-project solution:

- **VoiceTranscribe.Core** -- Shared library. Transcription pipeline, audio conversion, chunking, API client.
- **VoiceTranscribe.Cli** -- Console app. Command-line argument parsing and microphone/loopback recording.
- **VoiceTranscribe.Gui** -- WPF app. Dark themed UI with system tray, global hotkey, drag-and-drop, and auto-paste.
