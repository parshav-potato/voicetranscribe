using System.Globalization;
using System.Windows.Data;

namespace VoiceTranscribe.Gui.Converters;

/// <summary>
/// Converts a boolean (IsRecording/ShowStopIcon) to a record/stop icon string.
/// true -> stop icon, false -> microphone icon.
/// </summary>
public sealed class BoolToRecordIconConverter : IValueConverter
{
    private const string StopIcon = "\u23F9";
    private const string MicIcon = "\uD83C\uDFA4";

    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        return value is true ? StopIcon : MicIcon;
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
    {
        throw new NotSupportedException();
    }
}
