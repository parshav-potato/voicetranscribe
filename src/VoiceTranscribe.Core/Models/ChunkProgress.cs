namespace VoiceTranscribe.Core.Models;

/// <summary>
/// Reports progress during chunked transcription.
/// </summary>
public sealed record ChunkProgress
{
    /// <summary>The 1-based index of the current chunk.</summary>
    public required int CurrentChunk { get; init; }

    /// <summary>The total number of chunks.</summary>
    public required int TotalChunks { get; init; }

    /// <summary>The offset in seconds from the start of the original audio.</summary>
    public required double OffsetSeconds { get; init; }
}
