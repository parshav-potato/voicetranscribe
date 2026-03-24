using System.ComponentModel;
using System.Diagnostics;

namespace VoiceTranscribe.Core;

/// <summary>
/// Wraps ffmpeg/ffprobe for audio conversion and inspection.
/// </summary>
public static class AudioConverter
{
    /// <summary>
    /// Converts an audio file to MP3 (16 kHz, mono, 64 kbps) using ffmpeg.
    /// </summary>
    /// <param name="inputPath">Path to the source audio file.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>A <see cref="TempFile"/> owning the output MP3.</returns>
    /// <exception cref="FfmpegNotFoundException">ffmpeg is not installed or not on PATH.</exception>
    /// <exception cref="AudioConversionException">ffmpeg exited with a non-zero code.</exception>
    public static async Task<TempFile> ConvertToMp3Async(string inputPath, CancellationToken ct = default)
    {
        string outputPath = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}.mp3");
        var tempFile = new TempFile(outputPath);
        bool success = false;
        try
        {
            var (exitCode, _, stderr) = await RunProcessAsync(
                "ffmpeg",
                $"-y -i \"{inputPath}\" -ar 16000 -ac 1 -b:a 64k \"{outputPath}\"",
                ct).ConfigureAwait(false);

            if (exitCode != 0)
                throw new AudioConversionException(stderr);

            success = true;
            return tempFile;
        }
        finally
        {
            if (!success)
                tempFile.Dispose();
        }
    }

    /// <summary>
    /// Gets the duration of an audio file in seconds using ffprobe.
    /// </summary>
    /// <param name="path">Path to the audio file.</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>Duration in seconds, or 0.0 if it cannot be determined.</returns>
    public static async Task<double> GetDurationAsync(string path, CancellationToken ct = default)
    {
        try
        {
            var (exitCode, stdout, _) = await RunProcessAsync(
                "ffprobe",
                $"-v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{path}\"",
                ct).ConfigureAwait(false);

            if (exitCode == 0 && double.TryParse(stdout.Trim(), System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture, out double duration))
            {
                return duration;
            }
        }
        catch
        {
            // Swallow — return 0.0 on any failure
        }

        return 0.0;
    }

    /// <summary>
    /// Validates that the file has a supported audio extension.
    /// </summary>
    /// <param name="filePath">Path to the file to validate.</param>
    /// <exception cref="UnsupportedAudioFormatException">The extension is not in <see cref="Constants.AudioExtensions"/>.</exception>
    public static void ValidateAudioFormat(string filePath)
    {
        string ext = Path.GetExtension(filePath);
        if (string.IsNullOrEmpty(ext) || !Constants.AudioExtensions.Contains(ext))
            throw new UnsupportedAudioFormatException(ext ?? string.Empty);
    }

    /// <summary>
    /// Checks whether the file's format requires conversion to MP3 before upload.
    /// </summary>
    /// <param name="filePath">Path to the audio file.</param>
    /// <returns><c>true</c> if the extension is in <see cref="Constants.NeedsConversion"/>.</returns>
    public static bool NeedsConversion(string filePath)
    {
        string ext = Path.GetExtension(filePath);
        return !string.IsNullOrEmpty(ext) && Constants.NeedsConversion.Contains(ext);
    }

    internal static async Task<(int ExitCode, string Stdout, string Stderr)> RunProcessAsync(
        string fileName, string arguments, CancellationToken ct)
    {
        var psi = new ProcessStartInfo
        {
            FileName = fileName,
            Arguments = arguments,
            CreateNoWindow = true,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };

        Process process;
        try
        {
            process = Process.Start(psi)
                ?? throw new FfmpegNotFoundException();
        }
        catch (Win32Exception)
        {
            throw new FfmpegNotFoundException();
        }

        using (process)
        {
            var stdoutTask = process.StandardOutput.ReadToEndAsync(ct);
            var stderrTask = process.StandardError.ReadToEndAsync(ct);

            await process.WaitForExitAsync(ct).ConfigureAwait(false);

            string stdout = await stdoutTask.ConfigureAwait(false);
            string stderr = await stderrTask.ConfigureAwait(false);

            return (process.ExitCode, stdout, stderr);
        }
    }
}

/// <summary>
/// Owns a temporary file and deletes it on disposal. Prevents temp file leaks.
/// </summary>
public sealed class TempFile : IDisposable
{
    /// <summary>The absolute path to the temporary file.</summary>
    public string Path { get; }

    /// <summary>Creates a new <see cref="TempFile"/> for the given path.</summary>
    public TempFile(string path) => Path = path;

    /// <summary>Deletes the temporary file if it exists.</summary>
    public void Dispose()
    {
        try
        {
            if (File.Exists(Path))
                File.Delete(Path);
        }
        catch
        {
            // Best-effort cleanup
        }
    }
}
