import shutil
import subprocess as sp
import sys
from pathlib import Path
from textwrap import dedent

import typer

from . import APP_NAME, CMD_NAME
from .console import console

app = typer.Typer(help="Controls the autostart behaviour of the scrobbler.")
platform = sys.platform


def get_autostart_serv_path() -> Path:
    if platform == "darwin":
        return Path(f"~/Library/LaunchAgents/{APP_NAME}.plist").expanduser()
    elif platform == "linux":
        return Path(f"~/.config/systemd/user/{APP_NAME}.service").expanduser()
    else:
        from winreg import HKEY_CURRENT_USER, ConnectRegistry, OpenKey, QueryValueEx

        key = OpenKey(
            ConnectRegistry(None, HKEY_CURRENT_USER),
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        path = QueryValueEx(key, "Startup")[0]
        return Path(path) / (APP_NAME + ".lnk")


@app.command(help="Installs and enables the autostart service.")
def enable():
    cmd_path = shutil.which(CMD_NAME)
    if not cmd_path:
        console.print(
            "Cannot find path to trakts command. Check your PATH.", style="error"
        )
        raise typer.Exit(1)

    if platform == "darwin":
        plist_loc = get_autostart_serv_path()
        plist = dedent(
            f"""
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
                "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>com.iamkroot.trakt-scrobbler</string>
                <key>ProgramArguments</key>
                <array>
                    <string>{cmd_path}</string>
                    <string>run</string>
                </array>
                <key>RunAtLoad</key>
                <true />
            </dict>
            </plist>
            """
        )
        plist_loc.parent.mkdir(parents=True, exist_ok=True)
        plist_loc.write_text(plist.strip())
        sp.check_call(["launchctl", "load", "-w", str(plist_loc)])
    elif platform == "linux":
        systemd_serv = get_autostart_serv_path()
        contents = dedent(
            f"""
            [Unit]
            Description=Trakt Scrobbler Service
            After=default.target

            [Service]
            ExecStart="{cmd_path}" run
            Env="DISPLAY=:0"

            [Install]
            WantedBy=default.target
            """
        )
        systemd_serv.parent.mkdir(parents=True, exist_ok=True)
        systemd_serv.write_text(contents.strip())
        sp.check_call(["systemctl", "--user", "daemon-reload"])
        sp.check_call(["systemctl", "--user", "enable", "trakt-scrobbler"])
    else:
        win_startup_script = get_autostart_serv_path()
        powershell_path = shutil.which("powershell")
        if not powershell_path:
            console.print("Cannot find PowerShell executable.", style="error")
            raise typer.Exit(1)

        ps_cmd_path = cmd_path.replace("'", "''")
        ps_working_directory = str(Path(cmd_path).parent).replace("'", "''")
        launcher_script = (
            f"Start-Process -FilePath '{ps_cmd_path}' -ArgumentList 'run' "
            f"-WorkingDirectory '{ps_working_directory}' -WindowStyle Hidden"
        )
        launcher_arguments = sp.list2cmdline(
            [
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                launcher_script,
            ]
        )

        try:
            import win32com.client
        except ImportError:
            win32com = None

        if win32com is not None:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(str(win_startup_script))
            shortcut.Targetpath = powershell_path
            shortcut.Arguments = launcher_arguments
            shortcut.WorkingDirectory = str(Path(cmd_path).parent)
            shortcut.save()
        else:
            # Fallback: create shortcut using PowerShell
            ps_script = f'''
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{str(win_startup_script).replace("'", "''")}')
$Shortcut.TargetPath = '{powershell_path.replace("'", "''")}'
$Shortcut.Arguments = '{launcher_arguments.replace("'", "''")}'
$Shortcut.WorkingDirectory = '{str(Path(cmd_path).parent).replace("'", "''")}'
$Shortcut.Save()
'''
            sp.check_call(["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script.strip()])

    console.print(
        "Autostart Service has been enabled. "
        "The scrobbler will now run automatically when computer starts."
    )


@app.command(help="Disables the autostart service.")
def disable():
    if platform == "darwin":
        plist_loc = get_autostart_serv_path()
        sp.check_call(["launchctl", "unload", "-w", str(plist_loc)])
    elif platform == "linux":
        sp.check_call(["systemctl", "--user", "disable", "trakt-scrobbler"])
    else:
        get_autostart_serv_path().unlink()
    console.print("Autostart disabled.")
