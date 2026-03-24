# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VoiceTranscribe is a Windows voice transcription tool using the Whisper API via a Siemens LLM gateway (`https://api.siemens.com/llm/v1`). It has a WPF GUI and a CLI, built on .NET 10.

## Commands

```sh
# Build all projects
dotnet build

# Run GUI
dotnet run --project src/VoiceTranscribe.Gui

# Run CLI (microphone recording)
dotnet run --project src/VoiceTranscribe.Cli

# Run CLI (transcribe file)
dotnet run --project src/VoiceTranscribe.Cli -- recording.mp3

# Run CLI (with options)
dotnet run --project src/VoiceTranscribe.Cli -- recording.mp3 output.srt -f srt --translate
```

There are no tests in this project.

## Architecture

Three-project solution:

- **`VoiceTranscribe.Core`** -- Shared library (net10.0). Contains `WhisperApiClient`, `TranscriptionOrchestrator`, `AudioConverter`, `AudioChunker`, `SubtitleMerger`, `ApiKeyProvider`, and model types. Zero external NuGet dependencies.
- **`VoiceTranscribe.Cli`** -- Console app (net10.0). Uses `System.CommandLine` for argument parsing and `NAudio` for microphone/WASAPI loopback recording. Imports Core for transcription.
- **`VoiceTranscribe.Gui`** -- WPF app (net10.0-windows). Uses `CommunityToolkit.Mvvm` for MVVM, `NAudio` for recording, `H.NotifyIcon.Wpf` for system tray, `NHotkey.Wpf` for global hotkey. Custom dark Catppuccin theme via `WindowChrome`.

Key integration point: both CLI and GUI use `TranscriptionOrchestrator` from Core for the full transcription pipeline.

## Key Details

- API key is read from `~/.secret/siemens_api_key`
- Requires ffmpeg on PATH for audio conversion
- Windows-only: WPF GUI, P/Invoke for auto-paste, system tray, global hotkey
- Settings persisted at `~/.config/voicetranscribe/settings.json`
- Catppuccin Mocha color palette defined in `Themes/Dark.xaml`
