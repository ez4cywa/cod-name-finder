using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Platform;
using Avalonia.Threading;
using CODNameFinder.Core;
using System.Text;
using System.Text.Json;

namespace CODNameFinder.App;

public partial class App : Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    internal static WindowIcon LoadApplicationIcon()
    {
        using var stream = AssetLoader.Open(new Uri("avares://CODNameFinder/Assets/cod-name-finder.png"));
        return new WindowIcon(stream);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var window = new MainWindow();
            desktop.MainWindow = window;
            window.Opened += (_, _) => Dispatcher.UIThread.Post(async () =>
            {
                try
                {
                    if(Program.GuiCaptureDirectory is {Length:>0} captureDirectory)
                    {
                        window.ApplyCaptureValidation(captureDirectory,Program.GuiCaptureGame,Program.GuiCaptureOutput,Program.GuiCaptureScript);
                        var captured=await window.CaptureConfigurationAsync(Program.GuiCaptureLaunch);
                        window.WriteRunValidationState();
                        if(captured is null){Console.Error.WriteLine(window.ValidationStatusText);desktop.Shutdown(1);}
                        else
                        {
                            using var stream=new MemoryStream();using var writer=new Utf8JsonWriter(stream);
                            JsonSerializer.Serialize(writer,new CaptureWorkerEvent {Event="result",Result=captured},FinderJsonContext.Default.CaptureWorkerEvent);
                            writer.Flush();Console.WriteLine(Encoding.UTF8.GetString(stream.ToArray()));desktop.Shutdown(0);
                        }
                    }
                    else if (Program.GuiEstimateConfigPath is { Length: > 0 } quotePath)
                    {
                        var config=JsonSerializer.Deserialize(File.ReadAllText(quotePath),FinderJsonContext.Default.Config)
                            ?? throw new InvalidDataException("配置文件内容为空");
                        var quote=await window.EstimateConfigurationAsync(config);
                        window.WriteRunValidationState();
                        if(quote is null){Console.Error.WriteLine(window.ValidationStatusText);desktop.Shutdown(1);}
                        else
                        {
                            using var stream=new MemoryStream();using var writer=new Utf8JsonWriter(stream);
                            writer.WriteStartObject();writer.WriteString("event","estimate");writer.WritePropertyName("estimate");
                            JsonSerializer.Serialize(writer,quote,FinderJsonContext.Default.EstimateReport);writer.WriteEndObject();writer.Flush();
                            Console.WriteLine(Encoding.UTF8.GetString(stream.ToArray()));desktop.Shutdown(0);
                        }
                    }
                    else if (Program.GuiRunConfigPath is { Length: > 0 } configPath)
                    {
                        var config = JsonSerializer.Deserialize(File.ReadAllText(configPath), FinderJsonContext.Default.Config)
                            ?? throw new InvalidDataException("配置文件内容为空");
                        var report = await window.RunConfigurationAsync(config);
                        window.WriteRunValidationState();
                        if (report is null)
                        {
                            Console.Error.WriteLine(window.ValidationStatusText);
                            desktop.Shutdown(1);
                        }
                        else
                        {
                            using var stream = new MemoryStream();
                            using var writer = new Utf8JsonWriter(stream);
                            JsonSerializer.Serialize(writer, new WorkerEvent { Event = "result", Result = report }, FinderJsonContext.Default.WorkerEvent);
                            writer.Flush(); Console.WriteLine(Encoding.UTF8.GetString(stream.ToArray()));
                            desktop.Shutdown(0);
                        }
                    }
                    else if (Program.ScreenshotPath is { Length: > 0 } path)
                    {
                        await window.Capture(path, Program.TutorialRequested);
                        desktop.Shutdown(0);
                    }
                    else if (Program.TutorialRequested)
                    {
                        window.OpenTutorial();
                    }
                }
                catch (Exception exception)
                {
                    Console.Error.WriteLine("界面验证失败：" + exception.Message);
                    desktop.Shutdown(1);
                }
            });
        }
        base.OnFrameworkInitializationCompleted();
    }
}
