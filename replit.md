# AutoClip

A Flask web app that downloads videos from YouTube, TikTok, Instagram, Twitter/X, Facebook, and hundreds of other platforms (via yt-dlp), then splits them into clips of a configurable duration using FFmpeg.

The UI is in Indonesian.

## Stack

- **Backend**: Python / Flask
- **Video download**: yt-dlp
- **Video splitting**: FFmpeg (available via Nix)
- **Frontend**: Vanilla HTML/CSS/JS (served by Flask)

## How to run

```bash
uv sync          # install Python dependencies (first time only)
.pythonlibs/bin/python main.py
```

The workflow "Start application" is configured to run `.pythonlibs/bin/python main.py` and serves on port 5000.

## Project structure

```
main.py          # Flask app + video processing logic
templates/       # Jinja2 HTML templates
static/          # CSS and JS assets
uploads/         # Temporary downloaded videos (auto-created)
clips/           # Output video clips (auto-created)
pyproject.toml   # Python dependencies (managed with uv)
replit.nix       # Nix packages (ffmpeg)
```

## User preferences

- Keep existing project structure and stack.
