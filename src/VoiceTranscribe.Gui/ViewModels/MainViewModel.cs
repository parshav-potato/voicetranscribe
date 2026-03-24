using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using VoiceTranscribe.Core;
using VoiceTranscribe.Core.Models;
using VoiceTranscribe.Gui.Models;
using VoiceTranscribe.Gui.Services;

namespace VoiceTranscribe.Gui.ViewModels;

public partial class MainViewModel : ObservableObject, IDisposable
{
    private static readonly SolidColorBrush BrushTextDim = Freeze(new SolidColorBrush(ColorFromHex("#6c7086")));
    private static readonly SolidColorBrush BrushRed = Freeze(new SolidColorBrush(ColorFromHex("#f38ba8")));
    private static readonly SolidColorBrush BrushOrange = Freeze(new SolidColorBrush(ColorFromHex("#fab387")));
    private static readonly SolidColorBrush BrushBlue = Freeze(new SolidColorBrush(ColorFromHex("#89b4fa")));
    private static readonly SolidColorBrush BrushGreen = Freeze(new SolidColorBrush(ColorFromHex("#a6e3a1")));

    private readonly SettingsService _settings;
    private readonly AudioRecorderService _recorder;
    private readonly TranscriptionOrchestrator _orchestrator;
    private CancellationTokenSource? _cts;
    private nint _previousHwnd;
    private DispatcherTimer? _recordingTimer;
    private DateTime _recordStartTime;

    [ObservableProperty]
    private bool _isRecording;

    [ObservableProperty]
    private bool _isProcessing;

    [ObservableProperty]
    private bool _isAlwaysOnTop = true;

    [ObservableProperty]
    private string _statusText = "Ready";

    [ObservableProperty]
    private SolidColorBrush _statusBrush = BrushTextDim;

    [ObservableProperty]
    private double _audioLevel;

    [ObservableProperty]
    private double _progressValue = double.NaN;

    [ObservableProperty]
    private bool _isProgressIndeterminate;

    [ObservableProperty]
    private bool _isRecordButtonEnabled = true;

    [ObservableProperty]
    private bool _showStopIcon;

    [ObservableProperty]
    private string? _selectedLanguageCode;

    [ObservableProperty]
    private string _selectedLanguageName = "Auto";

    [ObservableProperty]
    private bool _translateToEnglish;

    [ObservableProperty]
    private bool _autoPasteEnabled = true;

    [ObservableProperty]
    private bool _transparentWhenIdle = true;

    [ObservableProperty]
    private string? _prompt;

    [ObservableProperty]
    private string? _tooltipPreview;

    public ObservableCollection<HistoryEntry> History { get; } = [];

    public MainViewModel(
        SettingsService settings,
        AudioRecorderService recorder,
        TranscriptionOrchestrator orchestrator)
    {
        _settings = settings;
        _recorder = recorder;
        _orchestrator = orchestrator;

        _recorder.LevelChanged += OnLevelChanged;
        LoadFromSettings();
    }

    private void LoadFromSettings()
    {
        var s = _settings.Settings;
        SelectedLanguageCode = s.Language;
        SelectedLanguageName = s.LanguageName ?? "Auto";
        TranslateToEnglish = s.Translate;
        AutoPasteEnabled = s.AutoPaste;
        TransparentWhenIdle = s.TransparentIdle;
        Prompt = s.Prompt;

        History.Clear();
        foreach (var entry in s.History)
            History.Add(entry);
    }

    private void SaveToSettings()
    {
        var s = _settings.Settings;
        s.Language = SelectedLanguageCode;
        s.LanguageName = SelectedLanguageName;
        s.Translate = TranslateToEnglish;
        s.AutoPaste = AutoPasteEnabled;
        s.TransparentIdle = TransparentWhenIdle;
        s.Prompt = Prompt;
        _settings.Save();
    }

    // ── Recording ──────────────────────────────────────────────────────

    [RelayCommand]
    private async Task ToggleRecordingAsync()
    {
        if (!IsRecording)
            await StartRecordingAsync();
        else
            await StopRecordingAsync();
    }

