namespace VoiceTranscribe.Core.Models;

/// <summary>
/// The response format requested from the Whisper API.
/// </summary>
public enum ResponseFormat
{
    /// <summary>JSON object with a "text" field.</summary>
    Json,
    /// <summary>Plain text transcription.</summary>
    Text,
    /// <summary>SubRip subtitle format.</summary>
    Srt,
    /// <summary>WebVTT subtitle format.</summary>
    Vtt,
    /// <summary>Verbose JSON with timestamps and metadata.</summary>
    VerboseJson,
}

/// <summary>
/// Options controlling a single transcription or translation request.
/// </summary>
public sealed record TranscriptionOptions
{
    /// <summary>ISO-639-1 language code (e.g. "en", "de"). Null for auto-detect.</summary>
    public string? Language { get; init; }

    /// <summary>Optional prompt to guide the model's style or provide context.</summary>
    public string? Prompt { get; init; }

    /// <summary>The desired response format from the API.</summary>
    public ResponseFormat Format { get; init; } = ResponseFormat.Json;

    /// <summary>Sampling temperature (0-1). Null for the API default.</summary>
    public float? Temperature { get; init; }

    /// <summary>If true, translate to English instead of transcribing in the original language.</summary>
    public bool Translate { get; init; }

    /// <summary>
    /// Returns the API string representation of the <see cref="Format"/>.
    /// </summary>
    public string FormatString => Format switch
    {
        ResponseFormat.Json => "json",
        ResponseFormat.Text => "text",
        ResponseFormat.Srt => "srt",
        ResponseFormat.Vtt => "vtt",
        ResponseFormat.VerboseJson => "verbose_json",
        _ => "json",
    };
}
