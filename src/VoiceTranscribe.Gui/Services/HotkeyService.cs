using System.Windows;
using System.Windows.Input;
using NHotkey;
using NHotkey.Wpf;

namespace VoiceTranscribe.Gui.Services;

public sealed class HotkeyService : IDisposable
{
    private const string HotkeyName = "ToggleRecord";

    public const string HotkeyDescription = "Ctrl+Shift+R";

    /// <summary>
    /// Fires on the UI thread when the global hotkey is pressed.
    /// </summary>
    public event Action? HotkeyPressed;

    public void Register(Window window)
    {
        try
        {
            HotkeyManager.Current.AddOrReplace(
                HotkeyName,
                Key.R,
                ModifierKeys.Control | ModifierKeys.Shift,
                OnHotkeyPressed);
        }
        catch { }
    }

    private void OnHotkeyPressed(object? sender, HotkeyEventArgs e)
    {
        HotkeyPressed?.Invoke();
        e.Handled = true;
    }

    public void Dispose()
    {
        try
        {
            HotkeyManager.Current.Remove(HotkeyName);
        }
        catch { }
    }
}
