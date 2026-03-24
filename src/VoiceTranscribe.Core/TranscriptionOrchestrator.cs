using System.Text.RegularExpressions;
using VoiceTranscribe.Core.Models;

namespace VoiceTranscribe.Core;

/// <summary>
/// Coordinates the full transcription pipeline: validation, conversion, chunking, API calls, and merging.
/// </summary>
public sealed class TranscriptionOrchestrator : IDisposable
{
    private readonly WhisperApiClient _client;
    private readonly bool _ownsClient;

    /// <summary>
    /// Creates an orchestrator using the given API key.
    /// </summary>
    /// <param name="apiKey">The Siemens LLM gateway API key.</param>
    public TranscriptionOrchestrator(string apiKey)
    {
        _client = new WhisperApiClient(apiKey);
        _ownsClient = true;
    }

    /// <summary>
    /// Creates an orchestrator wrapping an existing <see cref="WhisperApiClient"/>.
    /// The caller retains ownership of the client.
    /// </summary>
    /// <param name="client">An existing Whisper API client.</param>
    public TranscriptionOrchestrator(WhisperApiClient client)
    {
        _client = client;
        _ownsClient = false;
    }

    /// <summary>
    /// Transcribes (or translates) an audio file through the full pipeline.
    /// </summary>
    /// <param name="filePath">Path to the audio file.</param>
    /// <param name="options">Transcription options.</param>
    /// <param name="onProgress">Optional callback for chunk progress reporting.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>The transcription result.</returns>
    public async Task<TranscriptionResult> TranscribeFileAsync(
        string filePath,
        TranscriptionOptions options,
        Action<ChunkProgress>? onProgress = null,
        CancellationToken ct = default)
    {
        // 1. Validate format
        AudioConverter.ValidateAudioFormat(filePath);

        string audioPath = filePath;
        TempFile? convertedFile = null;

        try
        {
            // 2. Convert to MP3 if needed (single conversion path)
            if (AudioConverter.NeedsConversion(filePath))
            {
                convertedFile = await AudioConverter.ConvertToMp3Async(filePath, ct).ConfigureAwait(false);
                audioPath = convertedFile.Path;
            }

            // 3. Check file size
            long fileSize = new FileInfo(audioPath).Length;

            if (fileSize <= Constants.MaxUploadBytes)
            {
                // 4. Small enough -- transcribe directly
                string text = await _client.TranscribeAsync(audioPath, options, ct).ConfigureAwait(false);
                return new TranscriptionResult
                {
                    Text = text,
                    Format = options.Format,
                    ChunkCount = 1,
                };
            }

            // 5. Too large -- split, transcribe chunks, merge
            return await TranscribeChunkedAsync(audioPath, options, onProgress, ct).ConfigureAwait(false);
        }
        finally
        {
            convertedFile?.Dispose();
        }
    }

    /// <summary>Disposes the underlying <see cref="WhisperApiClient"/> if owned.</summary>
    public void Dispose()
    {
        if (_ownsClient)
            _client.Dispose();
    }

    private async Task<TranscriptionResult> TranscribeChunkedAsync(
        string audioPath,
        TranscriptionOptions options,
        Action<ChunkProgress>? onProgress,
        CancellationToken ct)
    {
        List<AudioChunk> chunks = await AudioChunker.SplitAsync(audioPath, ct: ct).ConfigureAwait(false);

        try
        {
            var results = new List<string>();
            var offsets = new List<double>();
            string? chainPrompt = options.Prompt;

            for (int i = 0; i < chunks.Count; i++)
            {
                ct.ThrowIfCancellationRequested();

                onProgress?.Invoke(new ChunkProgress
                {
                    CurrentChunk = i + 1,
                    TotalChunks = chunks.Count,
                    OffsetSeconds = chunks[i].OffsetSeconds,
                });

                var chunkOptions = options with { Prompt = chainPrompt };
                string text = await _client.TranscribeAsync(chunks[i].File.Path, chunkOptions, ct)
                    .ConfigureAwait(false);

                results.Add(text);
                offsets.Add(chunks[i].OffsetSeconds);

                // Use tail of previous transcript as prompt for next chunk
                chainPrompt = ExtractPromptTail(text, options.Format);
            }

            string merged = MergeResults(results, offsets, options.Format);

            return new TranscriptionResult
            {
                Text = merged,
                Format = options.Format,
                ChunkCount = chunks.Count,
            };
        }
        finally
        {
            foreach (var chunk in chunks)
                chunk.Dispose();
        }
    }

    private static string ExtractPromptTail(string text, ResponseFormat format)
    {
        string plain = text;
        if (format is ResponseFormat.Srt or ResponseFormat.Vtt)
        {
            // Strip timestamps, keep only text for prompt chaining
            plain = Regex.Replace(text, @"\d{2}:\d{2}[\d:.,]+\s*-->\s*\d{2}:\d{2}[\d:.,]+", "");
            plain = Regex.Replace(plain, @"^\d+$", "", RegexOptions.Multiline);
            plain = Regex.Replace(plain, @"WEBVTT.*", "");
            plain = string.Join(' ', plain.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        }

        return plain.Length > 200 ? plain[^200..] : plain;
    }

    private static string MergeResults(List<string> results, List<double> offsets, ResponseFormat format)
    {
        return format switch
        {
            ResponseFormat.Srt => SubtitleMerger.MergeSrt(results, offsets),
            ResponseFormat.Vtt => SubtitleMerger.MergeVtt(results, offsets),
            ResponseFormat.VerboseJson => string.Join("\n", results),
            _ => string.Join(" ", results),
        };
    }
}
