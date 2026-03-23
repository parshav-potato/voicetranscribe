#!/usr/bin/python3 -X utf8
# Set PYTHONUTF8=1 in the environment to enable UTF-8 mode
import sys
import os
import os.path
import json
import re
import argparse
import subprocess
import tempfile
import wave
import struct
import threading
from datetime import datetime
from requests import post, get

# Inlined from copilot_common.py for self-contained operation

def ensure_utf8_mode():
    """Re-exec with UTF-8 mode if not already enabled. Exits if re-exec needed."""
    if os.environ.get("PYTHONUTF8") != "1":
        os.environ["PYTHONUTF8"] = "1"
        sys.exit(os.system(f'"{sys.executable}" -X utf8 {" ".join(sys.argv)}'))

def get_api_key() -> str:
    """Read API key from file in home directory."""
    filepath = os.path.expanduser("~/.secret/siemens_api_key")
    if os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()
    
    raise RuntimeError(
        f"API key file not found: {filepath}\n"
        "Please create this file with your Siemens API key."
    )

# Supported audio formats for Whisper
AUDIO_EXTENSIONS = {
    ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".flac", ".ogg", ".opus"
}

WHISPER_MODEL = "whisper-large-v3-turbo"

# Formats that need conversion to mp3 before sending
NEEDS_CONVERSION = {".m4a", ".mp4", ".ogg", ".opus", ".webm", ".flac", ".mpeg", ".mpga"}

MAX_UPLOAD_SIZE = 24 * 1024 * 1024  # 24MB conservative limit (API max is 25MB)
CHUNK_DURATION = 600  # 10 minutes per chunk
CHUNK_OVERLAP = 5     # 5 second overlap between chunks to avoid splitting mid-word

ROOT_URL = "https://api.siemens.com/llm/v1"

# Directory for saving recordings and transcriptions
SAVE_DIRECTORY = os.path.join(os.path.expanduser("~"), "Documents", "Sound Recordings")

