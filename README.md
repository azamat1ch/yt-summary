# yt-summary

A [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill that summarizes YouTube videos using parallel transcript extraction.

## Install

```bash
curl -sSL https://raw.githubusercontent.com/azamat1ch/yt-summary/main/install.sh | bash
```

Or install globally (`~/.claude/skills/`):

```bash
curl -sSL https://raw.githubusercontent.com/azamat1ch/yt-summary/main/install.sh | bash -s -- --global
```

Restart Claude Code after installing.

### Manual install

```bash
mkdir -p .claude/skills/summarize-youtube/scripts
curl -sSL https://raw.githubusercontent.com/azamat1ch/yt-summary/main/SKILL.md -o .claude/skills/summarize-youtube/SKILL.md
curl -sSL https://raw.githubusercontent.com/azamat1ch/yt-summary/main/scripts/prepare.py -o .claude/skills/summarize-youtube/scripts/prepare.py
chmod +x .claude/skills/summarize-youtube/scripts/prepare.py
```

## Usage

```
/summarize-youtube <youtube-url>
```

Summaries are saved to `yt-summaries/` in your working directory. You get a TL;DR + key insights in chat, full summary in the file.

## How it works

1. Fetches transcript (`youtube-transcript-api`, with TranscriptAPI fallback)
2. Segments into 10-minute chunks with 1-minute overlap
3. Detects video type (tutorial, podcast, conference talk, news, general)
4. Parallel subagent extraction per segment (claims, quotes, insights)
5. Synthesizes into a structured summary adapted to the video type

No external LLM API needed. Runs entirely in your Claude session.

## Video Types

The summary format adapts to what you're watching:

- **Tutorial** — step-by-step guide with prerequisites and timestamps
- **Interview / Podcast** — topic clusters with speaker positions
- **Conference talk** — thesis, key arguments, evidence
- **News / Commentary** — facts vs opinions, clearly separated
- **General** — TL;DR, insights, quotes, takeaways

## Requirements

- Python 3.10+ (everything else auto-installs on first run)
- Optional: `yt-dlp` for richer video metadata
- Optional: `TRANSCRIPT_API_KEY` for reliable transcript access on cloud/VPS

## License

MIT
