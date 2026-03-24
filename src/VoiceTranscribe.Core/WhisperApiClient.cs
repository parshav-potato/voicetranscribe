using System.Net;
using System.Text.Json;
using VoiceTranscribe.Core.Models;

namespace VoiceTranscribe.Core;

/// <summary>
/// Sends audio files to the Whisper API for transcription or translation.
/// Includes retry logic with exponential backoff for transient server errors.
/// </summary>
public sealed class WhisperApiClient : IDisposable
{
    private const int MaxRetries = 3;
    private static readonly int[] BackoffSeconds = [1, 3, 9];

    private readonly HttpClient _httpClient;

    /// <summary>
    /// Creates a new client with the given API key.
    /// </summary>
    /// <param name="apiKey">The Siemens LLM gateway API key.</param>
    public WhisperApiClient(string apiKey)
    {
        _httpClient = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(120)
        };
        _httpClient.DefaultRequestHeaders.Add("Authorization", $"Bearer {apiKey}");
        _httpClient.DefaultRequestHeaders.Add("Editor-Version", "vscode/1.85.0");
        _httpClient.DefaultRequestHeaders.Add("Editor-Plugin-Version", "GitHubCopilotChat/0.11.1");
    }

    /// <summary>
    /// Transcribes or translates a single audio file via the Whisper API.
    /// The file must already be in a format the API accepts (use <see cref="AudioConverter"/> first).
    /// </summary>
    /// <param name="audioFilePath">Path to the audio file to send.</param>
    /// <param name="options">Transcription options (format, language, etc.).</param>
    /// <param name="ct">Cancellation token.</param>
    /// <returns>The transcription result as a string (format depends on <paramref name="options"/>).</returns>
    /// <exception cref="TranscriptionApiException">The API returned a non-success status code after all retries.</exception>
    public async Task<string> TranscribeAsync(
        string audioFilePath,
        TranscriptionOptions options,
        CancellationToken ct = default)
    {
        string endpoint = options.Translate ? "translations" : "transcriptions";
        string url = $"{Constants.RootUrl}/audio/{endpoint}";

        for (int attempt = 0; attempt < MaxRetries; attempt++)
        {
            ct.ThrowIfCancellationRequested();

            using var content = BuildMultipartContent(audioFilePath, options);

            HttpResponseMessage response;
            try
            {
                response = await _httpClient.PostAsync(url, content, ct).ConfigureAwait(false);
            }
            catch (HttpRequestException) when (attempt < MaxRetries - 1)
            {
                await Task.Delay(TimeSpan.FromSeconds(BackoffSeconds[attempt]), ct).ConfigureAwait(false);
                continue;
            }

            if (response.IsSuccessStatusCode)
            {
                return await ParseResponseAsync(response, options.Format, ct).ConfigureAwait(false);
            }

            // Do NOT retry 4xx errors
            int statusCode = (int)response.StatusCode;
            if (statusCode >= 400 && statusCode < 500)
            {
                string body = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
                throw new TranscriptionApiException(response.StatusCode, body);
            }

            // Retry on 5xx
            if (attempt < MaxRetries - 1)
            {
                await Task.Delay(TimeSpan.FromSeconds(BackoffSeconds[attempt]), ct).ConfigureAwait(false);
                continue;
            }

            // Final attempt failed
            string errorBody = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            throw new TranscriptionApiException(response.StatusCode, errorBody);
        }

        // Should not be reachable, but satisfies the compiler
        throw new VoiceTranscribeException("Transcription failed after all retry attempts.");
    }

    /// <summary>Disposes the underlying <see cref="HttpClient"/>.</summary>
    public void Dispose() => _httpClient.Dispose();

    private static MultipartFormDataContent BuildMultipartContent(string audioFilePath, TranscriptionOptions options)
    {
        var form = new MultipartFormDataContent();
        var fileStream = new FileStream(audioFilePath, FileMode.Open, FileAccess.Read);
        var fileContent = new StreamContent(fileStream);
        form.Add(fileContent, "file", Path.GetFileName(audioFilePath));
        form.Add(new StringContent(Constants.WhisperModel), "model");
        form.Add(new StringContent(options.FormatString), "response_format");

        if (options.Language is not null)
            form.Add(new StringContent(options.Language), "language");

        if (options.Prompt is not null)
            form.Add(new StringContent(options.Prompt), "prompt");

        if (options.Temperature is not null)
            form.Add(new StringContent(
                options.Temperature.Value.ToString(System.Globalization.CultureInfo.InvariantCulture)), "temperature");

        return form;
    }

    private static async Task<string> ParseResponseAsync(
        HttpResponseMessage response, ResponseFormat format, CancellationToken ct)
    {
        string text = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);

        switch (format)
        {
            case ResponseFormat.Text:
                // The API sometimes returns JSON even for text format
                string trimmed = text.Trim();
                if (trimmed.StartsWith('{'))
                {
                    try
                    {
                        using var doc = JsonDocument.Parse(trimmed);
                        if (doc.RootElement.TryGetProperty("text", out var textProp))
                            return textProp.GetString() ?? trimmed;
                    }
                    catch (JsonException)
                    {
                        // Not valid JSON, return as-is
                    }
                }
                return text;

            case ResponseFormat.Srt:
            case ResponseFormat.Vtt:
                return text;

            case ResponseFormat.VerboseJson:
                // Pretty-print the JSON
                try
                {
                    using var doc = JsonDocument.Parse(text);
                    return JsonSerializer.Serialize(doc.RootElement, new JsonSerializerOptions
                    {
                        WriteIndented = true,
                        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
                    });
                }
                catch (JsonException)
                {
                    return text;
                }

            case ResponseFormat.Json:
            default:
                try
                {
                    using var doc = JsonDocument.Parse(text);
                    if (doc.RootElement.TryGetProperty("error", out var errorProp))
                    {
                        string? message = errorProp.ValueKind == JsonValueKind.Object
                            ? (errorProp.TryGetProperty("message", out var msgProp) ? msgProp.GetString() : null)
                            : errorProp.GetString();
                        throw new VoiceTranscribeException($"API error: {message ?? "Unknown error"}");
                    }

                    if (doc.RootElement.TryGetProperty("text", out var textElement))
                        return textElement.GetString() ?? string.Empty;

                    return text;
                }
                catch (JsonException)
                {
                    return text;
                }
        }
    }
}
