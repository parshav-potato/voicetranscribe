using System.Windows;
using System.Windows.Controls;
using H.NotifyIcon;

namespace VoiceTranscribe.Gui.Services;

public sealed class TrayIconService : IDisposable
{
    private TaskbarIcon? _taskbarIcon;

    public event Action? ToggleWindowRequested;
    public event Action? StartRecordingRequested;
    public event Action? QuitRequested;

    public void Initialize()
    {
        _taskbarIcon = new TaskbarIcon();

        var iconUri = GetIconUri();
        if (iconUri is not null)
        {
            _taskbarIcon.IconSource = new System.Windows.Media.Imaging.BitmapImage(iconUri);
        }

        _taskbarIcon.ToolTipText = "Voice Transcribe";

        var contextMenu = new ContextMenu();

        var showHideItem = new MenuItem { Header = "Show / Hide" };
        showHideItem.Click += (_, _) => ToggleWindowRequested?.Invoke();
        showHideItem.FontWeight = FontWeights.Bold;
        contextMenu.Items.Add(showHideItem);

        var recordItem = new MenuItem { Header = "Start Recording" };
        recordItem.Click += (_, _) => StartRecordingRequested?.Invoke();
        contextMenu.Items.Add(recordItem);

        contextMenu.Items.Add(new Separator());

        var quitItem = new MenuItem { Header = "Quit" };
        quitItem.Click += (_, _) => QuitRequested?.Invoke();
        contextMenu.Items.Add(quitItem);

        _taskbarIcon.ContextMenu = contextMenu;

        _taskbarIcon.TrayMouseDoubleClick += (_, _) => ToggleWindowRequested?.Invoke();
    }

    public void ShowNotification(string title, string message)
    {
        _taskbarIcon?.ShowNotification(title, message);
    }

    private static Uri? GetIconUri()
    {
        try
        {
            var asmName = System.Reflection.Assembly.GetEntryAssembly()?.GetName().Name;
            if (asmName is not null)
                return new Uri($"pack://application:,,,/{asmName};component/Resources/microphone.ico", UriKind.Absolute);
        }
        catch
        {
            // Resource not found -- tray icon will have no image.
        }

        return null;
    }

    public void Dispose()
    {
        _taskbarIcon?.Dispose();
        _taskbarIcon = null;
    }
}
