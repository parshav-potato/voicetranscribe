using System.CommandLine;
using VoiceTranscribe.Cli;
using VoiceTranscribe.Core;
using VoiceTranscribe.Core.Models;

var inputArg = new Argument<string>("input")
{
    Description = $"Audio file path, or '-' / omit for live microphone recording. " +
                  $"Supported formats: {string.Join(", ", Constants.AudioExtensions.Order())}",
    DefaultValueFactory = _ => "-",
};

var outputArg = new Argument<string>("output")
{
    Description = "Output file path, or '-' for stdout (default: stdout)",
    DefaultValueFactory = _ => "-",
};

var languageOption = new Option<string?>("-l", "--language")
{
    Description = "ISO-639-1 language code (e.g. en, de, fr, ja). Omit for auto-detection.",
};

var promptOption = new Option<string?>("-p", "--prompt")
{
    Description = "Optional prompt to guide the model (e.g. spelling of names, technical terms, style).",
};

var formatOption = new Option<ResponseFormat>("-f", "--format")
{
    Description = "Output format (default: Json). Use Srt or Vtt for subtitles, VerboseJson for timestamps.",
    DefaultValueFactory = _ => ResponseFormat.Json,
};

var temperatureOption = new Option<float?>("-t", "--temperature")
{
    Description = "Sampling temperature 0-1. Lower = more deterministic.",
};

var translateOption = new Option<bool>("--translate")
{
    Description = "Translate audio to English instead of transcribing.",
};

var loopbackOption = new Option<bool>("--loopback")
{
    Description = "Record from system audio output (speakers) instead of microphone. Windows only (WASAPI).",
};

var deviceOption = new Option<int?>("-d", "--device")
{
    Description = "Audio device index to record from. Use --list-devices to see available devices. " +
                  "Combine with --loopback to capture output from a specific device.",
};

var listDevicesOption = new Option<bool>("--list-devices")
{
    Description = "List all available audio devices and exit.",
};

var rootCommand = new RootCommand(
    "Transcribe audio using Whisper via Siemens API.\n\n" +
    "API key is read from: ~/.secret/siemens_api_key\n" +
    $"Whisper model: {Constants.WhisperModel}")
{
    inputArg,
    outputArg,
    languageOption,
    promptOption,
    formatOption,
    temperatureOption,
    translateOption,
    loopbackOption,
    deviceOption,
    listDevicesOption,
};

rootCommand.SetAction(async (parseResult, ct) =>
{
    var input = parseResult.GetValue(inputArg);
    var output = parseResult.GetValue(outputArg);
    var language = parseResult.GetValue(languageOption);
    var prompt = parseResult.GetValue(promptOption);
    var format = parseResult.GetValue(formatOption);
    var temperature = parseResult.GetValue(temperatureOption);
    var translate = parseResult.GetValue(translateOption);
    var loopback = parseResult.GetValue(loopbackOption);
    var device = parseResult.GetValue(deviceOption);
    var listDevices = parseResult.GetValue(listDevicesOption);

    if (listDevices)
    {
        AudioRecorder.ListDevices(Console.Error);
        return 0;
    }

    var isLiveRecording = input == "-";
    string audioPath;
    string? savedTranscriptPath = null;

    try
    {
        if (isLiveRecording)
        {
            using var recorder = new AudioRecorder();
            using var tempFile = await recorder.RecordAsync(loopback, device, ct);
            audioPath = tempFile.Path;

            var timestamp = DateTime.Now.ToString("yyyy-MM-dd_HHmmss");
            Directory.CreateDirectory(Constants.SaveDirectory);
            var savedAudioPath = Path.Combine(Constants.SaveDirectory, $"{timestamp}.mp3");
            savedTranscriptPath = Path.Combine(Constants.SaveDirectory, $"{timestamp}.txt");

            File.Copy(audioPath, savedAudioPath, overwrite: true);
            await Console.Error.WriteLineAsync($"Audio saved to: {savedAudioPath}");
        }
        else
        {
            if (!File.Exists(input))
            {
                await Console.Error.WriteLineAsync($"Error: Input file '{input}' not found");
                return 2;
            }

            AudioConverter.ValidateAudioFormat(input);
            audioPath = input;
        }

        var options = new TranscriptionOptions
        {
            Language = language,
            Prompt = prompt,
            Format = format,
            Temperature = temperature,
            Translate = translate,
        };

        using var orchestrator = new TranscriptionOrchestrator(ApiKeyProvider.GetApiKey());
        var result = await orchestrator.TranscribeFileAsync(
            audioPath,
            options,
            onProgress: progress =>
            {
                Console.Error.Write(
                    $"\rTranscribing chunk {progress.CurrentChunk}/{progress.TotalChunks} " +
                    $"(offset {progress.OffsetSeconds / 60:F0}m{progress.OffsetSeconds % 60:F0}s)...");
            },
            ct: ct);

        if (result.ChunkCount > 1)
        {
            await Console.Error.WriteLineAsync();
            await Console.Error.WriteLineAsync($"Done — transcribed {result.ChunkCount} chunks.");
        }

        if (output == "-")
        {
            await Console.Out.WriteLineAsync(result.Text);
        }
        else
        {
            await File.WriteAllTextAsync(output, result.Text + Environment.NewLine, ct);
        }

        if (isLiveRecording && savedTranscriptPath is not null)
        {
            await File.WriteAllTextAsync(savedTranscriptPath, result.Text + Environment.NewLine, ct);
            await Console.Error.WriteLineAsync($"Transcript saved to: {savedTranscriptPath}");
        }

        return 0;
    }
    catch (OperationCanceledException)
    {
        await Console.Error.WriteLineAsync("Operation cancelled.");
        return 130;
    }
    catch (Exception ex)
    {
        await Console.Error.WriteLineAsync($"Error: {ex.Message}");
        return 1;
    }
});

return await rootCommand.Parse(args).InvokeAsync();
