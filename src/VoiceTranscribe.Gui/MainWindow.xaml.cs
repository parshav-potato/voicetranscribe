using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Threading;
using VoiceTranscribe.Core;
using VoiceTranscribe.Gui.ViewModels;

namespace VoiceTranscribe.Gui;

/// <summary>
/// Code-behind for the main application window.
/// Handles opacity fade, drag-drop, close/tray, hotkey, and history popup.
/// </summary>
public partial class MainWindow : Window
{
    private const double IdleAlpha = 0.45;
    private const double ActiveAlpha = 1.0;
    private const double AlphaStep = 0.08;

    private readonly DispatcherTimer _fadeTimer;
    private double _targetAlpha = ActiveAlpha;
    private bool _mouseInside;

    private static readonly (string Name, string? Code)[] Languages =
    [
        ("Auto-detect", null),
        ("English", "en"),
        ("German", "de"),
        ("French", "fr"),
        ("Spanish", "es"),
        ("Japanese", "ja"),
        ("Chinese", "zh"),
        ("Dutch", "nl"),
        ("Italian", "it"),
        ("Portuguese", "pt"),
        ("Russian", "ru"),
        ("Korean", "ko"),
    ];

    public MainWindow()
    {
        InitializeComponent();

        _fadeTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(30) };
        _fadeTimer.Tick += OnFadeTick;

        if (DataContext is MainViewModel vm)
        {
            vm.PropertyChanged += OnViewModelPropertyChanged;
        }

        MouseEnter += OnWindowMouseEnter;
        MouseLeave += OnWindowMouseLeave;

        RestoreWindowPosition();

        Dispatcher.InvokeAsync(async () =>
        {
            await Task.Delay(2000);
            if (DataContext is MainViewModel m && m.TransparentWhenIdle
                && !_mouseInside && !m.IsRecording && !m.IsProcessing)
            {
                FadeTo(IdleAlpha);
            }
        });
    }

    private MainViewModel? ViewModel => DataContext as MainViewModel;

    // ── Opacity Fade ────────────────────────────────────────────────

    private void OnWindowMouseEnter(object sender, MouseEventArgs e)
    {
        _mouseInside = true;
        if (ViewModel?.TransparentWhenIdle == true)
        {
            FadeTo(ActiveAlpha);
        }
    }

    private void OnWindowMouseLeave(object sender, MouseEventArgs e)
    {
        _mouseInside = false;
        if (ViewModel is { TransparentWhenIdle: true, IsRecording: false, IsProcessing: false })
        {
            Dispatcher.InvokeAsync(async () =>
            {
                await Task.Delay(300);
                if (!_mouseInside && ViewModel is { IsRecording: false, IsProcessing: false })
                {
                    FadeTo(IdleAlpha);
                }
            });
        }
    }

    private void FadeTo(double target)
    {
        _targetAlpha = target;
        if (!_fadeTimer.IsEnabled)
        {
            _fadeTimer.Start();
        }
    }

    private void OnFadeTick(object? sender, EventArgs e)
    {
        double current = Opacity;

        if (Math.Abs(current - _targetAlpha) < AlphaStep)
        {
            Opacity = _targetAlpha;
            _fadeTimer.Stop();
            return;
        }

        Opacity = current < _targetAlpha
            ? Math.Min(current + AlphaStep, _targetAlpha)
            : Math.Max(current - AlphaStep, _targetAlpha);
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        switch (e.PropertyName)
        {
            case nameof(MainViewModel.IsRecording):
            case nameof(MainViewModel.IsProcessing):
                if (ViewModel is { IsRecording: true } or { IsProcessing: true })
                {
                    FadeTo(ActiveAlpha);
                }
                else if (ViewModel is { TransparentWhenIdle: true } && !_mouseInside)
                {
                    FadeTo(IdleAlpha);
                }
                break;

            case nameof(MainViewModel.TransparentWhenIdle):
                if (ViewModel?.TransparentWhenIdle == true && !_mouseInside
                    && ViewModel is { IsRecording: false, IsProcessing: false })
                {
                    FadeTo(IdleAlpha);
                }
                else
                {
                    FadeTo(ActiveAlpha);
                }
                break;
        }
    }

    // ── Drag & Drop ─────────────────────────────────────────────────

    private void OnDragOver(object sender, DragEventArgs e)
    {
        if (e.Data.GetDataPresent(DataFormats.FileDrop))
        {
            e.Effects = DragDropEffects.Copy;
        }
        else
        {
            e.Effects = DragDropEffects.None;
        }
        e.Handled = true;
    }

    private void OnFileDrop(object sender, DragEventArgs e)
    {
        if (!e.Data.GetDataPresent(DataFormats.FileDrop))
            return;

        if (e.Data.GetData(DataFormats.FileDrop) is not string[] files || files.Length == 0)
            return;

        foreach (string file in files)
        {
            string ext = Path.GetExtension(file).ToLowerInvariant();
            if (Constants.AudioExtensions.Contains(ext))
            {
                ViewModel?.TranscribeFileCommand.Execute(file);
                return;
            }
        }
    }

    // ── Close / Quit ────────────────────────────────────────────────

    private void OnCloseClick(object sender, RoutedEventArgs e)
    {
        QuitApp();
    }

    private void QuitApp()
    {
        SaveWindowPosition();

        if (ViewModel is IDisposable disposable)
        {
            disposable.Dispose();
        }

        Application.Current.Shutdown();
    }

    protected override void OnClosing(CancelEventArgs e)
    {
        SaveWindowPosition();
        base.OnClosing(e);
    }

    // ── Window Position Persistence ─────────────────────────────────

    private void SaveWindowPosition()
    {
        try
        {
            var settings = SettingsProvider.Load();
            settings.WindowX = (int)Left;
            settings.WindowY = (int)Top;
            SettingsProvider.Save(settings);
        }
        catch
        {
        }
    }

    private void RestoreWindowPosition()
    {
        try
        {
            var settings = SettingsProvider.Load();
            if (settings.WindowX is { } x && settings.WindowY is { } y)
            {
                double screenW = SystemParameters.PrimaryScreenWidth;
                double screenH = SystemParameters.PrimaryScreenHeight;

                if (x > -50 && x < screenW - 50 && y > -50 && y < screenH - 50)
                {
                    Left = x;
                    Top = y;
                }
            }
        }
        catch
        {
        }
    }

    // ── History Popup ───────────────────────────────────────────────

    private void OnHistoryClick(object sender, RoutedEventArgs e)
    {
        HistoryPopup.IsOpen = !HistoryPopup.IsOpen;
    }

    private void OnHistoryItemClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: HistoryEntry entry })
        {
            ViewModel?.CopyFromHistoryCommand.Execute(entry);
            HistoryPopup.IsOpen = false;
        }
    }

    // ── Options Menu ────────────────────────────────────────────────

    private void OnOptionsMenuOpened(object sender, RoutedEventArgs e)
    {
        LanguageMenu.Items.Clear();

        foreach (var (name, code) in Languages)
        {
            var item = new MenuItem
            {
                Header = name,
                IsCheckable = true,
                IsChecked = ViewModel?.SelectedLanguageName == name,
                Style = (Style)FindResource("DarkMenuItemStyle"),
            };

            string? capturedCode = code;
            item.Click += (_, _) => ViewModel?.SetLanguageCommand.Execute(capturedCode);

            LanguageMenu.Items.Add(item);
        }
    }
}