    private async Task StartRecordingAsync()
    {
        CaptureTargetWindow();

        _cts = new CancellationTokenSource();
        IsRecording = true;
        ShowStopIcon = true;
        _recordStartTime = DateTime.UtcNow;

        StatusText = "Recording... 0:00";
        StatusBrush = BrushRed;

        StartRecordingTimer();
        _recorder.StartRecording();
    }

    private async Task StopRecordingAsync()
    {
        IsRecordButtonEnabled = false;
        StopRecordingTimer();

        StatusText = "Processing...";
        StatusBrush = BrushOrange;

        try
        {
            using var mp3File = await _recorder.StopRecordingAsync(_cts?.Token ?? CancellationToken.None);

            IsRecording = false;
            ShowStopIcon = false;
            IsProcessing = true;
            IsProgressIndeterminate = true;

            StatusText = "Transcribing...";
            StatusBrush = BrushBlue;

            await TranscribeAndFinishAsync(mp3File.Path);
        }
        catch (Exception ex)
        {
            HandleError($"Recording failed: {ex.Message}");
        }
    }

    // ── File Transcription ─────────────────────────────────────────────

    [RelayCommand]
    private async Task TranscribeFileAsync(string filePath)
    {
        if (IsRecording || IsProcessing)
            return;

        CaptureTargetWindow();

        IsProcessing = true;
        IsRecordButtonEnabled = false;
        IsProgressIndeterminate = true;

        StatusText = "Transcribing file...";
        StatusBrush = BrushBlue;

        try
        {
            await TranscribeAndFinishAsync(filePath);
        }
        catch (Exception ex)
        {
            HandleError($"Transcription failed: {ex.Message}");
        }
    }

    private async Task TranscribeAndFinishAsync(string audioPath)
    {
        var options = new TranscriptionOptions
        {
            Language = SelectedLanguageCode,
            Prompt = Prompt,
            Format = ResponseFormat.Text,
            Translate = TranslateToEnglish,
        };

        var ct = _cts?.Token ?? CancellationToken.None;

        var result = await _orchestrator.TranscribeFileAsync(
            audioPath,
            options,
            onProgress: progress =>
            {
                // BeginInvoke to avoid blocking the orchestrator thread.
                Application.Current.Dispatcher.BeginInvoke(() =>
                {
                    if (progress.TotalChunks > 1)
                    {
                        IsProgressIndeterminate = false;
                        ProgressValue = (double)progress.CurrentChunk / progress.TotalChunks * 100;
                    }
                });
            },
            ct: ct);

        var transcript = result.Text.Trim();
        OnTranscriptionComplete(transcript);
    }

    private void OnTranscriptionComplete(string transcript)
    {
        Application.Current.Dispatcher.Invoke(() =>
        {
            IsProcessing = false;
            IsProgressIndeterminate = false;
            ProgressValue = double.NaN;

            Clipboard.SetText(transcript);

            var entry = new HistoryEntry(DateTime.Now, transcript);
            History.Add(entry);
            _settings.AddHistory(entry);

            IsRecordButtonEnabled = true;
            ShowStopIcon = false;
            StatusText = "Copied!";
            StatusBrush = BrushGreen;

            TooltipPreview = transcript.Length > 100
                ? transcript[..100] + "..."
                : transcript;

            try { System.Media.SystemSounds.Asterisk.Play(); } catch { }

            if (AutoPasteEnabled && _previousHwnd != nint.Zero)
            {
                var hwnd = _previousHwnd;
                _previousHwnd = nint.Zero;
                _ = AutoPasteService.PasteToWindowAsync(hwnd);
            }

            ResetStatusAfterDelay(TimeSpan.FromSeconds(3));
        });
    }

    // ── History ────────────────────────────────────────────────────────

    [RelayCommand]
    private void CopyFromHistory(HistoryEntry entry)
    {
        Clipboard.SetText(entry.Text);
        StatusText = "Copied!";
        StatusBrush = BrushGreen;
        ResetStatusAfterDelay(TimeSpan.FromSeconds(2));
    }

    // ── Option Toggles ─────────────────────────────────────────────────

    [RelayCommand]
    private void ToggleAlwaysOnTop()
    {
        IsAlwaysOnTop = !IsAlwaysOnTop;
    }

