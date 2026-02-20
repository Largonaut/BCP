# Document Converter Usage Guide

## Quick Start

### Step 1: Install Dependencies
```bash
pip install -r requirements_doc_converter.txt
```

**Note**: PDF conversion requires Microsoft Word (Windows) or LibreOffice (Linux/Mac)

### Step 2: Run Converter
```bash
# Convert all .md and .txt files in a directory
python markdown_to_docx_pdf.py <input_directory> [output_directory]
```

**Example for GREMLIN project**:
```bash
cd F:/claude_tools
python markdown_to_docx_pdf.py "F:/dev/GREMLIN" "F:/dev/GREMLIN/documents_for_eblc"
```

### Step 3: Find Your Files
Converted files will be in:
- `output_directory/docx/` - Microsoft Word format
- `output_directory/pdf/` - PDF format

---

## What It Converts

- **Input**: `.md` (Markdown) and `.txt` (Plain text) files
- **Output**: `.docx` (Word) and `.pdf` files
- **Preserves**: Headings, lists, code blocks, bold, italic, tables

---

## Features

### Formatting Preserved:
- ✓ Headings (# through ######)
- ✓ Bold (**text**)
- ✓ Italic (*text*)
- ✓ Inline code (`code`)
- ✓ Code blocks (```code```)
- ✓ Bullet lists (- item)
- ✓ Numbered lists (1. item)
- ✓ Tables (| col | col |)
- ✓ Block quotes (> quote)

### Styling:
- Font: Calibri 11pt (body), Consolas 10pt (code)
- Headings: Bold, decreasing size (24pt → 14pt)
- Code blocks: Indented, monospace
- Tables: Light Grid Accent style

---

## Troubleshooting

### Issue: "python-docx not installed"
**Solution**: Run `pip install python-docx markdown`

### Issue: "docx2pdf not installed" (Warning only)
**Solution**:
- Windows: Run `pip install docx2pdf` (requires MS Word)
- Linux/Mac: Install LibreOffice, then `pip install docx2pdf`
- Alternative: Use .docx files, convert to PDF manually in Word

### Issue: PDF conversion fails
**Solution**:
- Check Microsoft Word or LibreOffice is installed
- Use .docx files (conversion succeeded partially)
- Convert manually: Open .docx in Word → Save As → PDF

### Issue: Formatting looks wrong
**Solution**: Some advanced Markdown features may not convert perfectly. Edit manually in Word after conversion.

---

## Examples

### Convert entire project:
```bash
python markdown_to_docx_pdf.py ./my_project ./output
```

### Convert specific folder:
```bash
python markdown_to_docx_pdf.py ./docs ./docs_converted
```

### Convert GREMLIN docs for EBLC:
```bash
python markdown_to_docx_pdf.py "F:/dev/GREMLIN" "F:/dev/GREMLIN/eblc_documents"
```

---

## Output Structure

If you run:
```bash
python markdown_to_docx_pdf.py ./gremlin ./output
```

You get:
```
output/
├── docx/
│   ├── README.docx
│   ├── QUICKSTART.docx
│   ├── docs/
│   │   ├── TECHNICAL_SPECIFICATION.docx
│   │   └── TECHNICAL_SPECIFICATION_CONTINUED.docx
│   └── ...
└── pdf/
    ├── README.pdf
    ├── QUICKSTART.pdf
    ├── docs/
    │   ├── TECHNICAL_SPECIFICATION.pdf
    │   └── TECHNICAL_SPECIFICATION_CONTINUED.pdf
    └── ...
```

The directory structure is preserved from input to output.

---

## Tips

1. **Large Projects**: The script recursively finds all .md/.txt files. Be patient with large projects.

2. **Selective Conversion**: Create a temporary folder with only files you want to convert.

3. **Batch Conversion**: The script handles multiple files automatically - no need to run multiple times.

4. **Quality Check**: Always review converted .docx files before distributing - some manual formatting adjustments may be needed.

---

## Limitations

- **Complex Tables**: Very complex tables may not convert perfectly
- **Images**: Not yet supported (will add in future version)
- **Links**: Converted as plain text (no hyperlinks)
- **Custom HTML**: Raw HTML in Markdown is treated as text

For these cases, edit manually in Word after conversion.

---

## Future Enhancements

Planned features:
- Image embedding
- Hyperlink preservation
- Custom styling templates
- HTML rendering support
- Table of contents generation

---

**Created by**: Claude (Anthropic)
**Date**: November 11, 2024
**Location**: F:/claude_tools/

---

# Better Compaction Protocol (BCP) Tools

> **Full operations guide**: See `BCP_Operations_Guide.md` in this directory (or in `F:\Better_Compaction_Protocol\`) for complete onboarding documentation including installation, hook setup, semantic tagging, audit interpretation, and troubleshooting.

The following sections provide per-tool usage details for each BCP tool.

---

# Context Preserver Usage Guide

## Quick Start

```bash
# Archive all sessions for current project (run from project directory)
python F:/claude_tools/context_preserver.py

# Dry run - see what would be written
python F:/claude_tools/context_preserver.py --dry-run
```

## What It Does

Reads Claude Code's local `.jsonl` conversation transcripts and converts them to human-readable `.md` files organized by session.

- **Input**: `.jsonl` files from `C:\Users\<user>\.claude\projects\<encoded-project-path>\`
- **Output**: Per-session `.md` files + `index.md` in `<project>/context_archive/`

## Options

| Flag | Purpose |
|------|---------|
| `--project-path <path>` | Override workspace path (default: cwd) |
| `--session <id>` | Archive only one session |
| `--output <dir>` | Override output directory |
| `--enrich` | Create `.enriched.md` copies of legacy files with richer metadata (originals preserved) |
| `--dry-run` | Preview without writing |

## Output Structure

```
<project>/context_archive/
  index.md                           # Session list with dates and first-message titles
  session_2026-02-15_abc123.md       # One conversation per file
```

## What Gets Preserved

- User messages (full text)
- Claude responses (full text)
- Tool use calls (name + truncated input)
- Thinking blocks (in collapsed `<details>` tags)
- Timestamps per turn
- Session metadata (ID, turn count, model)

## Technical Notes

- Pure Python stdlib - no pip install needed
- **Append model**: new turns appended to existing .md files; existing data is never altered
- `--enrich` compares content before creating new versions — skips if format unchanged
- Streams .jsonl line by line - handles large transcripts
- `\r\n` normalization prevents Windows line ending mismatches
- UTF-8 throughout (safe on Windows)
- Works for any Claude Code project, not just the one it was built for

## Why This Exists

Part of the Better Compaction Protocol. Current context compaction uses lossy narrative summarization. This tool preserves the raw conversation so it can be navigated programmatically after compaction, rather than trusting a summary.

---

**Context Preserver created by**: Claude (Anthropic)
**Date**: February 15, 2026
**Location**: F:/claude_tools/

---

# Context Searcher Usage Guide

## Quick Start

```bash
# Search for a keyword across all archived sessions
python F:/claude_tools/context_searcher.py search "DDSMRLV"

# List all extracted topics
python F:/claude_tools/context_searcher.py topics --list

# Show session timeline
python F:/claude_tools/context_searcher.py timeline
```

## What It Does

Provides prepared search tools for navigating `context_archive/` directories generated by `context_preserver.py`. Replaces ad-hoc grep/read with optimized, documented subcommands.

## Subcommands

### `search <query>` — Full-text keyword search

```bash
python F:/claude_tools/context_searcher.py search "compaction"
python F:/claude_tools/context_searcher.py search "hallucination" --role user
python F:/claude_tools/context_searcher.py search "tool" --after 2026-02-01 --limit 5
```

| Flag | Purpose |
|------|---------|
| `--role user\|claude` | Filter by speaker |
| `--after DATE` | Only sessions after this date |
| `--before DATE` | Only sessions before this date |
| `--limit N` | Max results (default: 20) |

### `topics` — Topic-based navigation

```bash
python F:/claude_tools/context_searcher.py topics --list          # List all topics
python F:/claude_tools/context_searcher.py topics "Libraric"      # Find sessions about a topic
```

Reads topic tags from enriched headers (fast). Falls back to full-text search if no tag match.

### `timeline` — Chronological session overview

```bash
python F:/claude_tools/context_searcher.py timeline
python F:/claude_tools/context_searcher.py timeline --after 2026-02-01
```

Shows date, turn count, topics, and summary for each session.

### `session <id-or-date>` — Session detail view

```bash
python F:/claude_tools/context_searcher.py session 2026-02-15
python F:/claude_tools/context_searcher.py session 04c9392f --full
python F:/claude_tools/context_searcher.py session 04c9392f --turns 1-5
```

| Flag | Purpose |
|------|---------|
| `--full` | Show full turn content |
| `--turns N-M` | Show specific turn range |

### `turns <file>` — Turn-level filtering

```bash
python F:/claude_tools/context_searcher.py turns session_2026-02-15_04c9392f.md --role user
python F:/claude_tools/context_searcher.py turns session_2026-02-15_04c9392f.md --contains "tool"
python F:/claude_tools/context_searcher.py turns session_2026-02-15_04c9392f.md --tools
```

| Flag | Purpose |
|------|---------|
| `--role user\|claude` | Filter by speaker |
| `--tools` | Only tool use turns |
| `--after HH:MM` | After this time of day |
| `--before HH:MM` | Before this time of day |
| `--contains KEYWORD` | Keyword filter within turns |

## Global Options

| Flag | Purpose |
|------|---------|
| `--archive-path DIR` | Override context_archive location (default: ./context_archive/) |

## File Resolution

The searcher automatically prefers `.enriched.md` files over plain `.md` when both exist. You can pass either filename — it resolves transparently.

## Technical Notes

- Pure Python stdlib — no pip install needed
- Parses `.md` files directly using regex on the known session structure
- Works on any project's `context_archive/` directory
- UTF-8 throughout (safe on Windows)

## Why This Exists

Part of the Better Compaction Protocol. After compaction, Claude instances need prepared tools to search the archive rather than burning context window tokens on ad-hoc file reads.

---

**Context Searcher created by**: Claude (Anthropic)
**Date**: February 15, 2026
**Location**: F:/claude_tools/

---

# Context Auditor Usage Guide

## Quick Start

```bash
# Audit the latest compaction summary against the archive
python F:/claude_tools/context_auditor.py transcript.jsonl

# Audit with deep turn-content search for missing claims
python F:/claude_tools/context_auditor.py transcript.jsonl --deep

# Audit the first compaction summary (if multiple exist)
python F:/claude_tools/context_auditor.py transcript.jsonl --which 0
```

## What It Does

Extracts verifiable claims from Claude Code compaction summaries and checks them against archived session `.md` files. Reports what's confirmed, what's missing, and what contradicts the archive.

- **Input**: `.jsonl` transcript file (auto-detects `isCompactSummary` messages) or `--summary` text file
- **Output**: Audit report with per-claim verification status

## Claim Types Extracted

| Category | What's Checked |
|----------|---------------|
| File Paths | Windows/Unix paths in summary vs archive's Files Referenced |
| Tools Used | Claude Code tool names vs archive's Tools Used |
| User Quotes | Quoted user messages vs archive turn content |
| Topics | Bold terms, acronyms, multi-word phrases vs archive Topics |
| Turn Counts | "N turns" claims vs archive metadata |
| Functions/Classes | `def`/`class` names from code blocks vs archive content |

## Verification Tiers

| Marker | Meaning |
|--------|---------|
| `[FOUND]` | Confirmed in session header metadata |
| `[DEEP]` | Not in headers but found in turn content (requires `--deep`) |
| `[MISSING]` | Not found anywhere in the archive |
| `[MISMATCH]` | Contradicted by archive data (e.g., wrong turn count) |

## Options

| Flag | Purpose |
|------|---------|
| `--archive <dir>` | Override context_archive location (auto-detected if omitted) |
| `--session <id>` | Specific session file to compare against |
| `--which N` | Which compaction to audit: 0=first, -1=last (default: -1) |
| `--deep` | Search turn content for claims missing from headers |
| `--summary <file>` | Use a text file instead of extracting from .jsonl |

## Examples

```bash
# Full path example
python F:/claude_tools/context_auditor.py "C:/Users/david/.claude/projects/f--Better-Compaction-Protocol/04c9392f.jsonl" --archive "F:/Better_Compaction_Protocol/context_archive" --deep

# Audit a pasted compaction summary
python F:/claude_tools/context_auditor.py --summary compaction_text.txt --archive ./context_archive
```

## Technical Notes

- Pure Python stdlib — no pip install needed
- Streams .jsonl line by line — handles large transcripts
- UTF-8 throughout (safe on Windows)
- Auto-detects compaction summaries via `isCompactSummary` flag or marker text

## Why This Exists

Part of the Better Compaction Protocol. Compaction summaries are the highest hallucination risk point in the context chain. This tool turns that risk into a measurable signal by checking every extractable claim against the archived ground truth.

---

**Context Auditor created by**: Claude (Anthropic)
**Date**: February 16, 2026
**Location**: F:/claude_tools/

---

# Context Rerunner Usage Guide

## Quick Start

```bash
# See which runs can be rerun (no execution)
python F:/claude_tools/context_rerunner.py --project-path F:/Better_Compaction_Protocol --dry-run

# Rerun all stored audits and compare
python F:/claude_tools/context_rerunner.py --project-path F:/Better_Compaction_Protocol

# Rerun specific runs only
python F:/claude_tools/context_rerunner.py --run 4 --run 5 --project-path F:/Better_Compaction_Protocol
```

## What It Does

Reruns all stored audits from `audit_history.jsonl`, compares original vs fresh results side-by-side, and reports whether each run reproduced exactly. This is the "testing the testing" tool — validates that the auditor produces deterministic, reliable results.

- **Input**: `audit_history.jsonl` (auto-detected in context_archive/) + original `.jsonl` transcripts
- **Output**: Comparison report (text or JSON) + append-only log in `audit_rerun_history.jsonl`

## How It Works

1. Loads all entries from `audit_history.jsonl`
2. Skips historical baselines (runs without real compaction data)
3. Matches each entry to its original compaction summary via timestamp
4. Re-executes the audit using `context_auditor.run_audit()`
5. Compares original vs rerun by integer claim counts (avoids float precision issues)
6. Reports per-run match status and any diffs

## Options

| Flag | Purpose |
|------|---------|
| `--archive <dir>` | Override context_archive location (default: auto-detect) |
| `--project-path <dir>` | Project root for finding .jsonl files (default: CWD) |
| `--run <N>` | Rerun specific run number (repeatable: `--run 4 --run 5`) |
| `--format text\|json` | Output format (default: text) |
| `--dry-run` | Show which runs would be rerun, don't execute |

## Output Formats

### Text (default)
```
================================================================
  AUDIT RERUN REPORT
  Batch: 2026-02-17T22:46:48Z
  Reruns: 5 of 7 entries (2 baselines skipped)
================================================================

  Run | Original Rate | Rerun Rate | Delta  | Match
  ----|---------------|------------|--------|------
    3 |        95.3%  |      95.3% |    0pp |  YES
    4 |        73.8%  |      73.8% |    0pp |  YES
    5 |        52.6%  |      52.6% |    0pp |  YES

================================================================
  RESULT: 3/3 runs reproduced exactly
================================================================
```

### JSON (`--format json`)
Array of objects with `rerun_of`, `original_summary`, `rerun_summary`, `comparison`, `category_deltas`, `claim_diffs`, and `reproduced` fields.

## Data Storage

- **`audit_rerun_history.jsonl`**: Append-only log in context_archive/. Each rerun is a separate entry with `rerun_of` linking to the original run number and a shared `batch` timestamp.
- Reruns never pollute the main `audit_history.jsonl` trend line.

## Technical Notes

- Pure Python stdlib — no pip install needed
- Imports sibling tools (`context_auditor`, `context_preserver`) via sys.path
- Integer count comparison (found/total/missing/mismatched) avoids floating-point precision issues with stored truncated rates
- Stderr for status messages, stdout for report output
- UTF-8 throughout (safe on Windows)

## Why This Exists

Part of the Better Compaction Protocol. After proving auditor determinism manually (5/5 exact matches across all testable runs), this tool automates that validation so any future changes to the auditor can be regression-tested instantly.

---

**Context Rerunner created by**: Claude (Anthropic)
**Date**: February 17, 2026
**Location**: F:/claude_tools/

---

# Context Autoarchive Usage Guide

## Quick Start

```bash
# Pre-compaction phase: archive current session + save ground truth
python F:/claude_tools/context_autoarchive.py --phase pre --project-path F:/Better_Compaction_Protocol

# Post-compaction phase: audit summary + bundle report
python F:/claude_tools/context_autoarchive.py --phase post --project-path F:/Better_Compaction_Protocol
```

## What It Does

Compaction-aware auto-archival orchestrator that runs as a Claude Code hook. Executes in two phases around compaction events, coordinating the preserver, auditor, and report bundler.

- **Pre-phase** (`--phase pre`): Archives the current session via `context_preserver.py`, outputs ground truth metadata to stdout (injected into compaction context), and saves `ground_truth_pending.json` to `compaction_reports/` for post-phase bundling.
- **Post-phase** (`--phase post`): Reads the compaction summary from the `.jsonl` transcript, runs a full audit via `context_auditor.py`, bundles ground truth + summary + audit into a timestamped `compaction_report_*.json`, appends to `audit_history.jsonl`, and outputs a brief 7-line beacon to stdout.

## Hook Configuration

Configured in `C:\Users\<user>\.claude\settings.json` under the `hooks` key:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "type": "command",
        "command": "python F:/claude_tools/context_autoarchive.py --phase pre --project-path F:/Better_Compaction_Protocol",
        "timeout": 30000
      }
    ],
    "SessionStart": [
      {
        "type": "command",
        "command": "python F:/claude_tools/context_autoarchive.py --phase post --project-path F:/Better_Compaction_Protocol",
        "timeout": 60000,
        "matcher": "compact"
      }
    ]
  }
}
```

## Options

| Flag | Purpose |
|------|---------|
| `--phase pre\|post` | Which phase to run (required) |
| `--project-path <dir>` | Project root directory (default: from stdin JSON or CWD) |

## Output Files

| File | Location | Purpose |
|------|----------|---------|
| `ground_truth_pending.json` | `context_archive/compaction_reports/` | Pre-phase saves; post-phase consumes and deletes |
| `compaction_report_*.json` | `context_archive/compaction_reports/` | Bundled report with ground truth + summary + audit |
| `audit_history.jsonl` | `context_archive/` | Append-only trend log (one entry per audit run) |

## Bundled Report Format

Each `compaction_report_*.json` contains:
- `report_version`: Schema version (currently 1)
- `timestamp`: ISO-8601 creation time
- `session_id`: Claude Code session ID
- `run_number`: Sequential audit run number
- `ground_truth`: Turn count, duration, topics, files, tools from pre-phase
- `compaction_summary`: Full summary text + length + timestamp
- `audit`: Rate, severity-weighted rate, per-category stats, per-claim results, regressions
- `trend`: Array of all historical accuracy percentages

## Brief Beacon (stdout)

Post-phase outputs a concise 7-line summary:
```
=== COMPACTION AUDIT ===
Run 12: 46% (severity-weighted: 50%)
Trend: 71% → 71% → 95% → 74% → 53% → 64% → 57% → 89% → 64% → 40% → 46% → 46%
Regressions: None
Report: compaction_reports/compaction_report_2026-02-18_223027.json
Archive: session_2026-02-19_2051e492~#$@ACDFIJMNPRSTUXYaefmqrstuwy.md
===
```

## Technical Notes

- Pure Python stdlib — no pip install needed
- Imports sibling tools (`context_preserver`, `context_auditor`) via sys.path
- Reads hook stdin JSON for project path metadata, falls back to CWD
- Stderr for status messages, stdout for context injection / beacon
- UTF-8 throughout (safe on Windows)

## Why This Exists

Part of the Better Compaction Protocol. Automates the archive-audit pipeline so that every compaction event is automatically preserved, audited, and reported without manual intervention.

---

**Context Autoarchive created by**: Claude (Anthropic)
**Date**: February 16, 2026 (enhanced February 18, 2026)
**Location**: F:/claude_tools/

---

# BCP Dashboard Usage Guide

## Quick Start

```bash
# Launch the dashboard
python F:/claude_tools/bcp_dashboard.py

# Launch with a specific project path
python F:/claude_tools/bcp_dashboard.py --project-path F:/Better_Compaction_Protocol
```

## What It Does

Standalone tkinter dashboard for all BCP tools. Provides visual access to tool execution, semantic map browsing, audit history, compaction reports, and archive files. Designed as the primary development companion — accessibility-first alternative to terminal output.

## Tabs

### Tools Tab
- Dropdown selector for all 6 BCP tools
- Argument text field for flags and parameters
- Run button executes tool as subprocess
- Color-coded output: [FOUND] green, [MISSING] red, [DEEP] yellow, [MISMATCH] orange

### Semantic Map Tab
- Displays 1,578 valid filename characters across 11 Unicode blocks
- Mapped characters shown in green with topic labels
- Unmapped characters shown in gray as available placeholders
- Click any character for details (topic, Unicode name, block)

### Blacklist Tab
- View all blacklisted words from `semantic_map.json`
- Add/remove words with immediate save
- Controls topic filtering in auditor and preserver

### Audit History Tab
- Trend line display showing accuracy across all runs
- Canvas bar chart with color-coded bars (green/yellow/red by accuracy)
- Treeview table with per-run breakdown (date, rate, session ID)

### Reports Tab
- PanedWindow horizontal split: report list (left) + detail viewer (right)
- Treeview columns: Date, Rate, Weighted Rate, Session ID
- Rich text detail viewer with 7 sections:
  1. Header (run number, date, rates)
  2. Trend line with arrows
  3. Regressions (highlighted if any)
  4. Ground Truth (turn count, duration, topics, files, tools)
  5. Compaction Summary (first 2000 chars)
  6. Audit by Category (per-claim [FOUND]/[DEEP]/[MISSING] with severity)
  7. Cross-Reference (ground truth vs audit claims)
- Loads bundled JSON from `compaction_reports/`, falls back to `audit_history.jsonl` for legacy runs

### Archive Tab
- Lists all files in `context_archive/` with parsed metadata
- Shows date, session ID, semantic tags, enrichment version
- Double-click opens file in default text editor

## Menu Bar

### File Menu
| Item | Shortcut | Action |
|------|----------|--------|
| Browse Project... | Ctrl+O | Select project directory |
| Open Archive Folder | — | Opens `context_archive/` in file explorer |
| Open Log Folder | — | Opens `dashboard_logs/` in file explorer |
| Open Reports Folder | — | Opens `compaction_reports/` in file explorer |
| Export Current Tab | Ctrl+E | Exports active tab's content to timestamped .txt |
| Exit | Ctrl+Q | Close dashboard |

### View Menu
| Item | Shortcut | Action |
|------|----------|--------|
| Dark Mode | Ctrl+D | Toggle dark mode (persisted to config) |
| Refresh All Tabs | F5 | Reload all data sources |

## Dark Mode

VS Code Dark-inspired color scheme:
- Background: #1e1e1e, Foreground: #d4d4d4
- Secondary: #252526, Selection: #264f78
- Toggle via View menu or Ctrl+D
- State persisted in `bcp_dashboard_config.json`

## Configuration

`bcp_dashboard_config.json` (auto-created on first run):
- `project_path`: Last-used project directory
- `geometry`: Window size and position
- `dark_mode`: Boolean dark mode state

## Technical Notes

- Pure Python stdlib (tkinter) — no pip install needed
- Runs BCP tools via `subprocess.Popen` (non-blocking, streams output)
- Reads `semantic_map.json`, `audit_history.jsonl`, `compaction_reports/*.json`
- UTF-8 throughout (safe on Windows)
- ~1,300 lines

## Why This Exists

Part of the Better Compaction Protocol. David has dyslexia and aphasia — terminal/console output is not accessible. The dashboard provides visual, legible access to all BCP data and tools, serving as the primary development window rather than an afterthought.

---

**BCP Dashboard created by**: Claude (Anthropic)
**Date**: February 17, 2026 (enhanced February 18, 2026)
**Location**: F:/claude_tools/
