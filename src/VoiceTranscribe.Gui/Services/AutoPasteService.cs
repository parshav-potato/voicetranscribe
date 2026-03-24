using System.Runtime.InteropServices;

namespace VoiceTranscribe.Gui.Services;

public static class AutoPasteService
{
    private const byte VK_CONTROL = 0x11;
    private const byte VK_V = 0x56;
    private const uint KEYEVENTF_KEYDOWN = 0x0000;
    private const uint KEYEVENTF_KEYUP = 0x0002;

    [DllImport("user32.dll")]
    private static extern nint GetForegroundWindow();

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetForegroundWindow(nint hWnd);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsWindow(nint hWnd);

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, nuint dwExtraInfo);

    /// <summary>
    /// Captures the current foreground window handle, excluding our own window.
    /// Call this before taking focus (e.g., before starting a recording).
    /// </summary>
    /// <param name="ownHwnd">The handle of our application's main window.</param>
    /// <returns>The handle of the foreground window, or <see cref="nint.Zero"/> if
    /// the foreground window is our own or could not be determined.</returns>
    public static nint CaptureCurrentForegroundWindow(nint ownHwnd)
    {
        try
        {
            var hwnd = GetForegroundWindow();
            if (hwnd != ownHwnd && hwnd != nint.Zero)
                return hwnd;
        }
        catch { }

        return nint.Zero;
    }

    /// <summary>
    /// Sets focus to the specified window and simulates Ctrl+V to paste
    /// from the clipboard. Includes a 150ms delay after the focus switch
    /// to let the target window become ready.
    /// </summary>
    public static async Task PasteToWindowAsync(nint hwnd)
    {
        if (hwnd == nint.Zero)
            return;

        try
        {
            if (!IsWindow(hwnd))
                return;

            SetForegroundWindow(hwnd);

            // Delay for the target window to fully activate before sending keystrokes.
            await Task.Delay(150).ConfigureAwait(false);

            keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYDOWN, 0);
            keybd_event(VK_V, 0, KEYEVENTF_KEYDOWN, 0);
            keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0);
            keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0);
        }
        catch { }
    }
}
