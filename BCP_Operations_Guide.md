# Better Compaction Protocol — Operations Guide

**Version**: 1.0
**Date**: February 19, 2026
**Author**: David Berlekamp / DoubleThink Solutions
**Tools by**: Claude (Anthropic)

---

## Table of Contents

1. [What Is The Better Compaction Protocol?](#1-what-is-the-better-compaction-protocol)
2. [Prerequisites](#2-prerequisites)
3. [Installation / Directory Layout](#3-installation--directory-layout)
4. [The Six Tools](#4-the-six-tools)
5. [Setting Up Automated Hooks](#5-setting-up-automated-hooks)
6. [The Semantic Tagging System](#6-the-semantic-tagging-system)
7. [Understanding Audit Results](#7-understanding-audit-results)
8. [The Archive Lifecycle](#8-the-archive-lifecycle)
9. [Bundled Compaction Reports](#9-bundled-compaction-reports)
10. [Troubleshooting](#10-troubleshooting)
11. [Adapting for a Different Project](#11-adapting-for-a-different-project)

---

## 1. What Is The Better Compaction Protocol?

### The Problem

When an AI language model runs out of context window space, it **compacts** — summarizing the conversation so far into a shorter narrative to free up tokens. This compaction is structurally lossy:

- **Selective amnesia**: Low-frequency topics get dropped entirely.
- **Hallucinated claims**: The summary asserts things that didn't actually happen in the conversation.
- **Flattened nuance**: Multi-turn reasoning chains collapse into single sentences.
- **Unverifiable**: Without ground truth, there is no way to know what was lost or fabricated.

In practice, compaction accuracy ranges from 40% to 95% depending on session type and compaction count. Repeated compactions within the same session progressively degrade accuracy (observed: 95% to 74% to 53% across three successive compactions).

### The Solution

The Better Compaction Protocol (BCP) is a local archive-and-audit pipeline that:

1. **Preserves** every conversation turn as human-readable Markdown before compaction occurs.
2. **Audits** the compaction summary against the preserved archive, extracting verifiable claims and checking each one.
3. **Reports** accuracy metrics per category (file paths, tools, quotes, topics, turn counts, functions) with severity weighting.
4. **Automates** the entire process via Claude Code hooks so it runs without manual intervention on every compaction event.

### Intellectual Foundations

BCP draws on two independent frameworks that converged on the same insight — that context should be treated as a navigable environment, not a disposable cache:

- **The Libraric Layer** (David Berlekamp / DoubleThink Solutions): A semantic memory architecture with DDSMRLV addressing (Domain, Depth, Scope, Mode, Reference, Layer, Version), Library Fortress security model, and Six Systems Architecture (Semantic, Temporal, Causal, Predictive Convergence, Compute, Basement).
- **MIT Recursive Language Models** (Zhang et al., Dec 2025, arXiv:2512.24601): Context-as-environment paradigm with REPL-based programmatic access and recursive sub-LM calls, demonstrating 2x performance on 10M+ token contexts.

### Design Principles

- **Accessibility-first**: The primary author has dyslexia and aphasia. All output is designed to be visually legible and navigable, not cryptic terminal dumps.
- **Zero cloud dependency**: Every tool is pure Python stdlib. Nothing phones home, nothing requires an internet connection, nothing breaks if a service shuts down.
- **Append-only / never-delete**: Data already written is sacred. Files are never altered or removed — only appended to or superseded by new versions alongside the original.
- **Pure stdlib**: No pip install required. Every tool runs on a stock Python installation.

---

## 2. Prerequisites

| Requirement | Details |
|-------------|---------|
| **Python** | 3.8 or higher. Only the standard library is used — no `pip install` needed. |
| **Claude Code CLI** | Anthropic's CLI tool for Claude. Produces `.jsonl` transcript files and provides the hook system that triggers BCP automation. |
| **Operating System** | Developed and tested on Windows 11. Should work on macOS/Linux with path adjustments (forward slashes, different home directory). |
| **tkinter** | Required for the dashboard (`bcp_dashboard.py`). Included with standard Python on Windows. On Linux, you may need to install `python3-tk` via your package manager (e.g., `sudo apt install python3-tk`). |

---

## 3. Installation / Directory Layout

BCP consists of Python scripts in a tools directory and a project directory containing the archive and reference documents.

### Tools Directory

```
F:\claude_tools\
    context_preserver.py      Tool #1: Archive transcripts to Markdown
    context_searcher.py       Tool #2: Search and navigate archives
    context_auditor.py        Tool #3: Audit compaction summaries
    context_autoarchive.py    Tool #4: Automated hook orchestrator
    context_rerunner.py       Tool #5: Audit reproducibility checker
    bcp_dashboard.py          Tool #6: Visual dashboard (tkinter)
    semantic_map.json         Global semantic character mappings
    bcp_dashboard_config.json Dashboard state (auto-created on first run)
    README.md                 Tool index
    USAGE_GUIDE.md            Detailed per-tool usage reference
    BCP_Operations_Guide.md   This document (duplicate copy)
```

### Project Directory

```
F:\Better_Compaction_Protocol\
    BCP_Operations_Guide.md                         This document (primary copy)
    The_Libraric_Layer_whitepaper_draft_1-26-26.txt  Libraric Layer whitepaper
    Libraric_Layer_Six_Systems_Architecture_11092025.txt  Six Systems spec
    MIT_Recursive_Language_Models_Abstract.pdf        MIT RLM paper
    context_archive/                                 Session archives
        session_2026-02-15_04c9392f~#PSUXfu.md       Example session file
        session_2026-02-17_1e4e3341_b~#$6@ABCD...md  Example split session
        index.md                                     Master index of all sessions
        audit_history.jsonl                          Append-only audit trend log
        audit_rerun_history.jsonl                    Reproducibility verification log
        compaction_reports/                          Bundled JSON reports
            compaction_report_2026-02-18_223027.json  Example bundled report
            ground_truth_pending.json                 Transient (pre-phase writes, post-phase consumes)
        duplicates/                                  Archived duplicate enrichment versions
        dashboard_logs/                              Dashboard export logs
```

### Raw Transcripts (Claude Code Internal)

Claude Code stores conversation transcripts as `.jsonl` files in an encoded project path:

```
C:\Users\<user>\.claude\projects\<encoded-path>\*.jsonl
```

For example, the BCP project transcripts live at:
```
C:\Users\<user>\.claude\projects\f--Better-Compaction-Protocol\
```

Each `.jsonl` file is one Claude Code session (named by UUID). The preserver reads these to produce the Markdown archives.

### Configuration Files

| File | Location | Purpose |
|------|----------|---------|
| `settings.json` | `C:\Users\<user>\.claude\settings.json` | Claude Code hooks configuration |
| `bcp_dashboard_config.json` | `F:\claude_tools\` | Dashboard window state (project path, geometry, dark mode) |
| `semantic_map.json` | `F:\claude_tools\` | Global semantic character mappings and blacklist |

---

## 4. The Six Tools

All tools are standalone Python scripts. Run them with `python <path-to-tool>`. All use only the Python standard library.

---

### 4.1 context_preserver.py — Archive Transcripts

Converts Claude Code `.jsonl` transcripts into human-readable Markdown files. Each session gets its own `.md` file with metadata headers, turn-by-turn content, semantic tags, and paragraph-level markers.

The preserver uses an **append model**: if a session file already exists, new turns are appended to it. Existing data is never altered or removed.

**Arguments:**

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--project-path` | string | Current directory | Workspace root. The preserver looks for `.jsonl` files in the Claude Code project directory and writes archives to `<project>/context_archive/`. |
| `--session` | string | All sessions | Only archive a specific session ID. |
| `--output` | string | `<project>/context_archive/` | Output directory for Markdown files. |
| `--enrich` | flag | off | Create a new enrichment version (`.enriched.md`, `.enriched2.md`, etc.) with updated formatting. Only creates the new version if content actually changed (content comparison prevents bloat). |
| `--dry-run` | flag | off | Show what would be written without writing anything. |

**Usage Examples:**

```bash
# Archive all sessions for the BCP project
python F:/claude_tools/context_preserver.py --project-path F:/Better_Compaction_Protocol

# Archive a specific session
python F:/claude_tools/context_preserver.py --project-path F:/Better_Compaction_Protocol --session 04c9392f

# Preview what would be archived without writing
python F:/claude_tools/context_preserver.py --project-path F:/Better_Compaction_Protocol --dry-run

# Create enriched version with updated formatting
python F:/claude_tools/context_preserver.py --project-path F:/Better_Compaction_Protocol --enrich
```

**Output:**
- Session `.md` files in `context_archive/` with naming format: `session_DATE_ID[~TAGS].md`
- `index.md` listing all archived sessions
- Reports unmapped topics found during semantic scanning (useful for expanding the semantic map)

---

### 4.2 context_searcher.py — Search & Navigate

Search and navigate archived session files. Provides 6 subcommands for different access patterns. Automatically prefers the highest enrichment version of each session and deduplicates by session identity.

**Global Argument:**

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--archive-path` | string | `./context_archive/` | Path to the context archive directory. |

**Subcommands:**

#### search — Full-text keyword search

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `query` | positional | (required) | Search term. |
| `--role` | choice | all | Filter by speaker: `user` or `claude`. |
| `--after` | string | none | Only sessions after this date (YYYY-MM-DD). |
| `--before` | string | none | Only sessions before this date (YYYY-MM-DD). |
| `--limit` | int | 20 | Max results to show. |

```bash
python F:/claude_tools/context_searcher.py search "DDSMRLV" --archive-path F:/Better_Compaction_Protocol/context_archive
python F:/claude_tools/context_searcher.py search "compaction" --role user --limit 50 --archive-path F:/Better_Compaction_Protocol/context_archive
```

#### topics — Topic-based navigation

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `topic` | positional (optional) | none | Topic to search for. |
| `--list` | flag | off | List all topics with session counts. |

```bash
python F:/claude_tools/context_searcher.py topics --list --archive-path F:/Better_Compaction_Protocol/context_archive
python F:/claude_tools/context_searcher.py topics "Libraric" --archive-path F:/Better_Compaction_Protocol/context_archive
```

#### timeline — Chronological overview

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `--after` | string | none | Only sessions after this date (YYYY-MM-DD). |
| `--before` | string | none | Only sessions before this date (YYYY-MM-DD). |

```bash
python F:/claude_tools/context_searcher.py timeline --after 2026-02-01 --archive-path F:/Better_Compaction_Protocol/context_archive
```

#### session — Session detail view

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `target` | positional | (required) | Session ID fragment, date, or filename. |
| `--full` | flag | off | Show full turn content (default: summary only). |
| `--turns` | string | all | Turn range to show (e.g., `1-5` or `3`). |

```bash
python F:/claude_tools/context_searcher.py session 04c9392f --full --archive-path F:/Better_Compaction_Protocol/context_archive
python F:/claude_tools/context_searcher.py session 2026-02-15 --turns 1-10 --archive-path F:/Better_Compaction_Protocol/context_archive
```

#### turns — Turn-level filtering

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `file` | positional | (required) | Session filename or partial match. |
| `--role` | choice | all | Filter by speaker: `user` or `claude`. |
| `--tools` | flag | off | Only show tool-use turns. |
| `--after` | string | none | After this time (HH:MM). |
| `--before` | string | none | Before this time (HH:MM). |
| `--contains` | string | none | Keyword filter within turn content. |

```bash
python F:/claude_tools/context_searcher.py turns session_2026-02-15_04c9392f.md --role user --archive-path F:/Better_Compaction_Protocol/context_archive
```

#### semantic — Semantic tag character search

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `char` | positional (optional) | none | Semantic character to search for. |
| `--list` | flag | off | Show the full semantic mapping table. |
| `--deep` | flag | off | Show paragraph-level locations within files. |

```bash
python F:/claude_tools/context_searcher.py semantic --list --archive-path F:/Better_Compaction_Protocol/context_archive
python F:/claude_tools/context_searcher.py semantic "$" --deep --archive-path F:/Better_Compaction_Protocol/context_archive
```

---

### 4.3 context_auditor.py — Verify Compaction Accuracy

Audits compaction summaries against archived session files. Extracts verifiable claims from the summary (file paths, tool names, user quotes, topics, turn counts, function names) and checks each one against the archive.

**Arguments:**

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `jsonl` | positional (optional) | none | Path to `.jsonl` transcript file. The auditor auto-finds compaction summaries (messages with `isCompactSummary` flag). |
| `--summary` | string | none | Path to a plain text file containing a compaction summary (alternative to `.jsonl` input). |
| `--archive` | string | auto-detected | Path to `context_archive/` directory. |
| `--session` | string | none | Specific session archive file to compare against. |
| `--which` | int | -1 | Which compaction summary to audit: `0` = first, `-1` = last (default). |
| `--deep` | flag | off | Search turn content for claims missing from headers. |
| `--format` | choice | `text` | Output format: `text` (human-readable) or `json` (structured). |
| `--history-file` | string | none | Path to `audit_history.jsonl` for trend analysis. |

**Claim Categories and Severity Levels:**

| Category | Severity | Weight | What It Checks |
|----------|----------|--------|----------------|
| File Paths | CRITICAL | 4 | File paths mentioned in the summary exist in the archive |
| Functions/Classes | CRITICAL | 4 | Function and class names from code blocks exist in the archive |
| Tools Used | MAJOR | 3 | Claude Code tool names (Read, Write, Bash, etc.) were actually used |
| User Quotes | MAJOR | 3 | Quoted user messages match what the user actually said |
| Topics | MINOR | 2 | Key topics extracted from the summary appear in the archive |
| Turn Counts | INFO | 1 | "N turns" claims match the actual turn count |

**Verification Tiers:**

1. **FOUND** — Claim located in archive metadata (session headers).
2. **FOUND (deep)** — Claim located in turn content (requires `--deep` flag).
3. **MISSING** — Claim not found anywhere in the archive.
4. **MISMATCH** — Claim found but value differs (e.g., turn count doesn't match).

**Usage Examples:**

```bash
# Audit the latest compaction in a transcript
python F:/claude_tools/context_auditor.py "C:/Users/david/.claude/projects/f--Better-Compaction-Protocol/2051e492-2f22-4269-9767-5629a1bebc64.jsonl" --archive F:/Better_Compaction_Protocol/context_archive --deep

# Audit with JSON output for programmatic use
python F:/claude_tools/context_auditor.py transcript.jsonl --archive F:/Better_Compaction_Protocol/context_archive --deep --format json

# Audit the first compaction in a multi-compaction session
python F:/claude_tools/context_auditor.py transcript.jsonl --which 0 --archive F:/Better_Compaction_Protocol/context_archive

# Audit from a pasted summary text file
python F:/claude_tools/context_auditor.py --summary pasted_summary.txt --archive F:/Better_Compaction_Protocol/context_archive

# Include trend analysis from audit history
python F:/claude_tools/context_auditor.py transcript.jsonl --archive F:/Better_Compaction_Protocol/context_archive --deep --history-file F:/Better_Compaction_Protocol/context_archive/audit_history.jsonl
```

**Output (text mode):**
- Category-by-category breakdown showing each claim's status
- Severity labels on each claim
- Overall accuracy rate and severity-weighted rate
- Trend line across all historical runs (if `--history-file` provided)
- Regression alerts (if accuracy dropped >5 percentage points from previous run)

**Output (JSON mode):**
- Structured dict with per-claim test cases (id, category, claim, status, severity, location)
- Category-level stats (total, found, missing, mismatched, rate)
- Trend data and regression info

---

### 4.4 context_autoarchive.py — Automated Hook Orchestrator

Compaction-aware auto-archival orchestrator designed to run as Claude Code hooks. Coordinates the preserver and auditor in a two-phase pipeline around compaction events.

**Arguments:**

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--phase` | choice (required) | none | Which phase to run: `pre` or `post`. |
| `--project-path` | string | from hook stdin or CWD | Project root directory. |

**Phase Details:**

#### --phase pre (runs before compaction)

1. Archives the current session via `context_preserver.py`.
2. Extracts ground truth metadata (turn count, session ID, duration, topics, files, tools).
3. Saves ground truth to `context_archive/compaction_reports/ground_truth_pending.json`.
4. Outputs a structured ground truth block to stdout (this gets injected into the compaction context, giving the compactor better data to work with).

#### --phase post (runs after compaction)

1. Finds the latest compaction summary in the `.jsonl` transcript.
2. Runs `context_auditor.py` verification against the archive.
3. Appends results to `audit_history.jsonl` (append-only trend log).
4. Bundles ground truth + compaction summary + audit results into a timestamped `compaction_report_*.json`.
5. Detects regressions (>5 percentage point drop from previous run).
6. Outputs a brief 7-line beacon to stdout:

```
=== COMPACTION AUDIT ===
Run 14: 100% (severity-weighted: 100%)
Trend: 71% -> 71% -> 95% -> 74% -> 53% -> 64% -> 57% -> 89% -> 64% -> 40% -> 46% -> 46% -> 100% -> 100%
Regressions: None
Report: compaction_reports/compaction_report_2026-02-19_002200.json
Archive: session_2026-02-19_20062c75_b~#ABCFIJMNPSTUXYefpsuwy.md
===
```

**Usage Examples:**

```bash
# Pre-compaction phase (normally run by hook, but can be run manually)
python F:/claude_tools/context_autoarchive.py --phase pre --project-path F:/Better_Compaction_Protocol

# Post-compaction phase
python F:/claude_tools/context_autoarchive.py --phase post --project-path F:/Better_Compaction_Protocol
```

**Output Files:**

| File | Location | Purpose |
|------|----------|---------|
| `ground_truth_pending.json` | `context_archive/compaction_reports/` | Pre-phase writes; post-phase reads and consumes |
| `compaction_report_*.json` | `context_archive/compaction_reports/` | Bundled report (ground truth + summary + audit) |
| `audit_history.jsonl` | `context_archive/` | Append-only trend log (one entry per audit run) |

---

### 4.5 context_rerunner.py — Audit Reproducibility

Reruns stored audits from `audit_history.jsonl` and compares original results to fresh results. Proves that the auditor is deterministic — given the same input, it produces the same output. Validated with 5/5 exact matches across all testable runs.

**Arguments:**

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--archive` | string | none | Path to `context_archive/` directory. |
| `--project-path` | string | Current directory | Project root for finding `.jsonl` transcript files. |
| `--run` | int (repeatable) | all | Specific run number(s) to rerun. Can be used multiple times: `--run 4 --run 5`. |
| `--format` | choice | `text` | Output format: `text` or `json`. |
| `--dry-run` | flag | off | Show which runs would be rerun without executing. |

**Usage Examples:**

```bash
# Rerun all stored audits and compare
python F:/claude_tools/context_rerunner.py --project-path F:/Better_Compaction_Protocol

# Preview which runs would be rerun
python F:/claude_tools/context_rerunner.py --project-path F:/Better_Compaction_Protocol --dry-run

# Rerun specific runs only
python F:/claude_tools/context_rerunner.py --project-path F:/Better_Compaction_Protocol --run 4 --run 5

# JSON output
python F:/claude_tools/context_rerunner.py --project-path F:/Better_Compaction_Protocol --format json
```

**Notes:**
- Skips historical baseline entries (runs 1-2) which don't have stored compaction data.
- Saves rerun results to `audit_rerun_history.jsonl` (separate from the main trend log).
- Compares by integer claim counts to avoid floating-point precision issues.

---

### 4.6 bcp_dashboard.py — Visual Dashboard

Standalone tkinter dashboard providing visual access to all BCP tools, data, and reports. Designed as the primary development companion — an accessibility-first alternative to terminal output.

**Arguments:**

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `--project-path` | string | `F:/Better_Compaction_Protocol` | Project root directory. |

**Usage:**

```bash
# Launch the dashboard
python F:/claude_tools/bcp_dashboard.py

# Launch with a specific project
python F:/claude_tools/bcp_dashboard.py --project-path F:/my_other_project
```

**Tabs:**

| Tab | Purpose |
|-----|---------|
| **Tools** | Dropdown selector for all 6 BCP tools. Argument text field. Run button executes as subprocess with color-coded output: [FOUND] green, [MISSING] red, [DEEP] yellow, [MISMATCH] orange. |
| **Semantic Map** | Displays 1,578 valid filename characters across 11 Unicode blocks. Mapped characters shown in green with topic labels. Unmapped characters shown in gray. Click any character for details. |
| **Blacklist** | View/add/remove blacklisted words (excluded from topic extraction). Saves directly to `semantic_map.json`. |
| **Audit History** | Trend line display showing accuracy across all runs. Canvas bar chart (green >= 80%, orange >= 60%, red < 60%). Treeview table with per-run breakdown. |
| **Reports** | Split view: report list (left) + rich detail viewer (right). 7 sections: Header, Trend, Regressions, Ground Truth, Compaction Summary, Audit by Category, Cross-Reference. Loads bundled JSON from `compaction_reports/`, falls back to `audit_history.jsonl` for legacy runs. |
| **Archive** | Lists all files in `context_archive/` with parsed metadata (date, session ID, semantic tags, enrichment version). Double-click opens in default text editor. |

**Menu Bar:**

| Menu | Item | Shortcut | Action |
|------|------|----------|--------|
| File | Browse Project... | Ctrl+O | Select a different project directory |
| File | Open Archive Folder | — | Opens `context_archive/` in file explorer |
| File | Open Log Folder | — | Opens `dashboard_logs/` in file explorer |
| File | Open Reports Folder | — | Opens `compaction_reports/` in file explorer |
| File | Export Current Tab | Ctrl+E | Exports active tab's content to timestamped `.txt` |
| File | Exit | Ctrl+Q | Close dashboard |
| View | Dark Mode | Ctrl+D | Toggle dark mode (VS Code Dark colors, persisted to config) |
| View | Refresh All Tabs | F5 | Reload all data sources |

**Configuration:**

Auto-saved to `bcp_dashboard_config.json`:
- `project_path`: Last-used project directory
- `geometry`: Window size and position
- `dark_mode`: Boolean dark mode state

---

## 5. Setting Up Automated Hooks

BCP hooks into Claude Code's event system so that archiving and auditing happen automatically on every compaction event.

### Step 1: Locate your Claude Code settings file

```
C:\Users\<your-username>\.claude\settings.json
```

### Step 2: Add the hook configuration

Add the `hooks` key to your `settings.json`. Here is the actual working configuration:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python F:/claude_tools/context_autoarchive.py --phase pre",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "python F:/claude_tools/context_autoarchive.py --phase post",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

**Important structural notes:**
- Each hook event (`PreCompact`, `SessionStart`) contains an array of hook groups.
- Each hook group contains a `hooks` array with the actual command entries.
- The `SessionStart` hook uses `"matcher": "compact"` to only fire after compaction events (not on fresh session starts).
- Timeouts are in seconds (30 for pre-phase, 60 for post-phase).

### Step 3: Understand the flow

When a compaction event occurs, the following sequence executes:

```
1. Context window fills up (or user runs /compact)
          |
2. PreCompact hook fires
   -> context_autoarchive.py --phase pre
   -> Archives current session to .md
   -> Saves ground_truth_pending.json
   -> Outputs ground truth block to stdout
          |
3. Ground truth stdout is injected into compaction input
          |
4. Cloud compaction generates summary narrative
          |
5. New session starts with compaction summary
          |
6. SessionStart (compact matcher) hook fires
   -> context_autoarchive.py --phase post
   -> Reads compaction summary from .jsonl
   -> Runs auditor against archive
   -> Bundles report to compaction_report_*.json
   -> Appends to audit_history.jsonl
   -> Outputs 7-line beacon to stdout
```

### Step 4: Verify hooks are working

After your next compaction event, check:

1. **New archive file** in `context_archive/` — the pre-phase archived the session.
2. **New entry** at the end of `context_archive/audit_history.jsonl` — the post-phase ran the audit.
3. **New report** in `context_archive/compaction_reports/compaction_report_*.json` — the post-phase bundled the report.
4. **Dashboard Reports tab** — launch the dashboard and check for the new entry.

---

## 6. The Semantic Tagging System

BCP assigns semantic tags to session files using single Unicode characters, each mapped to a topic. This creates a compositional keyword index embedded in the filename itself.

### Filename Format

```
session_DATE_ID[_SUFFIX][~TAGS][.VERSION].md
```

| Component | Example | Meaning |
|-----------|---------|---------|
| `DATE` | `2026-02-15` | Session date |
| `ID` | `04c9392f` | First 8 chars of Claude Code session UUID |
| `_SUFFIX` | `_b`, `_c`, `_d` | Logical session split (post-compaction continuations) |
| `~TAGS` | `~#$6@ABCDFIJMNPSTUXYaefmpqstuwy` | Semantic tag characters |
| `.VERSION` | `.enriched.md`, `.enriched5.md` | Enrichment version |

**Full example:**
```
session_2026-02-17_1e4e3341_b~#$6@ABCDFIJLMNOPSTUXYaefmpqstuwy.md
```
This is the second logical session (`_b`) from session `1e4e3341` on Feb 17, with semantic tags indicating topics like compaction (`#`), Libraric Layer (`$`), Six Systems (`6`), MIT RLM (`@`), and others.

### How semantic_map.json Works

Located at `F:\claude_tools\semantic_map.json`, this file contains:

- **`_version`**: Schema version (currently 2).
- **`mappings`**: An object mapping single characters to topic names. Example: `"#": "compaction"`, `"$": "Libraric Layer"`, `"@": "MIT"`.
- **`blacklist`**: An array of common English words excluded from topic extraction (e.g., "and", "the", "but", "for").

Currently 44 characters are mapped. The full Unicode pool of filename-safe characters (~1,578 across 11 blocks) is available for assignment.

### How Tags Are Assigned

The preserver's `scan_text_for_semantics()` function scans turn content against all mappings in `semantic_map.json` using word-boundary matching (`\b`). Any topic mentioned at least once (threshold=1) gets its character included in the filename tag.

### Adding New Mappings

**Via the dashboard:**
1. Open the **Semantic Map** tab to see all available characters.
2. Green = already mapped. Gray = available.
3. Click a character to see its details.
4. Edit `semantic_map.json` directly to add the mapping.

**Via the Blacklist tab:**
1. Open the **Blacklist** tab to see excluded words.
2. Add words that should never be treated as topics.
3. Changes save immediately to `semantic_map.json`.

**Via direct JSON edit:**
```json
{
  "mappings": {
    "#": "compaction",
    "$": "Libraric Layer",
    "Z": "your-new-topic"
  },
  "blacklist": ["and", "the", "your-noise-word"]
}
```

### Three-Level Index

Semantic information appears at three levels in the archive:

1. **Filename** — Which sessions contain a topic (glob for the character in filenames).
2. **Turn headers** — The `**Semantic Tags**` line in each turn header shows which topics appear in that turn.
3. **Paragraph markers** — `{chars}` markers between paragraphs show which topics appear in the surrounding text.

---

## 7. Understanding Audit Results

### Reading the Text Report

A text-format audit report looks like this (abbreviated):

```
=== COMPACTION AUDIT REPORT ===
Run 14 | 2026-02-19 00:22:00

--- File Paths (CRITICAL) ---
  [FOUND] F:\claude_tools\context_auditor.py
  [FOUND] F:\claude_tools\context_autoarchive.py
  File Paths: 9/9 (100%)

--- Tools Used (MAJOR) ---
  [FOUND] Read
  [FOUND] Bash
  Tools Used: 4/4 (100%)

--- Topics (MINOR) ---
  [FOUND] compaction
  [MISSING] Some Fabricated Topic
  Topics: 63/65 (97%)

Overall: 85/85 (100%)
Severity-weighted: 100%

Trend: 71% -> 71% -> 95% -> 74% -> 53% -> 64%
```

**Key elements:**
- Each claim shows its verification status: `[FOUND]`, `[DEEP]`, `[MISSING]`, or `[MISMATCH]`.
- Categories are grouped with their severity label.
- The overall rate counts all claims equally.
- The severity-weighted rate gives more weight to CRITICAL (4x) and MAJOR (3x) claims.
- The trend line shows accuracy across all historical compaction events.

### Reading the JSON Report

JSON output (`--format json`) provides structured data for programmatic analysis:

```json
{
  "summary": {
    "total": 85,
    "found": 85,
    "missing": 0,
    "mismatched": 0,
    "rate": 1.0,
    "severity_weighted_rate": 1.0
  },
  "categories": {
    "File Paths": { "total": 9, "found": 9, "rate": 1.0, "severity": "CRITICAL" }
  },
  "claims": [
    { "id": 1, "category": "File Paths", "claim": "context_auditor.py", "status": "FOUND", "severity": "CRITICAL", "location": "header" }
  ]
}
```

### What the Trend Line Means

The trend line tracks accuracy across successive compaction events:

```
71% -> 71% -> 95% -> 74% -> 53% -> 64% -> 57% -> 89% -> 64% -> 40% -> 46% -> 46% -> 100% -> 100%
```

- Higher is better.
- Drops often indicate discussion-heavy sessions (abstract content is harder to verify) or repeated compactions within the same session (progressive degradation).
- Spikes often indicate implementation-heavy sessions (concrete file paths, function names, tool usage are highly verifiable).

### What Regressions Look Like

A regression is flagged when accuracy drops more than 5 percentage points from the previous run. The report will show:

```
REGRESSION DETECTED: 64% -> 40% (-24pp)
```

### Known Patterns

- **Implementation sessions score higher**: Sessions with code changes produce concrete claims (file paths at 88-100%, tool names at 100%) that are easy to verify.
- **Discussion sessions score lower**: Planning and conversation produce abstract structural terms that the topic extractor picks up but can't verify against archive headers.
- **Ground truth injection**: The pre-phase feeds structured metadata into the compaction input. This both improves accuracy (the compactor has better data) and inflates the audit score (the compactor echoes back what was fed to it). Runs before ground truth injection (Runs 1-9, 53-95%) are truer measures of independent compaction accuracy.
- **Repeated compactions degrade**: Within the same session, accuracy drops with each successive compaction (observed: 95% to 74% to 53%).

---

## 8. The Archive Lifecycle

### Normal Run: Append

When the preserver runs, it finds the **active file** for each session (the highest enrichment version) and appends any new turns to it. Turns already in the file are not re-written.

### Compaction Boundary: Logical Splits

When a compaction occurs within a session, the same Claude Code session UUID continues but the context is fundamentally different (pre-compaction vs post-compaction). The preserver detects compaction summaries and splits the session into logical parts:

- `session_2026-02-17_1e4e3341.md` — Original (pre-first-compaction)
- `session_2026-02-17_1e4e3341_b.md` — After first compaction
- `session_2026-02-17_1e4e3341_c.md` — After second compaction
- `session_2026-02-17_1e4e3341_d.md` — After third compaction

### Enrichment: Format Versioning

The `--enrich` flag creates a new enrichment version when the preserver's formatting logic has changed:

- `.md` — Base version (enrichment version 0)
- `.enriched.md` — Version 1 (backward compatibility naming)
- `.enriched2.md` — Version 2
- `.enriched3.md` — Version 3, etc.

Each enriched file includes an `**Original**:` pointer to the base `.md` file. The preserver compares content before creating a new version — if nothing changed, the new version is skipped to prevent bloat.

### Deduplication

The `context_archive/duplicates/` directory holds identical enrichment versions that were created before the content-comparison fix. These are preserved (never deleted) but excluded from active search results.

### The Sacred Rule

**Data already written is never altered or removed.** This is the core integrity guarantee:

- Existing content in `.md` files is never modified.
- New turns are appended, never overwritten.
- Files are never deleted — only superseded by newer versions alongside the original.
- The `duplicates/` directory holds stale versions rather than deleting them.

---

## 9. Bundled Compaction Reports

Starting from Session 13, each compaction event produces a bundled JSON report containing everything about the compaction in one file.

### Report Format (v1)

Located in `context_archive/compaction_reports/compaction_report_YYYY-MM-DD_HHMMSS.json`:

```json
{
  "report_version": 1,
  "timestamp": "2026-02-19T00:22:00.000Z",
  "session_id": "20062c75-5285-4e7d-975a-d76a07c74da2__compact_1",
  "run_number": 14,
  "ground_truth": {
    "turn_count": 31,
    "session_id": "20062c75-...__compact_1",
    "duration": { "date": "2026-02-19", "start": "04:12:48", "end": "05:01:15" },
    "topics": "david, session, compaction, plan, phase",
    "files_referenced": ["context_auditor.py", "context_autoarchive.py", "..."],
    "tools_used": "Bash, Grep, Read",
    "archive_file": "session_2026-02-19_20062c75_b~#ABCFIJMNPSTUXYefpsuwy.md"
  },
  "compaction_summary": {
    "text": "This session is being continued from a previous conversation...",
    "length": 14496,
    "timestamp": "2026-02-19T04:14:11.039Z"
  },
  "audit": {
    "rate": 1.0,
    "severity_weighted_rate": 1.0,
    "categories": {
      "File Paths": { "total": 9, "found": 9, "rate": 1.0, "severity": "CRITICAL" },
      "Tools Used": { "total": 4, "found": 4, "rate": 1.0, "severity": "MAJOR" },
      "User Quotes": { "total": 7, "found": 7, "rate": 1.0, "severity": "MAJOR" },
      "Topics": { "total": 65, "found": 65, "rate": 1.0, "severity": "MINOR" },
      "Turn Counts": { "total": 0, "rate": 1.0, "severity": "INFO" },
      "Functions/Classes": { "total": 0, "rate": 1.0, "severity": "CRITICAL" }
    },
    "claims": [ "..." ],
    "regressions": []
  },
  "trend": [71, 71, 95, 74, 53, 64, 57, 89, 64, 40, 46, 46, 100, 100]
}
```

### How Reports Are Created

1. **Pre-phase** saves `ground_truth_pending.json` to `compaction_reports/`.
2. **Post-phase** reads the pending ground truth, runs the audit, and bundles everything into a timestamped report file. The pending file is consumed after bundling.

### Browsing Reports

- **Dashboard Reports tab**: Select a report from the list on the left. The detail viewer on the right shows 7 sections: Header, Trend, Regressions, Ground Truth, Compaction Summary, Audit by Category, and Cross-Reference.
- **Direct JSON**: Open `context_archive/compaction_reports/compaction_report_*.json` in any text editor or JSON viewer.
- **Legacy runs**: Runs before Session 13 don't have bundled reports. The dashboard falls back to `audit_history.jsonl` for these.

---

## 10. Troubleshooting

### Hook not firing

**Symptom**: No new entries in `audit_history.jsonl` after a compaction event.

**Check**:
1. Verify `settings.json` exists at `C:\Users\<user>\.claude\settings.json`.
2. Verify the structure matches Section 5 exactly — note the nested `hooks` arrays.
3. Verify Python is on your PATH: `python --version`.
4. Check that the tool path is correct: `python F:/claude_tools/context_autoarchive.py --help`.
5. For the post-phase specifically: the `"matcher": "compact"` on the SessionStart hook means it only fires after compaction, not on fresh session starts. This is correct behavior.

### Dashboard won't launch

**Symptom**: Error when running `python F:/claude_tools/bcp_dashboard.py`.

**Check**:
1. Verify tkinter is installed: `python -c "import tkinter"`.
2. On Linux: `sudo apt install python3-tk` (or equivalent for your distro).
3. On Windows: tkinter is included with the standard Python installer. If you used a minimal install, reinstall Python with the "tcl/tk" option checked.

### Preserver finds no transcripts

**Symptom**: `context_preserver.py` runs but reports 0 sessions.

**Check**:
1. Verify `--project-path` points to your project root.
2. The preserver looks for `.jsonl` files in `C:\Users\<user>\.claude\projects\<encoded-path>\`. The encoded path replaces `\` and `:` with `-` in the directory name.
3. Run Claude Code in the project at least once to generate a `.jsonl` file.

### Auditor returns 0 claims

**Symptom**: `context_auditor.py` runs but finds no claims to verify.

**Check**:
1. Verify the `.jsonl` file contains a compaction summary (a message with `isCompactSummary` set to `true`).
2. If the session has multiple compactions, use `--which 0` for the first or `--which -1` (default) for the last.
3. If using `--summary` with a text file, verify the file contains the actual summary text.

### Windows line endings

**Symptom**: Content comparison shows differences where none should exist.

**Note**: The preserver normalizes `\r\n` to `\n` in `format_turns_markdown()`. This was fixed in Session 7. If you encounter line-ending issues with very old archive files, running `--enrich` will create a new version with normalized line endings.

---

## 11. Adapting for a Different Project

BCP is designed to work with any Claude Code project, not just the Better Compaction Protocol itself.

### Pointing tools at a different project

All tools accept `--project-path` to specify the project root:

```bash
python F:/claude_tools/context_preserver.py --project-path F:/my_other_project
python F:/claude_tools/context_searcher.py search "query" --archive-path F:/my_other_project/context_archive
python F:/claude_tools/context_auditor.py transcript.jsonl --archive F:/my_other_project/context_archive
python F:/claude_tools/bcp_dashboard.py --project-path F:/my_other_project
```

### Archive auto-creation

The `context_archive/` directory is automatically created under `<project-path>/` when the preserver runs for the first time.

### Semantic map is global

`F:\claude_tools\semantic_map.json` is shared across all projects. Character mappings and the blacklist apply to every project the tools operate on. If you need project-specific semantic mappings, you would need to maintain separate copies (not currently supported as a built-in feature).

### Hook configuration for multiple projects

The hooks in `settings.json` currently fire for all Claude Code sessions. If you want hooks to target a specific project, add the `--project-path` flag to the hook commands:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python F:/claude_tools/context_autoarchive.py --phase pre --project-path F:/my_project",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

Without `--project-path`, the autoarchive reads project path metadata from the hook's stdin JSON (provided by Claude Code) or falls back to the current working directory.

---

**Created**: February 19, 2026
**Tools location**: `F:\claude_tools\`
**Project location**: `F:\Better_Compaction_Protocol\`
