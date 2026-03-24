using System.CommandLine;
using System.CommandLine.Invocation;
using VoiceTranscribe.Cli;
using VoiceTranscribe.Core;
using VoiceTranscribe.Core.Models;

var inputArg = new Argument<string>(
    name: "input",
    getDefaultValue: () => "-",
    description: $"Audio file path, or '-' / omit for live microphone recording. " +
                 $"Supported formats: {string.Join(", ", Constants.AudioExtensions.Order())}");

var outputArg = new Argument<string>(
    name: "output",
    getDefaultValue: () => "-",
    description: "Output file path, or '-' for stdout (default: stdout)");

var languageOption = new Option<string?>(
    aliases: ["-l", "--language"],
    description: "ISO-639-1 language code (e.g. en, de, fr, ja). Omit for auto-detection.");

var promptOption = new Option<string?>(
    aliases: ["-p", "--prompt"],
    description: "Optional prompt to guide the model (e.g. spelling of names, technical terms, style).");

var formatOption = new Option<ResponseFormat>(
    aliases: ["-f", "--format"],
    getDefaultValue: () => ResponseFormat.Json,
    description: "Output format (default: Json). Use Srt or Vtt for subtitles, VerboseJson for timestamps.");

var temperatureOption = new Option<float?>(
    aliases: ["-t", "--temperature"],
    description: "Sampling temperature 0-1. Lower = more deterministic.");

var translateOption = new Option<bool>(
    name: "--translate",
    description: "Translate audio to English instead of transcribing.");

var loopbackOption = new Option<bool>(
    name: "--loopback",
    description: "Record from system audio output (speakers) instead of microphone. Windows only (WASAPI).");

var deviceOption = new Option<int?>(
    aliases: ["-d", "--device"],
    description: "Audio device index to record from. Use --list-devices to see available devices. " +
                 "Combine with --loopback to capture output from a specific device.");

var listDevicesOption = new Option<bool>(
    name: "--list-devices",
    description: "List all available audio devices and exit.");

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

rootCommand.SetHandler(async (InvocationContext context) =>
{
    var input = context.ParseResult.GetValueForArgument(inputArg);
    var output = context.ParseResult.GetValueForArgument(outputArg);
    var language = context.ParseResult.GetValueForOption(languageOption);
    var prompt = context.ParseResult.GetValueForOption(promptOption);
    var format = context.ParseResult.GetValueForOption(formatOption);
    var temperature = context.ParseResult.GetValueForOption(temperatureOption);
    var translate = context.ParseResult.GetValueForOption(translateOption);
    var loopback = context.ParseResult.GetValueForOption(loopbackOption);
    var device = context.ParseResult.GetValueForOption(deviceOption);
    var listDevices = context.ParseResult.GetValueForOption(listDevicesOption);

    var ct = context.GetCancellationToken();

    if (listDevices)
    {
        AudioRecorder.ListDevices(Console.Error);
        context.ExitCode = 0;
        return;
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
            var savedAudioPath = System.IO.Path.Combine(Constants.SaveDirectory, $"{timestamp}.mp3");
            savedTranscriptPath = System.IO.Path.Combine(Constants.SaveDirectory, $"{timestamp}.txt");

            File.Copy(audioPath, savedAudioPath, overwrite: true);
            await Console.Error.WriteLineAsync($"Audio saved to: {savedAudioPath}");
        }
        else
        {
            if (!File.Exists(input))
            {
                await Console.Error.WriteLineAsync($"Error: Input file '{input}' not found");
                context.ExitCode = 2;
                return;
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

        using var orchestrator = new TranscriptionOrchestrator();
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

        if (result.ChunksProcessed > 1)
        {
            await Console.Error.WriteLineAsync();
            await Console.Error.WriteLineAsync($"Done — transcribed {result.ChunksProcessed} chunks.");
        }

        // Write result to output
        if (output == "-")
        {
            await Console.Out.WriteLineAsync(result.Text);
        }
        else
        {
            await File.WriteAllTextAsync(output, result.Text + Environment.NewLine, ct);
        }

        // Save transcript for live recordings
        if (isLiveRecording && savedTranscriptPath is not null)
        {
            await File.WriteAllTextAsync(savedTranscriptPath, result.Text + Environment.NewLine, ct);
            await Console.Error.WriteLineAsync($"Transcript saved to: {savedTranscriptPath}");
        }

        context.ExitCode = 0;
    }
    catch (OperationCanceledException)
    {
        await Console.Error.WriteLineAsync("Operation cancelled.");
        context.ExitCode = 130;
    }
    catch (Exception ex)
    {
        await Console.Error.WriteLineAsync($"Error: {ex.Message}");
        context.ExitCode = 1;
    }
});

return await rootCommand.InvokeAsync(args);
