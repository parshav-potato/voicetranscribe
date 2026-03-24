using System.IO;
using NAudio.Wave;
using VoiceTranscribe.Core;

namespace VoiceTranscribe.Gui.Services;

public sealed class AudioRecorderService : IDisposable
{
    private const int SampleRate = 16000;
    private const int Channels = 1;
    private const int BitsPerSample = 16;

    private WaveInEvent? _waveIn;
    private WaveFileWriter? _waveWriter;
    private string? _tempWavPath;

    /// <summary>
    /// Fires on the recording thread with the current peak level (0.0 to 1.0).
    /// Subscribers must marshal to the UI thread themselves.
    /// </summary>
    public event Action<float>? LevelChanged;

    public bool IsRecording { get; private set; }

    public void StartRecording()
    {
        if (IsRecording)
            return;

        _tempWavPath = Path.Combine(Path.GetTempPath(), $"vt_rec_{Guid.NewGuid():N}.wav");

        var waveFormat = new WaveFormat(SampleRate, BitsPerSample, Channels);
        _waveWriter = new WaveFileWriter(_tempWavPath, waveFormat);

        _waveIn = new WaveInEvent
        {
            WaveFormat = waveFormat,
            BufferMilliseconds = 64, // ~1024 samples at 16 kHz
        };
        _waveIn.DataAvailable += OnDataAvailable;
        _waveIn.RecordingStopped += OnRecordingStopped;

        IsRecording = true;
        _waveIn.StartRecording();
    }

    public async Task<TempFile> StopRecordingAsync(CancellationToken ct = default)
    {
        if (!IsRecording)
            throw new InvalidOperationException("Not currently recording.");

        IsRecording = false;
        _waveIn?.StopRecording();

        _waveWriter?.Dispose();
        _waveWriter = null;

        var wavPath = _tempWavPath!;
        _tempWavPath = null;

        try
        {
            var mp3Temp = await AudioConverter.ConvertToMp3Async(wavPath, ct).ConfigureAwait(false);
            return mp3Temp;
        }
        finally
        {
            // Clean up the intermediate WAV file.
            try { File.Delete(wavPath); } catch { /* best effort */ }
        }
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs e)
    {
        _waveWriter?.Write(e.Buffer, 0, e.BytesRecorded);

        float peak = 0f;
        int sampleCount = e.BytesRecorded / 2;
        for (int i = 0; i < sampleCount; i++)
        {
            short sample = BitConverter.ToInt16(e.Buffer, i * 2);
            float abs = Math.Abs(sample) / 32768f;
            if (abs > peak)
                peak = abs;
        }

        LevelChanged?.Invoke(peak);
    }

    // NAudio requires this handler; actual cleanup happens in StopRecordingAsync.
    private void OnRecordingStopped(object? sender, StoppedEventArgs e) { }

    public void Dispose()
    {
        IsRecording = false;

        if (_waveIn is not null)
        {
            _waveIn.DataAvailable -= OnDataAvailable;
            _waveIn.RecordingStopped -= OnRecordingStopped;
            _waveIn.Dispose();
            _waveIn = null;
        }

        _waveWriter?.Dispose();
        _waveWriter = null;

        if (_tempWavPath is not null)
        {
            try { File.Delete(_tempWavPath); } catch { /* best effort */ }
            _tempWavPath = null;
        }
    }
}
