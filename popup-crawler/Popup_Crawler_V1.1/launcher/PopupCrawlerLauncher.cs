using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string batPath = Path.Combine(baseDir, "run_daily.bat");

        if (!File.Exists(batPath))
        {
            MessageBox.Show(
                "run_daily.bat 파일을 찾을 수 없습니다.\n\n" + batPath,
                "Popup Crawler",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return;
        }

        try
        {
            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = "/c \"\"" + batPath + "\"\"",
                WorkingDirectory = baseDir,
                UseShellExecute = true,
                WindowStyle = ProcessWindowStyle.Normal
            };

            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Popup Crawler 실행에 실패했습니다.\n\n" + ex.Message,
                "Popup Crawler",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
    }
}