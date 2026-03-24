using System.Globalization;

namespace VoiceTranscribe.Core;

/// <summary>
/// Splits large audio files into overlapping chunks using ffmpeg.
/// </summary>
public static class AudioChunker
{
    /// <summary>
    /// Splits an audio file into overlapping MP3 chunks.
    /// Each chunk includes <paramref name="overlapSeconds"/> seconds from the end of the
    /// previous chunk to avoid cutting words at boundaries.
    /// </summary>
    /// <param name="audioPath">Path to the source audio file.</param>
    /// <param name="chunkDurationSeconds">Duration of each chunk in seconds.</param>
    /// <param name="overlapSeconds">Overlap in seconds between consecutive chunks.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>A list of <see cref="AudioChunk"/> instances that must be disposed by the caller.</returns>
    /// <exception cref="VoiceTranscribeException">Thrown when audio duration cannot be determined.</exception>
    /// <exception cref="FfmpegNotFoundException">ffmpeg is not installed or not on PATH.</exception>
    /// <exception cref="AudioConversionException">ffmpeg exited with a non-zero code.</exception>
    public static async Task<List<AudioChunk>> SplitAsync(
        string audioPath,
        int chunkDurationSeconds = Constants.ChunkDurationSeconds,
        int overlapSeconds = Constants.ChunkOverlapSeconds,
        CancellationToken ct = default)
    {
        double duration = await AudioConverter.GetDurationAsync(audioPath, ct).ConfigureAwait(false);
        if (duration <= 0)
            throw new VoiceTranscribeException("Could not determine audio duration. Is ffprobe installed?");

        var chunks = new List<AudioChunk>();
        double start = 0;
        int step = chunkDurationSeconds - overlapSeconds;

        try
        {
            while (start < duration)
            {
                ct.ThrowIfCancellationRequested();

                double actualDuration = Math.Min(chunkDurationSeconds, duration - start);
                string outputPath = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}.mp3");

                string startStr = start.ToString(CultureInfo.InvariantCulture);
                string durStr = actualDuration.ToString(CultureInfo.InvariantCulture);
                string args = $"-y -i \"{audioPath}\" -ss {startStr} -t {durStr} -ar 16000 -ac 1 -b:a 64k \"{outputPath}\"";

                var (exitCode, _, stderr) = await AudioConverter.RunProcessAsync("ffmpeg", args, ct)
                    .ConfigureAwait(false);

                if (exitCode != 0)
                {
                    TryDelete(outputPath);
                    throw new AudioConversionException($"ffmpeg chunk split failed: {stderr}");
                }

                chunks.Add(new AudioChunk(new TempFile(outputPath), start));
                start += step;

                if (start >= duration)
                    break;
            }

            return chunks;
        }
        catch
        {
            foreach (var chunk in chunks)
                chunk.Dispose();
            chunks.Clear();
            throw;
        }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }
}

/// <summary>
/// Represents one chunk of a split audio file. Owns the underlying <see cref="TempFile"/>.
/// </summary>
public sealed class AudioChunk : IDisposable
{
    /// <summary>The temporary file containing this chunk's audio data.</summary>
    public TempFile File { get; }

    /// <summary>The offset in seconds from the start of the original audio.</summary>
    public double OffsetSeconds { get; }

    /// <summary>Creates a new chunk wrapping the given temp file and offset.</summary>
    public AudioChunk(TempFile file, double offsetSeconds)
    {
        File = file;
        OffsetSeconds = offsetSeconds;
    }

    /// <summary>Disposes the underlying temporary file.</summary>
    public void Dispose() => File.Dispose();
}
