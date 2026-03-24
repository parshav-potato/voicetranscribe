using System.Globalization;
using System.Text.RegularExpressions;

namespace VoiceTranscribe.Core;

/// <summary>
/// Merges chunked SRT and VTT subtitle texts by adjusting timestamps and renumbering entries.
/// </summary>
public static class SubtitleMerger
{
    private static readonly Regex SrtTimestampPattern = new(
        @"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
        RegexOptions.Compiled);

    private static readonly Regex VttTimestampPattern = new(
        @"([\d:.]+)\s*-->\s*([\d:.]+)",
        RegexOptions.Compiled);

    private static readonly Regex VttTimestampLineDetect = new(
        @"^\d{2}:\d{2}",
        RegexOptions.Compiled);

    /// <summary>
    /// Merges multiple SRT subtitle chunks into a single SRT string with adjusted timestamps and renumbered entries.
    /// </summary>
    /// <param name="srtTexts">The raw SRT text from each chunk.</param>
    /// <param name="chunkOffsets">The time offset in seconds for each chunk.</param>
    /// <returns>The merged SRT string.</returns>
    public static string MergeSrt(IReadOnlyList<string> srtTexts, IReadOnlyList<double> chunkOffsets)
    {
        var merged = new List<string>();
        int counter = 1;

        for (int i = 0; i < srtTexts.Count; i++)
        {
            string srtText = srtTexts[i];
            double offset = chunkOffsets[i];

            string[] blocks = Regex.Split(srtText.Trim(), @"\n\n+");
            foreach (string block in blocks)
            {
                string[] lines = block.Trim().Split('\n');
                if (lines.Length < 2)
                    continue;

                var match = SrtTimestampPattern.Match(lines[1]);
                if (!match.Success)
                    continue;

                string start = OffsetTimestamp(match.Groups[1].Value, offset, ',');
                string end = OffsetTimestamp(match.Groups[2].Value, offset, ',');
                string text = string.Join("\n", lines.Skip(2));
                merged.Add($"{counter}\n{start} --> {end}\n{text}");
                counter++;
            }
        }

        return string.Join("\n\n", merged) + "\n";
    }

    /// <summary>
    /// Merges multiple VTT subtitle chunks into a single VTT string with adjusted timestamps.
    /// </summary>
    /// <param name="vttTexts">The raw VTT text from each chunk.</param>
    /// <param name="chunkOffsets">The time offset in seconds for each chunk.</param>
    /// <returns>The merged VTT string.</returns>
    public static string MergeVtt(IReadOnlyList<string> vttTexts, IReadOnlyList<double> chunkOffsets)
    {
        var mergedCues = new List<string>();

        for (int i = 0; i < vttTexts.Count; i++)
        {
            string vttText = vttTexts[i];
            double offset = chunkOffsets[i];

            string[] lines = vttText.Trim().Split('\n');
            int lineIdx = 0;

            // Skip WEBVTT header and metadata
            while (lineIdx < lines.Length && !VttTimestampLineDetect.IsMatch(lines[lineIdx]))
                lineIdx++;

            while (lineIdx < lines.Length)
            {
                var match = VttTimestampPattern.Match(lines[lineIdx]);
                if (match.Success)
                {
                    string start = OffsetTimestamp(match.Groups[1].Value, offset, '.');
                    string end = OffsetTimestamp(match.Groups[2].Value, offset, '.');
                    lineIdx++;

                    var textLines = new List<string>();
                    while (lineIdx < lines.Length && !string.IsNullOrWhiteSpace(lines[lineIdx]))
                    {
                        textLines.Add(lines[lineIdx]);
                        lineIdx++;
                    }

                    mergedCues.Add($"{start} --> {end}\n{string.Join("\n", textLines)}");
                }

                lineIdx++;
            }
        }

        return "WEBVTT\n\n" + string.Join("\n\n", mergedCues) + "\n";
    }

    /// <summary>
    /// Offsets a subtitle timestamp by the given number of seconds.
    /// Handles both SRT format (<c>HH:MM:SS,mmm</c>) and VTT format (<c>HH:MM:SS.mmm</c>).
    /// </summary>
    /// <param name="timeStr">The timestamp string to offset.</param>
    /// <param name="offsetSeconds">Seconds to add (can be negative, clamped to zero).</param>
    /// <param name="separator">The millisecond separator: <c>','</c> for SRT, <c>'.'</c> for VTT.</param>
    /// <returns>The offset timestamp string.</returns>
    public static string OffsetTimestamp(string timeStr, double offsetSeconds, char separator = ',')
    {
        string normalized = timeStr.Trim().Replace(',', '.');
        string[] parts = normalized.Split(':');

        int h = int.Parse(parts[0], CultureInfo.InvariantCulture);
        int m = int.Parse(parts[1], CultureInfo.InvariantCulture);
        double s = double.Parse(parts[2], CultureInfo.InvariantCulture);

        double total = h * 3600 + m * 60 + s + offsetSeconds;
        if (total < 0)
            total = 0;

        int newH = (int)(total / 3600);
        int newM = (int)(total % 3600 / 60);
        double newS = total % 60;

        string result = string.Create(CultureInfo.InvariantCulture, $"{newH:D2}:{newM:D2}:{newS:06.3f}");
        if (separator == ',')
            result = result.Replace('.', ',');

        return result;
    }
}
