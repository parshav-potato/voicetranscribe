using System.Windows;
using VoiceTranscribe.Core;

namespace VoiceTranscribe.Gui;

/// <summary>
/// Application entry point. Validates the API key on startup.
/// </summary>
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        try
        {
            ApiKeyProvider.GetApiKey();
        }
        catch (ApiKeyNotFoundException ex)
        {
            MessageBox.Show(ex.Message, "API Key Error", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }
}
