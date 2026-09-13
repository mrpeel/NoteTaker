"""py2app build:  .venv/bin/python setup.py py2app"""

from setuptools import setup

APP = ["hud.py"]
DATA_FILES: list = []
OPTIONS = {
    "argv_emulation": False,
    "packages": ["pynput"],
    "excludes": ["tkinter", "unittest", "pydoc"],
    "plist": {
        "CFBundleIdentifier": "com.neilkloot.meetinghud",
        "CFBundleDisplayName": "MeetingHUD",
        "CFBundleShortVersionString": "0.1.0",
        # Agent-style HUD: no Dock icon, floats above other apps.
        "LSUIElement": True,
        # Clipboard/hotkey apps need no document types; stay a pure agent.
        "NSSupportsAutomaticGraphicsSwitching": True,
    },
}

setup(
    app=APP,
    name="MeetingHUD",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