    [RelayCommand]
    private void SetLanguage((string? Code, string Name) lang)
    {
        SelectedLanguageCode = lang.Code;
        SelectedLanguageName = lang.Name;
        SaveToSettings();
    }

    [RelayCommand]
    private void ToggleTranslate()
    {
        TranslateToEnglish = !TranslateToEnglish;
        SaveToSettings();
    }

    [RelayCommand]
    private void ToggleAutoPaste()
    {
        AutoPasteEnabled = !AutoPasteEnabled;
        SaveToSettings();
    }

    [RelayCommand]
    private void ToggleTransparency()
    {
        TransparentWhenIdle = !TransparentWhenIdle;
        SaveToSettings();
    }

    [RelayCommand]
    private void SetPrompt(string? prompt)
    {
        Prompt = string.IsNullOrWhiteSpace(prompt) ? null : prompt;
        SaveToSettings();
    }

    // ── Recording Timer ────────────────────────────────────────────────

    private void StartRecordingTimer()
    {
        _recordingTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
        _recordingTimer.Tick += OnRecordingTimerTick;
        _recordingTimer.Start();
    }

    private void StopRecordingTimer()
    {
        _recordingTimer?.Stop();
        _recordingTimer = null;
    }

    private void OnRecordingTimerTick(object? sender, EventArgs e)
    {
        if (!IsRecording)
            return;

        var elapsed = DateTime.UtcNow - _recordStartTime;
        var mins = (int)elapsed.TotalMinutes;
        var secs = elapsed.Seconds;
        StatusText = $"Recording... {mins}:{secs:D2}";
    }

    // ── Audio Level Callback ───────────────────────────────────────────

    private void OnLevelChanged(float level)
    {
        // BeginInvoke to avoid blocking the audio recording thread.
        Application.Current.Dispatcher.BeginInvoke(() =>
        {
            AudioLevel = Math.Min(level, 1.0);
        });
    }

    // ── Error Handling ─────────────────────────────────────────────────

    private void HandleError(string message)
    {
        Application.Current.Dispatcher.Invoke(() =>
        {
            ResetUiState();
            StopRecordingTimer();

            StatusText = "Error";
            StatusBrush = BrushRed;

            MessageBox.Show(message, "Error", MessageBoxButton.OK, MessageBoxImage.Error);

            StatusText = "Ready";
            StatusBrush = BrushTextDim;
        });
    }

    // ── Helpers ────────────────────────────────────────────────────────

    /// <summary>
    /// Remembers which window had focus before we steal it, so auto-paste
    /// can return focus and paste the result there.
    /// </summary>
    private void CaptureTargetWindow()
    {
        var mainWindow = Application.Current.MainWindow;
        var ownHwnd = mainWindow is not null
            ? new System.Windows.Interop.WindowInteropHelper(mainWindow).Handle
            : nint.Zero;
        _previousHwnd = AutoPasteService.CaptureCurrentForegroundWindow(ownHwnd);
    }

    private void ResetUiState()
    {
        IsRecording = false;
        IsProcessing = false;
        IsProgressIndeterminate = false;
        ProgressValue = double.NaN;
        IsRecordButtonEnabled = true;
        ShowStopIcon = false;
        AudioLevel = 0;
    }

    private void ResetStatusAfterDelay(TimeSpan delay)
    {
        var timer = new DispatcherTimer { Interval = delay };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            if (!IsRecording && !IsProcessing)
            {
                StatusText = "Ready";
                StatusBrush = BrushTextDim;
                TooltipPreview = null;
            }
        };
        timer.Start();
    }

    private static Color ColorFromHex(string hex)
    {
        return (Color)ColorConverter.ConvertFromString(hex);
    }

    private static SolidColorBrush Freeze(SolidColorBrush brush)
    {
        brush.Freeze();
        return brush;
    }

    // ── Cleanup ────────────────────────────────────────────────────────

    public void Dispose()
    {
        _cts?.Cancel();
        _cts?.Dispose();
        StopRecordingTimer();

        _recorder.LevelChanged -= OnLevelChanged;
        _recorder.Dispose();
        _orchestrator.Dispose();

        SaveToSettings();
    }
}
