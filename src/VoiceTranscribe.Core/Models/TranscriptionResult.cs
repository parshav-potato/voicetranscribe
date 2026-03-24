namespace VoiceTranscribe.Core.Models;

/// <summary>
/// The result of a transcription or translation operation.
/// </summary>
public sealed record TranscriptionResult
{
    /// <summary>The transcribed or translated text.</summary>
    public required string Text { get; init; }

    /// <summary>The response format that was used.</summary>
    public required ResponseFormat Format { get; init; }

    /// <summary>The number of chunks the file was split into (1 if no splitting was needed).</summary>
    public required int ChunkCount { get; init; }
}
