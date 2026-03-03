---
name: summarize-youtube
description: Summarize YouTube videos with multi-pass extraction. Use when user provides a YouTube URL or asks to summarize a video.
---

# summarize-youtube

Summarize any YouTube video. Fetches transcript, segments it, extracts insights in parallel, synthesizes into a structured summary adapted to the video type.

---

## Phase 0: Setup & Dependency Check

### Step 1: Check Python

```bash
python3 --version
```

If missing or below 3.10, stop and tell the user:

```
You need Python 3.10+ to run this skill.

Install it:
  Ubuntu/Debian: sudo apt install python3
  Mac: brew install python
```

Wait for confirmation before continuing.

### Step 2: Check Skill Status

```bash
python3 scripts/prepare.py --check-setup
```

Parse the JSON output:

```json
{"venv_exists": bool, "deps_installed": bool, "transcript_api_key_set": bool, "yt_dlp_available": bool}
```

Python dependencies (`youtube-transcript-api`, `httpx`) auto-install to `~/.cache/yt-summary/.venv` on first run. No user action needed.

If `transcript_api_key_set` is false, mention once:

```
For reliable transcript access (especially on cloud/VPS), you can set up TranscriptAPI:
1. Visit https://transcriptapi.com
2. Create a free account (100 free credits)
3. Set: export TRANSCRIPT_API_KEY=your_key_here

This is optional. We'll try the free method first.
```

If `yt_dlp_available` is false, mention briefly: "Optional: `pip install yt-dlp` for richer video metadata."

### Step 3: Route

| Input | Action |
|-------|--------|
| *(empty)* | Ask for a YouTube URL |
| `[url or video ID]` | Proceed to Phase 1 |
| `[url] --lang es` | Proceed with language override |

---

## Phase 1: Fetch & Segment

Run the prepare script:

```bash
python3 scripts/prepare.py <url-or-id> [--lang en]
```

### Handle Errors

- **Exit 2** — Invalid URL/ID. Tell user and show example: `https://youtube.com/watch?v=dQw4w9WgXcQ`
- **Exit 1, no TRANSCRIPT_API_KEY** — Likely IP block. Guide through TranscriptAPI setup (see Phase 0). Offer retry.
- **Exit 1, key is set** — TranscriptAPI also failed. Ask user to verify key, credits, and whether video has subtitles.
- Always provide actionable next steps and stop.

### On Success

Capture stdout (temp dir path like `/tmp/yt-summary-<video_id>`).

Read:
- `<temp_dir>/meta.json` — video metadata (title, channel, duration, segment count, language)
- `<temp_dir>/segment_*.md` — transcript segments (10-min chunks with 1-min overlap)

---

## Phase 2: Detect Video Type

Before extraction, classify the video from metadata + segment content. This determines the synthesis format in Phase 4.

Scan `meta.json` (title, channel, duration) and skim the first 2 segment files. Classify as one of:

| Type | Signals | Synthesis Format |
|------|---------|-----------------|
| **Tutorial / How-to** | Title contains "how to", "guide", "tutorial", step-by-step language | Step-by-step guide with prerequisites |
| **Interview / Podcast** | 2+ speakers, Q&A pattern, long duration (45min+), podcast in title | Topic clusters with speaker positions |
| **Conference talk** | "talk", "keynote", conference name, 15-40 min, single speaker with thesis | Key arguments with supporting evidence |
| **News / Commentary** | Reacting to events, "breaking", "update", opinion language | Claims with fact-check notes |
| **General** | Doesn't fit above categories | Standard format (default) |

Tell the user what you detected: "This looks like a [type]. I'll structure the summary accordingly."

If unsure, default to General.

---

## Phase 3: Parallel Extraction

Launch one Task subagent per segment file. All segments run in parallel.

- `subagent_type`: `general-purpose`
- Use this exact prompt per segment:

```text
You are extracting structured notes from one transcript segment.

Read file: {{segment_path}}

Return valid JSON only with this exact schema:
{
  "claims": ["..."],
  "quotes": [{"timestamp": "MM:SS or HH:MM:SS", "quote": "..."}],
  "insights": ["..."],
  "summary": "2-4 sentence summary of this segment."
}

Rules:
- claims: concrete factual or argumentative points from this segment.
- quotes: exact quoted text copied from transcript lines, each with timestamp.
- insights: practical, strategic, or conceptual implications.
- summary: concise and faithful to the segment.
- Do not include markdown fences.
- If something is missing, return empty arrays instead of inventing content.
```

Collect all subagent JSON results. Sort by segment index (`segment_001`, `segment_002`, ...).

---

## Phase 4: Synthesis

Use the synthesis prompt that matches the detected video type from Phase 2.

