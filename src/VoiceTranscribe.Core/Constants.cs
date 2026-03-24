namespace VoiceTranscribe.Core;

/// <summary>
/// Shared constants for the VoiceTranscribe application.
/// </summary>
public static class Constants
{
    /// <summary>
    /// Supported audio file extensions for the Whisper API.
    /// </summary>
    public static readonly IReadOnlySet<string> AudioExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".flac", ".ogg", ".opus"
    };

    /// <summary>
    /// Audio formats that require conversion to MP3 before uploading.
    /// </summary>
    public static readonly IReadOnlySet<string> NeedsConversion = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        ".m4a", ".mp4", ".ogg", ".opus", ".webm", ".flac", ".mpeg", ".mpga"
    };

    /// <summary>
    /// The Whisper model identifier used for transcription.
    /// </summary>
    public const string WhisperModel = "whisper-large-v3-turbo";

    /// <summary>
    /// Base URL for the Siemens LLM gateway API.
    /// </summary>
    public const string RootUrl = "https://api.siemens.com/llm/v1";

    /// <summary>
    /// Conservative upload size limit in bytes (24 MB; API max is 25 MB).
    /// </summary>
    public const long MaxUploadBytes = 24 * 1024 * 1024;

    /// <summary>
    /// Duration of each audio chunk in seconds (10 minutes).
    /// </summary>
    public const int ChunkDurationSeconds = 600;

    /// <summary>
    /// Overlap between consecutive chunks in seconds, to avoid splitting mid-word.
    /// </summary>
    public const int ChunkOverlapSeconds = 5;

    /// <summary>
    /// Default directory for saving recordings and transcriptions.
    /// </summary>
    public static readonly string SaveDirectory = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
        "Sound Recordings");

    /// <summary>
    /// Path to the API key file.
    /// </summary>
    public static readonly string ApiKeyFilePath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".secret",
        "siemens_api_key");

    /// <summary>
    /// Supported languages for transcription, as (display name, ISO-639-1 code) pairs.
    /// A null code means auto-detect.
    /// </summary>
    public static readonly IReadOnlyList<(string Name, string? Code)> Languages = new List<(string, string?)>
    {
        ("Auto-detect", null),
        ("English", "en"),
        ("German", "de"),
        ("French", "fr"),
        ("Spanish", "es"),
        ("Japanese", "ja"),
        ("Chinese", "zh"),
        ("Dutch", "nl"),
        ("Italian", "it"),
        ("Portuguese", "pt"),
        ("Russian", "ru"),
        ("Korean", "ko"),
    };
}
