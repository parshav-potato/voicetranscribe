using System.Net;

namespace VoiceTranscribe.Core;

/// <summary>
/// Base exception for all VoiceTranscribe errors.
/// </summary>
public class VoiceTranscribeException : Exception
{
    /// <summary>Initializes a new instance with the specified message.</summary>
    public VoiceTranscribeException(string message) : base(message) { }

    /// <summary>Initializes a new instance with the specified message and inner exception.</summary>
    public VoiceTranscribeException(string message, Exception innerException) : base(message, innerException) { }
}

/// <summary>
/// Thrown when the API key file cannot be found.
/// </summary>
public class ApiKeyNotFoundException : VoiceTranscribeException
{
    /// <summary>The path where the key file was expected.</summary>
    public string KeyFilePath { get; }

    /// <summary>Initializes a new instance for the given key file path.</summary>
    public ApiKeyNotFoundException(string keyFilePath)
        : base($"API key file not found: {keyFilePath}\nPlease create this file with your Siemens API key.")
    {
        KeyFilePath = keyFilePath;
    }
}

/// <summary>
/// Thrown when ffmpeg or ffprobe cannot be found on PATH.
/// </summary>
public class FfmpegNotFoundException : VoiceTranscribeException
{
    /// <summary>Initializes a new instance.</summary>
    public FfmpegNotFoundException()
        : base("ffmpeg not found. Please install ffmpeg and ensure it is on your PATH.") { }
}

/// <summary>
/// Thrown when audio conversion via ffmpeg fails.
/// </summary>
public class AudioConversionException : VoiceTranscribeException
{
    /// <summary>Initializes a new instance with ffmpeg's error output.</summary>
    public AudioConversionException(string stderrOutput)
        : base($"ffmpeg conversion failed: {stderrOutput}") { }
}

/// <summary>
/// Thrown when the Whisper transcription API returns an error.
/// </summary>
public class TranscriptionApiException : VoiceTranscribeException
{
    /// <summary>The HTTP status code returned by the API.</summary>
    public HttpStatusCode StatusCode { get; }

    /// <summary>Initializes a new instance with the given status code and response body.</summary>
    public TranscriptionApiException(HttpStatusCode statusCode, string responseBody)
        : base($"Transcription API error {(int)statusCode}: {responseBody}")
    {
        StatusCode = statusCode;
    }
}

/// <summary>
/// Thrown when an audio file has an unsupported extension.
/// </summary>
public class UnsupportedAudioFormatException : VoiceTranscribeException
{
    /// <summary>The unsupported file extension.</summary>
    public string Extension { get; }

    /// <summary>Initializes a new instance for the given extension.</summary>
    public UnsupportedAudioFormatException(string extension)
        : base($"Unsupported audio format: {extension}. Supported formats: {string.Join(", ", Constants.AudioExtensions)}")
    {
        Extension = extension;
    }
}