### Tutorial / How-to

```text
You are synthesizing a tutorial summary from ordered segment results.

Video metadata:
{{meta_json}}

Ordered segment results:
{{ordered_segment_json}}

Produce markdown with these sections:
1. **What You'll Learn** — 1-2 sentences, what the tutorial teaches
2. **Prerequisites** — what you need before starting (tools, knowledge, accounts). Skip if none.
3. **Steps** — numbered step-by-step walkthrough. Each step: what to do + why. Include timestamps.
4. **Key Tips** — practical tips/warnings mentioned during the tutorial
5. **Result** — what you should have at the end

Rules:
- Steps should be actionable. Someone should be able to follow them without watching.
- Include timestamps so users can jump to specific steps.
- Do not invent steps not present in the video.
```

### Interview / Podcast

```text
You are synthesizing a podcast/interview summary from ordered segment results.

Video metadata:
{{meta_json}}

Ordered segment results:
{{ordered_segment_json}}

Produce markdown with these sections:
1. **TL;DR** — 2-3 sentences, the core conversation
2. **Topics Discussed** — group by topic (not chronological). For each topic: key positions from each speaker, with timestamps.
3. **Notable Quotes** — up to 10, with speaker attribution and timestamps
4. **Agreements & Disagreements** — where speakers aligned or diverged
5. **Takeaways** — actionable insights from the conversation

Rules:
- Attribute positions to speakers where identifiable.
- Group by topic, not by segment order.
- Do not invent dialogue not present in segments.
```

### Conference Talk

```text
You are synthesizing a conference talk summary from ordered segment results.

Video metadata:
{{meta_json}}

Ordered segment results:
{{ordered_segment_json}}

Produce markdown with these sections:
1. **Thesis** — the speaker's core argument in 1-2 sentences
2. **Key Arguments** — each major point with supporting evidence/examples, in presentation order. Include timestamps.
3. **Data & Evidence** — specific numbers, studies, or examples cited
4. **Notable Quotes** — up to 8, with timestamps
5. **Implications** — what this means for the audience (the "so what")

Rules:
- Preserve the logical flow of the argument.
- Separate claims from evidence.
- Do not invent claims not present in segments.
```

### News / Commentary

```text
You are synthesizing a news/commentary video summary from ordered segment results.

Video metadata:
{{meta_json}}

Ordered segment results:
{{ordered_segment_json}}

Produce markdown with these sections:
1. **TL;DR** — 2-3 sentences, what happened and the creator's take
2. **Facts Reported** — objective claims made, with timestamps
3. **Commentary & Opinions** — the creator's analysis, clearly labeled as opinion
4. **Sources Mentioned** — any studies, articles, people, or events referenced
5. **Key Quotes** — up to 8, with timestamps

Rules:
- Clearly separate factual claims from opinions/commentary.
- Do not invent facts not present in segments.
```

### General (Default)

```text
You are synthesizing a full-video summary from ordered segment JSON results.

Video metadata:
{{meta_json}}

Ordered segment results:
{{ordered_segment_json}}

Produce markdown with these sections:
1. **TL;DR** — 2-3 sentences max
2. **Key Insights** — 5-10 bullets, deduplicated across segments
3. **Notable Quotes** — up to 10, with timestamps
4. **Actionable Takeaways** — concrete steps a viewer can apply
5. **Segment Summaries** — one bullet per segment, in order

Rules:
- Deduplicate across segments (overlap exists by design).
- Do not invent facts not present in segments.
```

---

## Phase 5: Save, Deliver & Cleanup

### Save Full Summary

Write the synthesized markdown to a file. Use the video title (slugified) or video ID as filename:

```
yt-summaries/<slugified-title>.md
```

If the directory doesn't exist, create it. If a file with the same name exists, append the video ID to disambiguate.

Add a metadata header to the saved file:

```markdown
# <Video Title>

**Channel:** <channel> | **Duration:** <duration> | **Type:** <detected type>
**URL:** <video url>
**Summarized:** <date>

---

<full synthesis output>
```

### Reply to User

Don't dump the full summary into chat. Give a short overview:

```
Summarized: "<Video Title>" (<duration>, <type>)
Saved to: yt-summaries/<filename>.md

<TL;DR section only — 2-3 sentences>

<3-5 top insights or key points as bullets>
```

If the video is non-English, note the detected language.
If `transcript_api_key_set` was false, add: "Tip: For reliable access on any network, set up TranscriptAPI (free 100 credits at transcriptapi.com)."

### Cleanup

Delete temp directory:
```bash
rm -rf <temp_dir>
```

If cleanup fails, still deliver the summary and mention it briefly.
