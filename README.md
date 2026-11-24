# Walkie

**Talk to Claude Code through your headphones.**

You kick off a refactor, go make coffee, and halfway down the hall your headphones say:
*"Needs you: run the migrations?"* You say *"yes"*. Done. Back at the desk, a little fox is
sitting on top of the terminal that's working – shaking with effort.

Walkie is a small companion that lives on your desktop and makes Claude Code
**hands-free**. It tells you what your sessions are up to, reads out their questions and
permission prompts, takes your answers by voice – and turns the buttons on your Bluetooth
headphones into its remote control.

*[Deutsche Version](README.de.md)*

## What it does

### 🎧 Your headphones are the remote
Play/Pause, Next, Previous – single, double or long press, each mapped to an action: talk,
repeat, allow, deny, pause the music. Works with ordinary Bluetooth headphones. Available gestures depend on the headset. The mic opens on a button press or after
a question if automatic listening is enabled. With voice interruption enabled, Walkie can also
listen briefly during playback.

### 🗣️ Answer by voice
Permissions and questions: *"yes"*, *"no, use yarn instead"*, or just the name of an option.
The normal dialog stays open in the terminal – whoever answers first wins.

Risky commands are read aloud and need a second, clear yes. For **critical commands** – `rm -rf`,
force pushes, production deploys, resetting a database or emptying tables, deleting
infrastructure, publishing packages – a yes is not enough: Walkie names a code and you say
*"confirm 42"*. A headphone button alone never approves them.

### 🧭 Just talk – it finds the right session
Press Play and say what you want. The walkie sends it to the right Claude Code session – by
project name, by topic, or the one you were just talking to – opens a new session for a project
that isn't running yet, or answers small questions itself. *"Show me that"* brings the
session's window to the front.

### 🔔 Hear what's going on
*"Tests are green. Should I commit?"* Walkie can shorten long answers for playback. Work reports
stay brief, while explanations and suggestions keep their substance. You hear a session name
when it helps distinguish conversations.

*"What did I miss?"* (or hold Previous, or run `walkie missed`) sums up all sessions since your
last overview: who is waiting for you, who is still working, who finished – and with what result.

### 🎵 Music ducks instead of fighting
While Walkie listens or speaks, Spotify and friends keep playing quieter (default 30 %) and return
to exactly their previous volume afterwards. Linux via PipeWire/PulseAudio, Windows via audio
sessions, macOS for Spotify and Music.

### 📝 Knows your file names
Walkie gives Whisper the files of your running sessions as context (recently changed first) and
carefully corrects afterwards: *"fix the bug in auth middleware"* arrives as `auth_middleware.py`.

### 🦊 It lives on your desktop
Drop it and it falls onto the window below. It walks along window edges and rides along when you
move them, climbs the screen edges, crawls along the top – and when a session starts working, it
hops onto that terminal and works along. Want a different look? Any Shimeji pack imports with
one command.

### ⚙️ Settings you'll actually find
On first start, a short guide walks you through language, agent, microphone and headphones.
Afterwards, right-click the figure and choose *Settings …*. **Sprache / Language** switches between English
and German for menus, announcements, speech recognition and the reading voice.
You can also open the window with `walkie gui`.

### 🔒 Local first
Speech recognition (Whisper) and the voice (Piper) run on your machine. Details below.

## Install

Walkie is developed and tested primarily with **Claude Code**. Open a Claude Code session and enter these commands one at a time.

```
/plugin marketplace add julesintown/walkie
/plugin install walkie@walkie
/walkie:start
```

`/walkie:start` sets everything up on first run (1–3 minutes, no admin rights): its own
Python environment, packages, a voice and the speech recognition model. Then a short
**Getting started** page opens: test your mic, check your headphones, learn a key.

**Headphone buttons on Linux:** If Walkie cannot read the media keys yet, open
*Getting started → Unlock buttons* or run `walkie keys unlock` in a terminal. Your system asks for
administrator approval once to install the udev rule. Reconnect the headset if needed.
Walkie itself runs as your regular user.

**Install from a terminal** (Linux/macOS):

```sh
git clone https://github.com/julesintown/walkie.git
cd walkie
./install.sh
```