def convert_to_mp3(audio_path: str) -> str:
    """Convert audio file to mp3 format using ffmpeg.
    
    Args:
        audio_path: Path to the input audio file.
    
    Returns:
        str: Path to the temporary mp3 file.
    
    Raises:
        RuntimeError: If ffmpeg is not found or conversion fails.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-b:a", "64k", tmp.name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            os.unlink(tmp.name)
            raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
        return tmp.name
    except FileNotFoundError:
        os.unlink(tmp.name)
        raise RuntimeError("ffmpeg not found. Please install ffmpeg to transcode audio files.")

def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, ValueError):
        pass
    return 0.0

def split_audio_chunks(audio_path: str, chunk_duration: int = CHUNK_DURATION,
                       overlap: int = CHUNK_OVERLAP) -> list:
    """Split audio file into overlapping chunks using ffmpeg.
    
    Each chunk includes `overlap` seconds from the end of the previous chunk
    to avoid cutting words at boundaries.
    
    Args:
        audio_path: Path to the audio file.
        chunk_duration: Duration of each chunk in seconds.
        overlap: Overlap in seconds between consecutive chunks.
    
    Returns:
        List of (temp_path, start_seconds) tuples.
    """
    duration = get_audio_duration(audio_path)
    if duration <= 0:
        raise RuntimeError("Could not determine audio duration. Is ffprobe installed?")
    
    chunks = []
    start = 0
    step = chunk_duration - overlap  # advance by less than chunk_duration
    while start < duration:
        # Each chunk is chunk_duration long (or until end of file)
        actual_duration = min(chunk_duration, duration - start)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ss", str(start), "-t", str(actual_duration),
             "-ar", "16000", "-ac", "1", "-b:a", "64k", tmp.name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            os.unlink(tmp.name)
            for path, _ in chunks:
                if os.path.exists(path):
                    os.unlink(path)
            raise RuntimeError(f"ffmpeg chunk split failed: {result.stderr}")
        chunks.append((tmp.name, start))
        start += step
        if start >= duration:
            break
    
    return chunks

def _offset_timestamp(time_str: str, offset_sec: float, separator: str = ',') -> str:
    """Offset a timestamp (HH:MM:SS,mmm or HH:MM:SS.mmm) by offset_sec seconds."""
    parts = time_str.strip().replace(',', '.').split(':')
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    total = h * 3600 + m * 60 + s + offset_sec
    if total < 0:
        total = 0
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s = total % 60
    result = f"{h:02d}:{m:02d}:{s:06.3f}"
    if separator == ',':
        result = result.replace('.', ',')
    return result

def merge_srt_chunks(srt_texts: list, chunk_offsets: list) -> str:
    """Merge SRT chunks with adjusted timestamps and renumbered entries."""
    merged = []
    counter = 1
    for srt_text, offset in zip(srt_texts, chunk_offsets):
        blocks = re.split(r'\n\n+', srt_text.strip())
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 2:
                ts_match = re.match(
                    r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
                    lines[1] if len(lines) > 1 else ''
                )
                if ts_match:
                    start = _offset_timestamp(ts_match.group(1), offset, ',')
                    end = _offset_timestamp(ts_match.group(2), offset, ',')
                    text = '\n'.join(lines[2:])
                    merged.append(f"{counter}\n{start} --> {end}\n{text}")
                    counter += 1
    return '\n\n'.join(merged) + '\n'

def merge_vtt_chunks(vtt_texts: list, chunk_offsets: list) -> str:
    """Merge VTT chunks with adjusted timestamps."""
    merged_cues = []
    for vtt_text, offset in zip(vtt_texts, chunk_offsets):
        lines = vtt_text.strip().split('\n')
        i = 0
        # Skip WEBVTT header and metadata
        while i < len(lines) and not re.match(r'\d{2}:\d{2}', lines[i]):
            i += 1
        while i < len(lines):
            ts_match = re.match(r'([\d:.]+)\s*-->\s*([\d:.]+)', lines[i])
            if ts_match:
                start = _offset_timestamp(ts_match.group(1), offset, '.')
                end = _offset_timestamp(ts_match.group(2), offset, '.')
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i])
                    i += 1
                merged_cues.append(f"{start} --> {end}\n" + '\n'.join(text_lines))
            i += 1
    return "WEBVTT\n\n" + '\n\n'.join(merged_cues) + '\n'

def list_audio_devices():
    """List all available audio devices for debugging."""
    try:
        import pyaudio
    except ImportError:
        print("pyaudio not installed", file=sys.stderr)
        return
    
    pa = pyaudio.PyAudio()
    print("\n=== Audio Host APIs ===", file=sys.stderr)
    for i in range(pa.get_host_api_count()):
        info = pa.get_host_api_info_by_index(i)
        print(f"  [{i}] {info['name']} (devices: {info['deviceCount']})", file=sys.stderr)
    
    print("\n=== Audio Devices ===", file=sys.stderr)
    for i in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(i)
        api = pa.get_host_api_info_by_index(dev['hostApi'])
        direction = []
        if dev['maxInputChannels'] > 0:
            direction.append(f"IN:{dev['maxInputChannels']}ch")
        if dev['maxOutputChannels'] > 0:
            direction.append(f"OUT:{dev['maxOutputChannels']}ch")
        print(f"  [{i}] {dev['name']}  ({', '.join(direction)})  "
              f"[{api['name']}] {int(dev['defaultSampleRate'])}Hz", file=sys.stderr)
    
    pa.terminate()
    print("", file=sys.stderr)

def record_from_microphone(loopback: bool = False, device: int = None) -> str:
    """Record audio from the microphone or system audio output until Enter is pressed.
    
    Args:
        loopback: If True, record system audio output instead of microphone.
                  Uses WASAPI loopback on Windows (requires PyAudioWPatch).
        device: Specific device index to record from. Use --list-devices to see indices.
                Overrides default device selection. When combined with --loopback,
                opens the specified device in loopback mode.
    
    Returns:
        str: Path to the temporary mp3 file with the recording.
    
    Raises:
        RuntimeError: If pyaudio is not installed or recording fails.
    """
    try:
        import pyaudio
    except ImportError:
        raise RuntimeError(
            "pyaudio is required for live recording. Install it with:\n"
            "  pip install pyaudio\n"
            "For loopback (system audio) support on Windows:\n"
            "  pip install PyAudioWPatch"
        )
    
    pa = pyaudio.PyAudio()
    
    if device is not None:
        # User explicitly selected a device
        try:
            dev = pa.get_device_info_by_index(device)
        except Exception:
            pa.terminate()
            raise RuntimeError(
                f"Device index {device} not found.\n"
                "Run with --list-devices to see available devices."
            )
        RATE = int(dev['defaultSampleRate'])
        max_ch = dev.get('maxInputChannels', 0) or dev.get('maxOutputChannels', 0)
        CHANNELS = max(1, min(max_ch, 2))
        device_index = device
        use_loopback = loopback
        print(f"Recording from device [{device}]: {dev['name']} "
              f"({RATE}Hz, {CHANNELS}ch){' [loopback]' if use_loopback else ''}",
              file=sys.stderr)
    elif loopback:
        # Find WASAPI host API
        wasapi_index = None
        for i in range(pa.get_host_api_count()):
            info = pa.get_host_api_info_by_index(i)
            if 'wasapi' in info.get('name', '').lower():
                wasapi_index = i
                break
        
        if wasapi_index is None:
            pa.terminate()
            raise RuntimeError(
                "WASAPI not found. Loopback recording is only supported on Windows.\n"
                "Run with --list-devices to see available audio devices."
            )
        
        wasapi_info = pa.get_host_api_info_by_index(wasapi_index)
        
        # Strategy: find the default WASAPI output device, then use it as loopback
        # PyAudioWPatch exposes output devices as loopback-capable input devices
        default_output_idx = wasapi_info.get('defaultOutputDevice', -1)
        
        loopback_device = None
        
        # First, try to find a loopback device via PyAudioWPatch's method
        if hasattr(pa, 'get_loopback_device_info_generator'):
            # PyAudioWPatch provides this generator
            for loopback_dev in pa.get_loopback_device_info_generator():
                loopback_device = loopback_dev
                break  # Use the first (default) loopback device
        
        if loopback_device is None:
            # Fallback: find WASAPI output devices that we can open as loopback
            # The default output device should be openable with as_loopback=True
            if default_output_idx >= 0:
                dev = pa.get_device_info_by_index(default_output_idx)
                if dev.get('maxOutputChannels', 0) > 0:
                    # Use the output device - we'll open it with as_loopback=True
                    loopback_device = dev
        
        if loopback_device is None:
            # Last resort: any WASAPI device with output channels
            for i in range(pa.get_device_count()):
                dev = pa.get_device_info_by_index(i)
                if dev.get('hostApi') == wasapi_index and dev.get('maxOutputChannels', 0) > 0:
                    loopback_device = dev
                    break
        
        if loopback_device is None:
            pa.terminate()
            raise RuntimeError(
                "No WASAPI loopback device found.\n"
                "Run with --list-devices to see available audio devices.\n"
                "Install PyAudioWPatch for best loopback support:\n"
                "  pip install PyAudioWPatch"
            )
        
        RATE = int(loopback_device['defaultSampleRate'])
        # For loopback, use the device's output channels (not input)
        max_ch = loopback_device.get('maxInputChannels', 0) or loopback_device.get('maxOutputChannels', 0)
        CHANNELS = max(1, min(max_ch, 2))
        device_index = loopback_device['index']
        use_loopback = True
        print(f"Recording system audio from: {loopback_device['name']} "
              f"({RATE}Hz, {CHANNELS}ch)", file=sys.stderr)
    else:
        RATE = 16000
        CHANNELS = 1
        device_index = None
        use_loopback = False
        try:
            default_input = pa.get_default_input_device_info()
            print(f"Recording from: {default_input['name']}", file=sys.stderr)
        except Exception:
            print("Recording from default input device", file=sys.stderr)
    
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    
    open_kwargs = dict(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK
    )
    if use_loopback and device_index is not None:
        open_kwargs['input_device_index'] = device_index
        # PyAudioWPatch uses as_loopback=True to capture output audio
        open_kwargs['as_loopback'] = True
    elif device_index is not None:
        open_kwargs['input_device_index'] = device_index
    
    try:
        stream = pa.open(**open_kwargs)
    except Exception as e1:
        # Fallback 1: try without as_loopback (older builds)
        if use_loopback and 'as_loopback' in open_kwargs:
            del open_kwargs['as_loopback']
            try:
                stream = pa.open(**open_kwargs)
                print("Warning: opened without loopback flag — you may need PyAudioWPatch",
                      file=sys.stderr)
            except Exception as e2:
                pa.terminate()
                raise RuntimeError(
                    f"Failed to open loopback stream: {e1}\n"
                    f"Fallback also failed: {e2}\n\n"
                    "Install PyAudioWPatch for WASAPI loopback support:\n"
                    "  pip install PyAudioWPatch\n\n"
                    "Run with --list-devices to see available audio devices."
                )
        else:
            pa.terminate()
            raise RuntimeError(f"Failed to open audio stream: {e1}")
    
    frames = []
    stop_event = threading.Event()
    
    def wait_for_enter():
        input()
        stop_event.set()
    
    print("Recording... Press ENTER to stop.", file=sys.stderr)
    listener = threading.Thread(target=wait_for_enter, daemon=True)
    listener.start()
    
    try:
        while not stop_event.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    
    if not frames:
        raise RuntimeError("No audio recorded")
    
    duration = len(frames) * CHUNK / RATE
    print(f"Recorded {duration:.1f}s of audio.", file=sys.stderr)
    
    # Save as temporary wav
    tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_wav.close()
    try:
        with wave.open(tmp_wav.name, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # paInt16 = 2 bytes
            wf.setframerate(RATE)
            wf.writeframes(b"".join(frames))
        
        # Convert to mp3 for smaller upload
        mp3_path = convert_to_mp3(tmp_wav.name)
        return mp3_path
    finally:
        if os.path.exists(tmp_wav.name):
            os.unlink(tmp_wav.name)

def detect_audio_format(filepath: str) -> str:
    """Detect if the file is an audio file based on extension.
    
    Args:
        filepath: Path to the file.
    
    Returns:
        str: File extension or raises ValueError if not audio.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio format: {ext}. Supported formats: {', '.join(AUDIO_EXTENSIONS)}")
    return ext

