namespace VoiceTranscribe.Core;

/// <summary>
/// Reads the Siemens API key from the user's home directory.
/// </summary>
public static class ApiKeyProvider
{
    /// <summary>
    /// Reads the API key from <c>~/.secret/siemens_api_key</c>.
    /// </summary>
    /// <returns>The trimmed API key string.</returns>
    /// <exception cref="ApiKeyNotFoundException">Thrown when the key file does not exist.</exception>
    public static string GetApiKey()
    {
        string path = Constants.ApiKeyFilePath;
        if (!File.Exists(path))
            throw new ApiKeyNotFoundException(path);

        return File.ReadAllText(path).Trim();
    }

    /// <summary>
    /// Asynchronously reads the API key from <c>~/.secret/siemens_api_key</c>.
    /// </summary>
    /// <returns>The trimmed API key string.</returns>
    /// <exception cref="ApiKeyNotFoundException">Thrown when the key file does not exist.</exception>
    public static async Task<string> GetApiKeyAsync(CancellationToken ct = default)
    {
        string path = Constants.ApiKeyFilePath;
        if (!File.Exists(path))
            throw new ApiKeyNotFoundException(path);

        string content = await File.ReadAllTextAsync(path, ct).ConfigureAwait(false);
        return content.Trim();
    }
}
