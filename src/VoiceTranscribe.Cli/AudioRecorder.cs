using NAudio.CoreAudioApi;
using NAudio.Wave;
using VoiceTranscribe.Core;

namespace VoiceTranscribe.Cli;

public sealed class AudioRecorder : IDisposable
{
    private static readonly WaveFormat DefaultMicFormat = new(rate: 16000, bits: 16, channels: 1);

    private WaveFileWriter? _writer;
    private IWaveIn? _capture;
    private bool _disposed;

    /// <summary>
    /// Record from microphone or WASAPI loopback until cancellation.
    /// The user can press Enter or Ctrl+C to stop recording.
    /// Returns a TempFile pointing to the recorded mp3.
    /// </summary>
    public async Task<TempFile> RecordAsync(
        bool loopback = false,
        int? deviceIndex = null,
        CancellationToken ct = default)
    {
        var tempWav = Path.GetTempFileName();
        File.Move(tempWav, tempWav + ".wav");
        tempWav += ".wav";

        try
        {
            IWaveIn capture;
            WaveFormat format;

            if (loopback)
            {
                (capture, var deviceName) = CreateLoopbackCapture(deviceIndex);
                format = ((WasapiLoopbackCapture)capture).WaveFormat;
                await Console.Error.WriteLineAsync(
                    $"Recording system audio from: {deviceName} " +
                    $"({format.SampleRate}Hz, {format.Channels}ch)");
            }
            else if (deviceIndex.HasValue)
            {
                var waveIn = new WaveInEvent
                {
                    DeviceNumber = deviceIndex.Value,
                    WaveFormat = DefaultMicFormat,
                };
                capture = waveIn;
                format = waveIn.WaveFormat;

                var caps = WaveInEvent.GetCapabilities(deviceIndex.Value);
                await Console.Error.WriteLineAsync(
                    $"Recording from device [{deviceIndex.Value}]: {caps.ProductName} " +
                    $"({format.SampleRate}Hz, {format.Channels}ch)");
            }
            else
            {
                var waveIn = new WaveInEvent
                {
                    WaveFormat = DefaultMicFormat,
                };
                capture = waveIn;
                format = waveIn.WaveFormat;
                await Console.Error.WriteLineAsync("Recording from default input device");
            }

            _capture = capture;
            _writer = new WaveFileWriter(tempWav, format);

            capture.DataAvailable += (_, e) =>
            {
                _writer?.Write(e.Buffer, 0, e.BytesRecorded);
            };

            var recordingDone = new TaskCompletionSource<bool>();

            capture.RecordingStopped += (_, e) =>
            {
                if (e.Exception is not null)
                    recordingDone.TrySetException(e.Exception);
                else
                    recordingDone.TrySetResult(true);
            };

            capture.StartRecording();
            await Console.Error.WriteLineAsync("Recording... Press ENTER to stop.");

            // Wait for Enter key or cancellation
            await WaitForStopSignalAsync(ct);

            capture.StopRecording();
            await recordingDone.Task;

            _writer.Dispose();
            _writer = null;

            var wavInfo = new FileInfo(tempWav);
            var durationSeconds = (double)wavInfo.Length / format.AverageBytesPerSecond;
            await Console.Error.WriteLineAsync($"Recorded {durationSeconds:F1}s of audio.");

            var mp3TempFile = await AudioConverter.ConvertToMp3Async(tempWav, ct);
            return mp3TempFile;
        }
        finally
        {
            try { File.Delete(tempWav); }
            catch { /* best-effort cleanup */ }
        }
    }

    /// <summary>Print all audio devices to the given writer.</summary>
    public static void ListDevices(TextWriter output)
    {
        using var enumerator = new MMDeviceEnumerator();

        output.WriteLine();
        output.WriteLine("=== Audio Devices ===");

        var renderDevices = enumerator
            .EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active);
        var captureDevices = enumerator
            .EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active);

        var index = 0;

        output.WriteLine();
        output.WriteLine("  -- Output Devices (for --loopback) --");
        foreach (var device in renderDevices)
        {
            var format = device.AudioClient.MixFormat;
            output.WriteLine(
                $"  [{index}] {device.FriendlyName}  (OUT:{format.Channels}ch)  " +
                $"{format.SampleRate}Hz");
            index++;
        }

        output.WriteLine();
        output.WriteLine("  -- Input Devices (microphone) --");
        foreach (var device in captureDevices)
        {
            var format = device.AudioClient.MixFormat;
            output.WriteLine(
                $"  [{index}] {device.FriendlyName}  (IN:{format.Channels}ch)  " +
                $"{format.SampleRate}Hz");
            index++;
        }

        output.WriteLine();
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;

        _capture?.Dispose();
        _capture = null;

        _writer?.Dispose();
        _writer = null;
    }

    private static (WasapiLoopbackCapture Capture, string DeviceName) CreateLoopbackCapture(int? deviceIndex)
    {
        if (!deviceIndex.HasValue)
        {
            var capture = new WasapiLoopbackCapture();
            using var enumerator = new MMDeviceEnumerator();
            var defaultDevice = enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            return (capture, defaultDevice.FriendlyName);
        }

        using var enumByIndex = new MMDeviceEnumerator();
        var renderDevices = enumByIndex
            .EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active)
            .ToList();

        if (deviceIndex.Value < 0 || deviceIndex.Value >= renderDevices.Count)
        {
            throw new InvalidOperationException(
                $"Device index {deviceIndex.Value} not found among {renderDevices.Count} output devices.\n" +
                "Run with --list-devices to see available devices.");
        }

        var device = renderDevices[deviceIndex.Value];
        return (new WasapiLoopbackCapture(device), device.FriendlyName);
    }

    private static async Task WaitForStopSignalAsync(CancellationToken ct)
    {
        // Read from stdin in a background thread; honour cancellation
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);

        var enterTask = Task.Run(() =>
        {
            try { Console.ReadLine(); }
            catch { /* stdin closed or cancelled */ }
        }, cts.Token);

        var cancelTask = Task.Delay(Timeout.Infinite, cts.Token);

        await Task.WhenAny(enterTask, cancelTask);
        // Ensure the linked source is cancelled so the other task can clean up
        await cts.CancelAsync();
    }
}
