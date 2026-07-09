# ClipMint 🍃

Turn long YouTube videos into short, viral-ready clips — automatically.

ClipMint is a local web tool that takes a YouTube URL, downloads the video, transcribes the audio with word-level timestamps, uses Claude AI to find the segments with the highest viral potential, and renders them as vertical 9:16 clips with TikTok-style subtitles, ready to post.

## How it works

```
YouTube URL → Download → Transcribe → AI Analysis → Cut & Crop → Subtitled 9:16 Clips
   (yt-dlp)              (AssemblyAI)  (Claude API)    (FFmpeg)
```

Each job moves through a status pipeline:

```
queued → downloading → transcribing → analyzing → clipping → done (or error)
```

1. **Download** — `yt-dlp` fetches the video and extracts the audio track.
2. **Transcribe** — AssemblyAI produces a full transcript with per-word timestamps.
3. **Analyze** — the transcript and video metadata are sent to Claude, which returns candidate segments scored 0–10 for viral potential, each with a hook, suggested title, tags, and reasoning. Segments below the configurable threshold are discarded; segments longer than the max duration are split at natural pauses or sentence boundaries.
4. **Clip** — FFmpeg cuts each segment, crops it to 9:16, and burns in subtitles.

## Features

- **Viral analysis powered by Claude** — every clip comes with a virality score, hook text, suggested title, tags, and an explanation of why it might perform well.
- **Three subtitle modes** — `word_highlight` (TikTok-style karaoke, word by word), `traditional` (text blocks), or `none`. Subtitles are generated as `.ASS` files and burned in with FFmpeg.
- **Self-improving prompts (few-shot learning)** — after posting a clip, you can validate it in the UI with its real-world performance (`bom` / `muito_bom` / `viral`), view count, and what you learned. Validated clips are saved as JSON examples and automatically injected into the analysis prompt for future jobs, prioritizing top performers and category diversity.
- **Smart splitting** — clips exceeding the max duration are split in two at the most natural point (sentence end or longest pause) near the midpoint.
- **Simple local stack** — SQLite database, filesystem storage, FastAPI background tasks. No Redis, no Celery, no cloud dependencies beyond the two APIs.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy (async) · SQLite |
| Frontend | Next.js 15 · React 19 · TypeScript · Tailwind CSS 4 |
| Transcription | AssemblyAI (word-level timestamps) |
| Viral analysis | Anthropic Claude API |
| Video processing | FFmpeg · yt-dlp · MediaPipe (face tracking — planned) |

## Project structure

```
clipmint/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, lifespan
│   │   ├── config.py            # Settings (pydantic-settings, .env)
│   │   ├── models.py            # ORM: Job, Transcript, Clip
│   │   ├── routers/             # /api/jobs, /api/clips
│   │   ├── workers/pipeline.py  # Pipeline orchestrator
│   │   ├── prompts/             # Viral analysis user prompt
│   │   └── services/
│   │       ├── downloader.py    # yt-dlp wrapper
│   │       ├── transcriber.py   # AssemblyAI wrapper
│   │       ├── analyzer.py      # Claude API integration
│   │       ├── clipper.py       # FFmpeg cut + 9:16 crop + subtitles
│   │       ├── subtitler.py     # .ASS subtitle generation (3 modes)
│   │       └── face_tracker.py  # MediaPipe face tracking (placeholder)
│   └── prompt_engine/
│       ├── core_prompt.txt      # Base system prompt
│       ├── prompt_builder.py    # Injects validated few-shot examples
│       └── examples/validated/  # Validated clip examples (JSON)
├── frontend/
│   └── src/
│       ├── app/                 # Home (URL input + job list), job detail
│       ├── components/          # UrlInput, JobCard, ClipCard, ValidateModal, ...
│       └── lib/                 # API client + types
├── Makefile
└── .env.example
```

## Requirements

- Python 3.11+
- Node.js 20+
- FFmpeg installed on the system (`sudo apt install ffmpeg`)
- [AssemblyAI](https://www.assemblyai.com/) API key
- [Anthropic](https://console.anthropic.com/) API key

## Setup

```bash
git clone https://github.com/pedrohazki333/clipmint.git
cd clipmint

# Configure environment variables
cp .env.example .env
# Edit .env with your API keys

# Install backend (venv) and frontend (npm) dependencies
make setup
```

## Running

```bash
# Backend (port 8000) and frontend (port 3000) together
make dev

# Or separately:
make backend
make frontend
```

Open http://localhost:3000, paste a YouTube URL, pick a subtitle mode, and hit generate. The job page polls for progress and shows each clip with its virality score, hook, and a download button as soon as it's ready.

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `ASSEMBLYAI_API_KEY` | — | AssemblyAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `VIRALITY_THRESHOLD` | `7.0` | Minimum score (0–10) for a segment to become a clip |
| `MIN_CLIP_DURATION` | `15` | Minimum clip length in seconds |
| `MAX_CLIP_DURATION` | `90` | Maximum clip length — longer segments get split |
| `STORAGE_DIR` | `./storage` | Where downloads, transcripts and clips are stored |
| `SQLITE_URL` | `sqlite+aiosqlite:///./clipmint.db` | Database URL |

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/jobs` | Create a job (YouTube URL + subtitle mode) and start the pipeline |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/{id}` | Job details, including generated clips |
| `GET` | `/api/clips/{id}` | Clip details |
| `GET` | `/api/clips/{id}/download` | Download the rendered clip (MP4) |
| `POST` | `/api/clips/{id}/validate` | Save a clip as a validated few-shot example |
| `GET` | `/health` | Health check |

## Roadmap

- [ ] Face tracking with MediaPipe, so the 9:16 crop follows the speaker
- [ ] Iterative tuning of the viral analysis prompt
- [ ] Niche-specific example filtering in the prompt builder
