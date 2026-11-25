// Walkie.exe – Starter für Windows. Bewusst winzig, damit er sich fast nie ändert:
//  - noch nicht installiert: lädt und startet install.ps1 von GitHub (sichtbares Fenster, die
//    Einrichtung dauert 1–3 Minuten und zeigt ihren Fortschritt)
//  - installiert: startet den Walkie (bzw. holt die Figur nach vorne), ohne Konsolenfenster
// Den Code des Walkies hält der Walkie selbst aktuell (selfupdate.py) – diese Datei muss dafür
// nicht neu gebaut werden. Gebaut von .github/workflows/launcher.yml.
using System;
using System.Diagnostics;
using System.IO;

static class Walkie
{
    const string Installer =
        "https://raw.githubusercontent.com/julesintown/walkie/main/install.ps1";

    static int Main(string[] args)
    {
        string home = Environment.GetEnvironmentVariable("WALKIE_HOME");
        if (string.IsNullOrEmpty(home))
            home = Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData), "walkie", "app");
        string cmd = Path.Combine(home, "bin", "walkie.cmd");

        if (!File.Exists(cmd))
        {
            var setup = new ProcessStartInfo("powershell.exe",
                "-NoProfile -ExecutionPolicy Bypass -Command \"" +
                "irm '" + Installer + "' | iex; " +
                "if ($LASTEXITCODE) { Read-Host 'Einrichtung fehlgeschlagen. Enter zum Schliessen' }\"");
            setup.UseShellExecute = false;               // eigenes, sichtbares Konsolenfenster
            using (var p = Process.Start(setup)) { p.WaitForExit(); return p.ExitCode; }
        }

        var run = new ProcessStartInfo(cmd, string.Join(" ", args));
        run.UseShellExecute = false;
        run.CreateNoWindow = true;
        run.WorkingDirectory = home;
        using (var p = Process.Start(run)) { p.WaitForExit(); return p.ExitCode; }
    }
}
