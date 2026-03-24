using System.Globalization;
using System.Windows.Data;

namespace VoiceTranscribe.Gui.Converters;

/// <summary>
/// Converts an audio level (0.0-1.0) and a container width to a pixel width.
/// Used as an IMultiValueConverter binding to both AudioLevel and ActualWidth.
/// </summary>
public sealed class LevelToWidthConverter : IMultiValueConverter
{
    public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture)
    {
        if (values.Length >= 2
            && values[0] is double level
            && values[1] is double containerWidth)
        {
            return Math.Max(0, Math.Min(level, 1.0)) * containerWidth;
        }

        return 0.0;
    }

    public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture)
    {
        throw new NotSupportedException();
    }
}
