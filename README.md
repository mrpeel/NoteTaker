# Meeting Scratchpad HUD

Always-on-top floating scratchpad for meetings. Press `Enter` to append a
timestamped note to `~/workspace/notes_vault/stream_notes.jsonl`; `End Session`
seals the session and clears the feed.

## Use it as a real app (recommended)

A prebuilt `MeetingHUD.app` bundle lives in `dist/`. It has its own bundle id
(`com.neilkloot.meetinghud`), no Dock icon, and needs no terminal:

```bash
cp -r dist/MeetingHUD.app /Applications/
open /Applications/MeetingHUD.app
```

First launch: macOS may warn the app is unsigned (ad-hoc signature) — allow it
in System Settings → Privacy & Security if prompted.

### Permissions (one-time)

The global toggle hotkey installs a system key tap, which macOS attributes to
**MeetingHUD** (not your terminal):

1. System Settings → Privacy & Security → **Accessibility** → add
   `MeetingHUD` and enable it.
2. Same page → **Input Monitoring** → add/enable `MeetingHUD`.
3. Quit and relaunch the app (`Cmd+Q` while it's focused, then `open` again).

Without these, everything works except the global hotkey.

### Hotkey not firing? Diagnose in order

1. **Grants missing (most common).** On launch without them you get
   `[hud] WARNING: not Accessibility-trusted…`, and the header dot turns
   red — hover it for the reason. Grant, relaunch, done.
2. **Toggled on the wrong screen?** Every show lands on the display holding
   your cursor, and swiping Spaces pulls a visible HUD along. If you still
   can't see it, check the other display before assuming the hotkey died.
3. **Still dead?** Each press appends `hotkey fired` + `toggle -> …` lines to
   `~/workspace/notes_vault/hud_errors.log`. Press the combo on each screen,
   then check the file: lines present = tap works, look for the window;
   absent = macOS is swallowing the tap (re-check permissions, relaunch).

### Everyday use

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+Space` / `Cmd+Shift+Space` | Toggle HUD visibility globally |
| `Enter` (in input) | Add note |
| `Ctrl+Shift+E` | End session (asks if notes exist) |
| `Esc` or **Hide** button | Hide HUD — session keeps running (best before screen sharing) |
| `Cmd+Q` | Quit the app |

Drag by the header strip. The HUD joins all Spaces as a fullscreen-auxiliary
panel, so it stays put over fullscreen apps too (same hotkey toggles it
there). On multi-monitor setups it follows the active screen: every show
lands on the display holding your cursor, and swiping Spaces pulls a visible
HUD along to the current display — your in-screen position is preserved.
Only one instance runs at a time — launching again
just brings the existing HUD forward. A teal dot in the menu bar opens
Show / Hide and **Quit** (or `Cmd+Q` while the HUD is focused) — there is no
Dock icon, so the tray is the way out. Optional: add to Login Items.

## Install on another Mac

Requirements on the target: **Apple Silicon** (the bundle is arm64-only) and a
recent macOS (13+; built on 26). No Python or Homebrew needed — everything is
bundled.

1. Copy `dist/MeetingHUD.zip` over (AirDrop, USB, file share) and unzip.
   (Zip via `ditto`, not Finder-compress of a loose copy — the `.app` is a
   bundle and symlinks must survive.)
2. Move it: `cp -r MeetingHUD.app /Applications/`
3. Strip the download quarantine Gatekeeper attaches to transferred files:
   `xattr -cr /Applications/MeetingHUD.app`
4. Launch: `open /Applications/MeetingHUD.app`. If macOS still refuses
   (ad-hoc signature, no paid Developer ID): System Settings → Privacy &
   Security → **Open Anyway**, or Finder right-click → Open.
5. Grant **Accessibility** + **Input Monitoring** to `MeetingHUD` (per-machine
   grants don't transfer), then quit (`Cmd+Q`) and relaunch.
6. Vault auto-creates at `~/workspace/notes_vault/` on first note.

Alternative (clean-room): copy just the source (`hud.py`, `setup.py`,
`requirements.txt`), install Python 3.12, `pip install -r requirements.txt`,
then `python setup.py py2app` on that machine. Same result, native build.

## Dev run (terminal)

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python hud.py
```

Note: run this way, the key tap is attributed to your terminal app, so the
*terminal* needs the Accessibility/Input Monitoring grants instead.

## Rebuild the app bundle

```bash
source .venv/bin/activate
pip install py2app
python setup.py py2app   # → dist/MeetingHUD.app
```

## Notes

- Notes append as JSONL: `{"session_id", "timestamp", "raw"}`. Session close
  appends `{"session_id", "type": "session_end", "timestamp", "note_count"}`.
- Hiding (hotkey / `Esc` / Hide button) preserves the live session — quitting
  and relaunching starts a fresh `session_id`, so prefer hiding mid-day.
- Notes over 2000 chars ask for confirmation (likely an accidental paste);
  input is hard-capped at 10000 chars.
- If a vault write fails, the header dot turns red with an explanatory
  tooltip, the text stays on screen, and End Session refuses to wipe —
  a note app that can't save tells you so.
- Slot errors log to `~/workspace/notes_vault/hud_errors.log` instead of
  crashing the app.