def transcribe_audio(audio_path: str, language: str = None, prompt: str = None,
                     response_format: str = "json", temperature: float = None,
                     translate: bool = False) -> str:
    """Transcribe audio file using GitHub Copilot's Whisper API.
    
    Args:
        audio_path: Path to the audio file.
        language: ISO-639-1 language code (e.g. 'en', 'de'). None for auto-detect.
        prompt: Optional prompt to guide the model's style or provide context.
        response_format: Output format: json, text, srt, vtt, verbose_json.
        temperature: Sampling temperature (0-1). None for default.
        translate: If True, use /audio/translations endpoint (translates to English).
    
    Returns:
        str: Transcribed (or translated) text.
    
    Raises:
        Exception: If the API request fails.
    """
    api_key = get_api_key()
    
    # Detect file type
    ext = os.path.splitext(audio_path)[1].lower()
    
    # Convert unsupported formats to mp3 via ffmpeg
    wav_tmp = None
    if ext in NEEDS_CONVERSION:
        print(f"Converting {ext} to mp3 via ffmpeg...", file=sys.stderr)
        wav_tmp = convert_to_mp3(audio_path)
        send_path = wav_tmp
        mime_type = "audio/mpeg"
    else:
        send_path = audio_path
        mime_type_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
        }
        mime_type = mime_type_map.get(ext, "audio/wav")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Editor-Version": "vscode/1.85.0",
        "Editor-Plugin-Version": "GitHubCopilotChat/0.11.1",
    }
    
    # Choose endpoint: transcriptions or translations
    endpoint = "translations" if translate else "transcriptions"
    url = f"{ROOT_URL}/audio/{endpoint}"
    
    try:
        with open(send_path, "rb") as audio_file:
            files = {
                'file': (os.path.basename(send_path), audio_file, mime_type)
            }
            data = {
                'model': WHISPER_MODEL,
                'response_format': response_format,
            }
            if language:
                data['language'] = language
            if prompt:
                data['prompt'] = prompt
            if temperature is not None:
                data['temperature'] = str(temperature)
            
            response = post(url, headers=headers, files=files, data=data)
            
            if response.status_code != 200:
                raise Exception(f"Error: {response.status_code} - {response.text}")
            
            # For non-json formats, return raw text
            if response_format in ("text", "srt", "vtt"):
                # Some API endpoints return JSON even for text format
                text = response.text.strip()
                if response_format == "text" and text.startswith('{'):
                    try:
                        data = json.loads(text)
                        return data.get("text", text)
                    except (json.JSONDecodeError, AttributeError):
                        pass
                return response.text
            
            result = response.json()
            
            if "error" in result:
                raise Exception(result["error"].get("message", "Unknown error"))
            
            if response_format == "verbose_json":
                return json.dumps(result, indent=2, ensure_ascii=False)
            
            return result.get("text", "")
        
    except Exception as e:
        raise Exception(f"Transcription failed: {str(e)}")
    finally:
        if wav_tmp and os.path.exists(wav_tmp):
            os.unlink(wav_tmp)

