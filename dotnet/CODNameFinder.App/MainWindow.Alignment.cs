using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.VisualTree;

namespace CODNameFinder.App;

public partial class MainWindow
{
    private bool InteractiveControlsCentered()
        =>ControlAlignmentIssues().Length==0;
    private string[] ControlAlignmentIssues()
    {
        // Read effective styled properties; explanations and long-form output keep reading alignment.
        var descendants=this.GetVisualDescendants().OfType<Control>().ToArray();
        var issues=new List<string>();
        foreach(var control in descendants)
        {
            var centered=control switch
            {
                TextBox box when !box.IsReadOnly=>box.TextAlignment==TextAlignment.Center&&box.VerticalContentAlignment==VerticalAlignment.Center,
                ComboBox box=>box.HorizontalContentAlignment==HorizontalAlignment.Center&&box.VerticalContentAlignment==VerticalAlignment.Center,
                ComboBoxItem item=>item.HorizontalContentAlignment==HorizontalAlignment.Center&&item.VerticalContentAlignment==VerticalAlignment.Center,
                NumericUpDown box=>box.TextAlignment==TextAlignment.Center&&box.VerticalContentAlignment==VerticalAlignment.Center,
                Button button when button is not RepeatButton=>button.HorizontalContentAlignment==HorizontalAlignment.Center&&button.VerticalContentAlignment==VerticalAlignment.Center,
                TextBlock text when text.Name=="PART_Placeholder"&&text.FindAncestorOfType<TextBox>() is {IsReadOnly:false}=>text.TextAlignment==TextAlignment.Center&&text.VerticalAlignment==VerticalAlignment.Center,
                _=>true
            };
            if(!centered)issues.Add(control.GetType().Name+":"+(control.Name??""));
        }
        return issues.Distinct().ToArray();
    }
}
