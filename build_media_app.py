#!/usr/bin/env python3
"""Build a local macOS Media.app launcher using the system AppleScript compiler."""

import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent


def main():
    if sys.platform != "darwin":
        raise SystemExit("Media.app 需要在 macOS 上构建。")
    destination = ROOT / "Media.app"
    if destination.exists():
        raise SystemExit("Media.app 已存在；请先移走旧版本，再重新构建。")
    project_literal = json.dumps(str(ROOT), ensure_ascii=False)
    script = f'''on run
    try
        set bundlePath to POSIX path of (path to me)
        set launcherPath to bundlePath & "Contents/Resources/media_launcher.py"
        set projectPath to {project_literal}
        do shell script "/usr/bin/python3 " & quoted form of launcherPath & " --project " & quoted form of projectPath
    on error errorMessage
        activate
        display dialog errorMessage with title "Media 启动失败" buttons {{"确定"}} default button "确定" with icon stop
    end try
end run
'''
    with tempfile.TemporaryDirectory(prefix="media-build-") as temp:
        staging = Path(temp) / "Media.app"
        subprocess.run(["/usr/bin/osacompile", "-o", str(staging), "-"], input=script, text=True, check=True)
        shutil.copy2(ROOT / "media_launcher.py", staging / "Contents/Resources/media_launcher.py")
        plist_path = staging / "Contents/Info.plist"
        with plist_path.open("rb") as plist_file:
            info = plistlib.load(plist_file)
        info.update({
            "CFBundleName": "Media",
            "CFBundleDisplayName": "Media",
            "CFBundleIdentifier": "local.personal-ai.media",
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1",
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
        })
        with plist_path.open("wb") as plist_file:
            plistlib.dump(info, plist_file)
        subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(staging)], check=True)
        shutil.copytree(staging, destination)
    print(destination)


if __name__ == "__main__":
    main()