On Windows, run `bin\walkie.cmd setup` in the cloned folder. Afterwards just type `walkie` to start it (the first time, this also sets it up).
Setup can download Python with
[uv](https://github.com/astral-sh/uv) if needed. Use `walkie start` to bring the figure back later.
From the repository, use `./bin/walkie start` on Linux/macOS or `bin\walkie.cmd start` on Windows.

For a headless installation, run `walkie setup --no-start --no-assets`. This installs and checks
the Python packages and skips the Piper voice and Whisper model downloads. Walkie can fetch missing
models when it runs. Set `HF_HUB_OFFLINE=1` to use only local speech assets. Run `walkie setup`
again with network access to add them. Setup reports missing speech assets or an agent CLI as
warnings and exits with an error if the required installation checks fail. To run the same checks
later, use `walkie doctor --allow-missing-agent`. Plain `walkie doctor` also requires the selected
agent CLI.

**Optional Codex CLI plugin** for session events:

```sh
codex plugin marketplace add julesintown/walkie
codex plugin add walkie@walkie
```

For voice conversations with Codex, select *Primary agent → Codex* in Walkie’s settings and
restart Walkie. If the CLI asks for approval to run the plugin hooks, approve them.

For hands-free dictation, a click acknowledges the button press. Speak after the rising tone.
A spoken “Okay” marks the end of a recording when speech was detected. A falling tone serves
as the fallback when the voice has not loaded. With `WALKIE_TALK=auto`, Claude uses session
routing. Codex, Gemini, Antigravity and custom commands receive local transcription in the
Walkie terminal (requires kitty with panel support).

Run `walkie drafts` to read pending and unconfirmed dictations. The current Claude plugin
acknowledges each submission. Older plugins leave a local copy. For an unconfirmed native
Claude dictation, the command shows the path to the recording.

## Platforms

| | Status |
|---|---|
| **Linux – KDE Plasma** (Wayland/X11, PipeWire) | developed and used daily |
| **Linux – GNOME and others** | should work; window edges only on X11 with `wmctrl`, no "show me that" on GNOME Wayland |
| **Windows 10/11** | test suite, start/stop, music ducking and thinking models (`claude`, `agy`) checked on Windows 11; headphone keys via media keys |
| **WSL2 (WSLg)** | works; `walkie setup` installs missing Qt system libraries (e.g. `libxcb-icccm4`, `libxcb-keysyms1`) |
| **macOS** | experimental – not yet tested on real hardware; needs microphone and accessibility permissions |

Linux note: reading the headphone keys needs a one-time permission – one click on *Unlock buttons*
in the first-steps page (your system asks for your password; or `walkie keys unlock`). It only
makes the headphones' key device readable for you (`extras/udev/70-walkie-avrcp.rules`).
Until then, click the figure or use the hotkey. On Wayland the global hotkey only works while an X11 window has focus – the
headphone keys are the better path there.

**Agents:** `walkie agents` shows what Walkie can do with Claude Code, Codex, Antigravity, Gemini
CLI or a custom command. Without Claude Code, Walkie thinks with whatever is installed (`codex`,
`agy -p`, `gemini -p`), so voice chat also works with only Antigravity.

**Download size:** about 200 MB of packages (Qt, ONNX, Whisper runtime), one voice (~60 MB) and
the Whisper model "base" (~140 MB). Other voices download only when you pick them.

## How it works

```
Claude Code session ── plugin module (hooks/session.tsx) ──► local service of the walkie app
   status, questions, permissions; spoken text comes back as the next prompt   (127.0.0.1 + token)
Walkie app (Python/Qt): figure · mic & speaker (miniaudio) · Whisper · Piper · keys · router
```

The plugin needs no Python inside Claude Code. If the walkie app isn't running, the plugin does
nothing – no errors, no waiting.

## Privacy – what stays local, what doesn't

- **On your computer**, Piper handles playback and local Whisper handles transcription. Settings and pending dictations are stored locally. Access to session data on the local bridge requires a token.
- **Your selected agent** receives the text you send to a session. Routing and summaries can also send excerpts of conversations through the configured model CLI. Native Claude dictation uses Claude Code’s voice feature.

- **Downloads during setup:** Python packages (PyPI), the voice (Hugging Face / rhasspy), the
  Whisper model (Hugging Face).

## Settings

`/walkie` (in Claude Code), right-click on the figure → *Settings …*, or in a terminal:

```
walkie settings             menu (arrow keys)
walkie set announce off     single values
walkie keys learn           learn a headphone key
walkie list --json          everything, for scripts and AI agents (walkie agent-guide)
walkie start | stop | restart | status | doctor
```

## Figures

Fox (default), frog and slime – free pixel art (CC0, see `figures/CREDITS.md`), converted by
`tools/make_figures.py`. Your own figures: any folder with `AnimData.xml` and
`<Animation>-Anim.png` sheets (8 directions) via *Settings → Figure → Own folder*.

**Shimeji packs** (`shime1.png` … `shime46.png`, Shimeji-ee layout) can be imported as they
are – with their own climbing, ceiling and sitting-on-the-edge poses:

    walkie sprite import ~/Downloads/some-shimeji.zip my-shimeji

Figures without climbing poses climb rotated. Window edges work on KDE (Wayland or X11), macOS
(system window list, no extra permission) and X11 desktops with `wmctrl`; elsewhere the figure
uses floor, screen edges and top only.

## Development

```
python -m unittest discover -s tests      # app, bridge, router, settings, soak test (200 rounds)
claude plugin validate . && claude plugin test .   # the plugin module
```

CI runs the Python suite on 3.10 and 3.13 and checks setup, start, bridge access and stop on
Ubuntu, macOS and Windows. Ubuntu also loads both speech models offline after setup. The plugin
job uses Claude Code 2.1.330 to validate the manifests and run the TypeScript hook tests.

License: [MIT](LICENSE). Figures: CC0 (see `figures/CREDITS.md`). Voices: [Piper](https://github.com/rhasspy/piper); speech recognition: [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
