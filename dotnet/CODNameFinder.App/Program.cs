using System.Runtime.InteropServices;
using System.Text;
using Avalonia;
using CODNameFinder.Core;
using Fluid.Avalonia.Acrylic;

namespace CODNameFinder.App;

internal static partial class Program
{
    public static string? ScreenshotPath;
    public static bool TutorialRequested;
    public static bool ValidationMode;
    public static string? GuiRunConfigPath;
    public static string? GuiEstimateConfigPath;
    public static string? GuiCaptureDirectory;
    public static string GuiCaptureOutput="";
    public static string GuiCaptureGame="COD2026";
    public static string? GuiCaptureScript;
    public static bool GuiCaptureLaunch;
    public static long StopAfterCandidates;

    [STAThread]
    public static int Main(string[] args)
    {
        Console.OutputEncoding=new UTF8Encoding(false);
        Console.InputEncoding=new UTF8Encoding(false);
        var dispatched=Cli.Dispatch(args);
        if(dispatched is int result)return result;
        TutorialRequested=args.Contains("tutorial") || args.Contains("--tutorial");
        ValidationMode=args.Contains("--validation");
        if(args.Length>=2 && args[0]=="screenshot")ScreenshotPath=args[1];
        if(args.Length>=2 && args[0]=="gui-run")
        {
            GuiRunConfigPath=args[1];
            var stop=Array.IndexOf(args,"--stop-after");
            if(stop>=0 && stop+1<args.Length)StopAfterCandidates=long.Parse(args[stop+1]);
        }
        if(args.Length>=2 && args[0]=="gui-estimate")GuiEstimateConfigPath=args[1];
        if(args.Length>=2 && args[0]=="gui-capture")
        {
            GuiCaptureDirectory=args[1];GuiCaptureLaunch=args.Contains("--launch");
            var output=Array.IndexOf(args,"--output");if(output>=0&&output+1<args.Length)GuiCaptureOutput=args[output+1];
            var game=Array.IndexOf(args,"--game");if(game>=0&&game+1<args.Length)GuiCaptureGame=args[game+1];
            var script=Array.IndexOf(args,"--script");if(script>=0&&script+1<args.Length)GuiCaptureScript=args[script+1];
            var stop=Array.IndexOf(args,"--stop-after");if(stop>=0&&stop+1<args.Length)StopAfterCandidates=long.Parse(args[stop+1]);
        }
        if(ScreenshotPath is null && GuiRunConfigPath is null && GuiEstimateConfigPath is null && GuiCaptureDirectory is null && OperatingSystem.IsWindows())
        {
            var console=GetConsoleWindow();
            if(console!=IntPtr.Zero)ShowWindow(console,0);
        }
        return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp()=>AppBuilder.Configure<App>().UsePlatformDetect()
        .UseAcrylicPerformanceDefaults(128L * 1024 * 1024, 8).LogToTrace();
    [LibraryImport("kernel32.dll")]private static partial IntPtr GetConsoleWindow();
    [LibraryImport("user32.dll")][return:MarshalAs(UnmanagedType.Bool)]private static partial bool ShowWindow(IntPtr hwnd,int command);
}
