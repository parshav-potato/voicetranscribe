using System.IO;
using System.Text.Json;
using VoiceTranscribe.Gui.Models;

namespace VoiceTranscribe.Gui.Services;

public sealed class AppSettings
{
    public string? Language { get; set; }
    public string? LanguageName { get; set; }
    public bool Translate { get; set; }
    public bool AutoPaste { get; set; } = true;
    public bool TransparentIdle { get; set; } = true;
    public double? WindowX { get; set; }
    public double? WindowY { get; set; }
    public string? Prompt { get; set; }
    public List<HistoryEntry> History { get; set; } = [];
}

public sealed class SettingsService
{
    private const int MaxHistory = 20;

    private static readonly string SettingsDir = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        ".config", "voicetranscribe");

    private static readonly string SettingsFile = Path.Combine(SettingsDir, "settings.json");

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    public AppSettings Settings { get; private set; } = new();

    public void Load()
    {
        try
        {
            if (!File.Exists(SettingsFile))
                return;

            var json = File.ReadAllText(SettingsFile);
            var loaded = JsonSerializer.Deserialize<AppSettings>(json, JsonOptions);
            if (loaded is not null)
                Settings = loaded;
        }
        catch
        {
            Settings = new AppSettings();
        }
    }

    public void Save()
    {
        try
        {
            Directory.CreateDirectory(SettingsDir);
            var json = JsonSerializer.Serialize(Settings, JsonOptions);
            File.WriteAllText(SettingsFile, json);
        }
        catch
        {
            // Settings are best-effort; don't crash on write failures.
        }
    }

    public void AddHistory(HistoryEntry entry)
    {
        Settings.History.Add(entry);

        while (Settings.History.Count > MaxHistory)
            Settings.History.RemoveAt(0);

        Save();
    }
}