def whistper(inname: str, fout, language: str = None, prompt: str = None,
             response_format: str = "json", temperature: float = None,
             translate: bool = False, loopback: bool = False,
             device: int = None) -> None:
    """Process audio file through Whisper for transcription.

    Automatically splits large files into chunks when they exceed the API
    upload limit (25MB). Chunks are transcribed sequentially and merged,
    with the previous chunk's tail used as prompt context for continuity.

    Args:
        inname: Input filename (must be a valid audio file, or '-' for live recording).
        fout: Output file object (must be writable).
        language: ISO-639-1 language code (e.g. 'en', 'de'). None for auto-detect.
        prompt: Optional prompt to guide the model.
        response_format: Output format: json, text, srt, vtt, verbose_json.
        temperature: Sampling temperature (0-1).
        translate: If True, translate to English instead of transcribing.
        loopback: If True, record from system audio output instead of microphone.
    """
    recorded_tmp = None
    tmp_files = []
    is_live_recording = (inname == "-")
    saved_audio_path = None
    saved_transcript_path = None

    try:
        if is_live_recording:
            recorded_tmp = record_from_microphone(loopback=loopback, device=device)
            audio_path = recorded_tmp

            # Generate timestamp-based filename for saving
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            base_filename = timestamp

            # Ensure save directory exists
            os.makedirs(SAVE_DIRECTORY, exist_ok=True)

            # Save the recorded audio to the permanent location
            saved_audio_path = os.path.join(SAVE_DIRECTORY, f"{base_filename}.mp3")
            saved_transcript_path = os.path.join(SAVE_DIRECTORY, f"{base_filename}.txt")

            # Copy the recorded file to the save location
            import shutil
            shutil.copy2(recorded_tmp, saved_audio_path)
            print(f"Audio saved to: {saved_audio_path}", file=sys.stderr)
        else:
            detect_audio_format(inname)
            audio_path = inname
        
        # Pre-convert to mp3 if needed, so we can check file size
        ext = os.path.splitext(audio_path)[1].lower()
        if ext in NEEDS_CONVERSION:
            print(f"Converting {ext} to mp3 via ffmpeg...", file=sys.stderr)
            mp3_path = convert_to_mp3(audio_path)
            tmp_files.append(mp3_path)
            audio_path = mp3_path
        
        file_size = os.path.getsize(audio_path)
        
        if file_size <= MAX_UPLOAD_SIZE:
            # Small enough — transcribe directly
            transcript = transcribe_audio(
                audio_path,
                language=language,
                prompt=prompt,
                response_format=response_format,
                temperature=temperature,
                translate=translate
            )
            fout.write(transcript)
            fout.write("\n")

            # Save transcript to file for live recordings
            if is_live_recording and saved_transcript_path:
                with open(saved_transcript_path, "w", encoding="utf-8") as tf:
                    tf.write(transcript)
                    tf.write("\n")
                print(f"Transcript saved to: {saved_transcript_path}", file=sys.stderr)
        else:
            # Too large — split into chunks and transcribe each
            size_mb = file_size / (1024 * 1024)
            print(f"File is {size_mb:.1f}MB (limit {MAX_UPLOAD_SIZE // (1024*1024)}MB), "
                  f"splitting into {CHUNK_DURATION // 60}-minute chunks...", file=sys.stderr)
            
            chunks = split_audio_chunks(audio_path)
            tmp_files.extend([path for path, _ in chunks])
            
            results = []
            offsets = []
            chain_prompt = prompt  # user prompt for first chunk
            
            for i, (chunk_path, offset) in enumerate(chunks):
                print(f"Transcribing chunk {i + 1}/{len(chunks)} "
                      f"(offset {offset // 60:.0f}m{offset % 60:.0f}s)...", file=sys.stderr)
                
                text = transcribe_audio(
                    chunk_path,
                    language=language,
                    prompt=chain_prompt,
                    response_format=response_format,
                    temperature=temperature,
                    translate=translate
                )
                results.append(text)
                offsets.append(offset)
                
                # Use tail of previous transcript as prompt for next chunk
                # This helps Whisper maintain context across chunk boundaries
                plain = text
                if response_format in ("srt", "vtt"):
                    # Strip timestamps, keep only text for prompt chaining
                    plain = re.sub(r'\d{2}:\d{2}[\d:.,]+\s*-->\s*\d{2}:\d{2}[\d:.,]+', '', text)
                    plain = re.sub(r'^\d+$', '', plain, flags=re.MULTILINE)
                    plain = re.sub(r'WEBVTT.*', '', plain)
                    plain = ' '.join(plain.split())
                chain_prompt = plain[-200:] if len(plain) > 200 else plain
            
            # Merge results based on output format
            if response_format == "srt":
                merged = merge_srt_chunks(results, offsets)
            elif response_format == "vtt":
                merged = merge_vtt_chunks(results, offsets)
            elif response_format == "verbose_json":
                merged = "\n".join(results)
            else:
                # text or json — join plain text
                merged = " ".join(results)

            fout.write(merged)
            fout.write("\n")

            # Save transcript to file for live recordings
            if is_live_recording and saved_transcript_path:
                with open(saved_transcript_path, "w", encoding="utf-8") as tf:
                    tf.write(merged)
                    tf.write("\n")
                print(f"Transcript saved to: {saved_transcript_path}", file=sys.stderr)

            print(f"Done — transcribed {len(chunks)} chunks.", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        for f in tmp_files:
            if os.path.exists(f):
                os.unlink(f)
        if recorded_tmp and os.path.exists(recorded_tmp):
            os.unlink(recorded_tmp)

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whistper",
        description="Transcribe audio using Whisper via Siemens API.",
        epilog=(
            f"API key is read from: ~/.secret/siemens_api_key\n"
            f"Whisper model: {WHISPER_MODEL}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "input", nargs="?", default="-",
        help="Audio file path, or '-' / omit for live microphone recording. "
             f"Supported formats: {', '.join(sorted(AUDIO_EXTENSIONS))}")
    parser.add_argument(
        "output", nargs="?", default="-",
        help="Output file path, or '-' for stdout (default: stdout)")
    parser.add_argument(
        "-l", "--language", default=None,
        help="ISO-639-1 language code (e.g. en, de, fr, ja). "
             "Omit for auto-detection.")
    parser.add_argument(
        "-p", "--prompt", default=None,
        help="Optional prompt to guide the model (e.g. spelling of names, "
             "technical terms, style).")
    parser.add_argument(
        "-f", "--format", dest="response_format",
        default="json", choices=["json", "text", "srt", "vtt", "verbose_json"],
        help="Output format (default: json). Use 'srt' or 'vtt' for subtitles, "
             "'verbose_json' for timestamps.")
    parser.add_argument(
        "-t", "--temperature", type=float, default=None,
        help="Sampling temperature 0-1. Lower = more deterministic.")
    parser.add_argument(
        "--translate", action="store_true",
        help="Translate audio to English instead of transcribing.")
    parser.add_argument(
        "--loopback", action="store_true",
        help="Record from system audio output (speakers) instead of microphone. "
             "Windows only (WASAPI). Requires: pip install PyAudioWPatch")
    parser.add_argument(
        "-d", "--device", type=int, default=None,
        help="Audio device index to record from. Use --list-devices to see "
             "available devices. Combine with --loopback to capture output "
             "from a specific device.")
    parser.add_argument(
        "--list-devices", action="store_true",
        help="List all available audio devices and exit.")
    return parser

def main():
    ensure_utf8_mode()

    parser = build_parser()
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        sys.exit(0)

    inname = args.input
    outname = args.output

    # Validate input file (skip for live recording)
    if inname != "-":
        if not os.path.isfile(inname):
            print(f"Error: Input file '{inname}' not found", file=sys.stderr)
            parser.print_usage(sys.stderr)
            sys.exit(2)
        if not os.access(inname, os.R_OK):
            print("Cannot read input file", file=sys.stderr)
            sys.exit(2)

    # Validate output file
    if outname != "-" and not (os.access(outname, os.W_OK) or os.access(os.path.dirname(outname) or ".", os.W_OK)):
        print("Cannot write output file", file=sys.stderr)
        sys.exit(2)

    outfile = None
    try:
        outfile = sys.stdout if outname == "-" else open(outname, "w", encoding="utf-8")
        whistper(
            inname, outfile,
            language=args.language,
            prompt=args.prompt,
            response_format=args.response_format,
            temperature=args.temperature,
            translate=args.translate,
            loopback=args.loopback,
            device=args.device
        )
    finally:
        if outfile is not None and outfile != sys.stdout:
            outfile.close()

if __name__ == "__main__":
    main()
