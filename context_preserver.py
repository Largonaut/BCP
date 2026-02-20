#!/usr/bin/env python3
"""
context_preserver.py - Preserves Claude Code conversation transcripts as human-readable Markdown.

Part of the Better Compaction Protocol. Instead of lossy narrative summarization,
this tool treats context as environment (per Libraric Layer / MIT RLM paradigms)
by preserving the full conversation as navigable, searchable .md files.

Location: F:\claude_tools\context_preserver.py
Usage:
    python F:/claude_tools/context_preserver.py
    python F:/claude_tools/context_preserver.py --session <id>
    python F:/claude_tools/context_preserver.py --project-path F:/some/project
    python F:/claude_tools/context_preserver.py --enrich
    python F:/claude_tools/context_preserver.py --dry-run
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Claude Code stores projects under this base with path-encoded directory names
CLAUDE_PROJECTS_BASE = Path(os.path.expanduser("~")) / ".claude" / "projects"

# Compaction summary marker text (fallback when isCompactSummary flag is absent)
COMPACTION_MARKER = "This session is being continued from a previous conversation"

# Semantic filename support
SEMANTIC_SEPARATOR = "~"
SEMANTIC_MAP_PATH = Path(__file__).parent / "semantic_map.json"
# Characters forbidden in Windows filenames + reserved separator + whitespace
SEMANTIC_EXCLUDED = set('\\/:"*?<>|' + SEMANTIC_SEPARATOR) | set(' \t\n\r')

# Stop words for topic extraction
STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'need',
    'that', 'this', 'these', 'those', 'i', 'you', 'he', 'she', 'it',
    'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his',
    'its', 'our', 'their', 'what', 'which', 'who', 'whom', 'when', 'where',
    'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
    'other', 'some', 'such', 'no', 'not', 'only', 'own', 'same', 'so',
    'than', 'too', 'very', 'just', 'because', 'if', 'then', 'else', 'also',
    'about', 'up', 'out', 'into', 'over', 'after', 'before', 'between',
    'under', 'again', 'further', 'once', 'here', 'there', 'any', 'much',
    'many', 'well', 'back', 'even', 'still', 'already', 'now', 'let',
    'make', 'like', 'think', 'want', 'get', 'go', 'see', 'know', 'take',
    'come', 'look', 'use', 'find', 'give', 'tell', 'say', 'try', 'ask',
    'work', 'call', 'keep', 'put', 'run', 'move', 'going', 'really',
    'thing', 'things', 'something', 'anything', 'nothing', 'way', 'one',
    'two', 'first', 'new', 'good', 'long', 'great', 'little', 'right',
    'old', 'big', 'high', 'different', 'small', 'large', 'next', 'don',
    'doesn', 'didn', 'won', 'wouldn', 'couldn', 'shouldn', 'isn', 'aren',
    'wasn', 'weren', 'hasn', 'haven', 'hadn', 'yes', 'ok', 'okay', 'yeah',
    'hey', 'hi', 'hello', 'sure', 'got', 'done', 'using', 'used',
}


def encode_project_path(project_path: str) -> str:
    """Convert a filesystem path to Claude's project directory encoding.
    e.g. 'F:\\Better_Compaction_Protocol' -> 'f--Better-Compaction-Protocol'
    """
    p = project_path.replace("\\", "/").rstrip("/")
    # Drive letter: 'F:' -> 'f-'
    if len(p) >= 2 and p[1] == ":":
        p = p[0].lower() + "-" + p[2:]
    # Forward slashes become '-'
    p = p.replace("/", "-")
    # Underscores become '-'
    p = p.replace("_", "-")
    return p


def find_project_dir(project_path: str) -> Path:
    """Find the Claude projects directory for a given workspace path."""
    encoded = encode_project_path(project_path)
    candidate = CLAUDE_PROJECTS_BASE / encoded
    if candidate.is_dir():
        return candidate
    # Fallback: scan for partial match
    if CLAUDE_PROJECTS_BASE.is_dir():
        for d in CLAUDE_PROJECTS_BASE.iterdir():
            if d.is_dir() and encoded in d.name:
                return d
    raise FileNotFoundError(
        f"No Claude project directory found for '{project_path}'\n"
        f"Looked for: {candidate}\n"
        f"Available: {[d.name for d in CLAUDE_PROJECTS_BASE.iterdir() if d.is_dir()] if CLAUDE_PROJECTS_BASE.is_dir() else 'none'}"
    )


def parse_jsonl_file(filepath: Path):
    """Stream-parse a .jsonl file, yielding parsed JSON objects."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # Skip malformed lines


def extract_text_content(content_blocks) -> str:
    """Extract text from Claude's content block format."""
    if isinstance(content_blocks, str):
        return content_blocks
    if isinstance(content_blocks, list):
        parts = []
        for block in content_blocks:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content_blocks)


def extract_thinking_content(content_blocks) -> str:
    """Extract thinking blocks from Claude's content format."""
    if not isinstance(content_blocks, list):
        return ""
    parts = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "thinking":
            parts.append(block.get("thinking", ""))
    return "\n".join(parts)


def extract_tool_uses(content_blocks) -> list:
    """Extract tool use info from content blocks (formatted strings)."""
    if not isinstance(content_blocks, list):
        return []
    tools = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tools.append(f"**Tool**: `{block.get('name', 'unknown')}` | Input: `{str(block.get('input', ''))[:200]}...`")
    return tools


def extract_tool_names(content_blocks) -> list:
    """Extract just the tool names from content blocks."""
    if not isinstance(content_blocks, list):
        return []
    names = []
    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            name = block.get("name", "")
            if name:
                names.append(name)
    return names


def extract_file_paths(text: str) -> list:
    """Extract file paths mentioned in text."""
    patterns = [
        r'[A-Za-z]:[/\\][\w./\\-]+',           # Windows: F:\foo\bar or F:/foo/bar
        r'(?<!\w)/(?:[\w.-]+/)+[\w.-]+',         # Unix: /foo/bar/baz.py
    ]
    paths = set()
    for pattern in patterns:
        for match in re.findall(pattern, text):
            if len(match) > 5:
                paths.add(match.rstrip('/\\'))
    return sorted(paths)


def extract_topics(turns: list, max_topics: int = 10) -> list:
    """Extract topic keywords from user messages using heuristic frequency analysis."""
    user_text = " ".join(t["text"] for t in turns if t["type"] == "user")
    if not user_text.strip():
        return []

    topic_scores = {}

    # Multi-word capitalized phrases (e.g., "Libraric Layer", "Better Compaction Protocol")
    for phrase in re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', user_text):
        phrase = phrase.strip()
        if len(phrase) > 3:
            topic_scores[phrase] = topic_scores.get(phrase, 0) + 5

    # ALL-CAPS acronyms (e.g., "DDSMRLV", "MIT", "RLM")
    for acr in re.findall(r'\b([A-Z]{2,})\b', user_text):
        if acr not in {'OK', 'ID', 'VS', 'IE', 'EG'}:
            topic_scores[acr] = topic_scores.get(acr, 0) + 3

    # Single significant words by frequency
    words = re.findall(r'\b([a-zA-Z]{3,})\b', user_text.lower())
    word_freq = Counter(w for w in words if w not in STOP_WORDS)
    for word, count in word_freq.items():
        if count >= 2:
            topic_scores[word] = topic_scores.get(word, 0) + count

    sorted_topics = sorted(topic_scores.items(), key=lambda x: (-x[1], x[0]))
    return [t[0] for t in sorted_topics[:max_topics]]


def generate_summary(turns: list) -> str:
    """Generate a one-line summary from the first substantive user message."""
    for turn in turns:
        if turn["type"] != "user":
            continue
        text = turn["text"].strip()
        # Skip IDE open events and very short messages
        lines = [l for l in text.split('\n') if not l.strip().startswith('<ide_') and l.strip()]
        text = ' '.join(lines).strip()
        if len(text) < 15:
            continue
        # Take first sentence or first 120 chars
        for i, ch in enumerate(text):
            if ch in '.!?\n' and i > 15:
                return text[:i + 1].strip()
        return (text[:120].strip() + "...") if len(text) > 120 else text
    return "(no summary available)"


def collect_session_enrichment(turns: list) -> dict:
    """Extract enrichment metadata from a session's turns."""
    topics = extract_topics(turns)
    summary = generate_summary(turns)

    tool_names = set()
    for t in turns:
        for name in t.get("tool_names", []):
            tool_names.add(name)

    all_text = " ".join(t["text"] for t in turns)
    file_paths = extract_file_paths(all_text)

    return {
        "topics": topics,
        "summary": summary,
        "tools_used": sorted(tool_names),
        "files_referenced": file_paths[:20],
    }


def parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    # Handle various formats Claude might use
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def collect_turns(project_dir: Path, session_filter: str = None) -> dict:
    """Collect all conversation turns from .jsonl files, grouped by logical session.

    Detects compaction boundaries (isCompactSummary flag or marker text) within
    the same sessionId and splits them into separate logical sessions with
    __compact_N suffixes in the key.
    """
    sessions = {}  # logical_id -> list of turn dicts
    compaction_counts = {}  # session_id -> number of compactions seen

    jsonl_files = sorted(project_dir.glob("*.jsonl"))
    if not jsonl_files:
        print(f"No .jsonl files found in {project_dir}")
        return sessions

    for jf in jsonl_files:
        for entry in parse_jsonl_file(jf):
            entry_type = entry.get("type", "")
            if entry_type not in ("user", "assistant"):
                continue

            msg = entry.get("message", {})
            content_blocks = msg.get("content", "")
            timestamp = entry.get("timestamp", "")
            session_id = entry.get("sessionId", "unknown")

            if session_filter and session_id != session_filter:
                continue

            # Detect compaction boundary (before processing turn content)
            is_compaction = entry.get("isCompactSummary", False)
            if not is_compaction and entry_type == "user":
                raw_content = msg.get("content", "")
                if isinstance(raw_content, str) and raw_content[:200].startswith(COMPACTION_MARKER):
                    is_compaction = True

            if is_compaction:
                if session_id not in compaction_counts:
                    compaction_counts[session_id] = 0
                compaction_counts[session_id] += 1

            # Build logical session key
            suffix_num = compaction_counts.get(session_id, 0)
            logical_id = session_id if suffix_num == 0 else f"{session_id}__compact_{suffix_num}"

            text = extract_text_content(content_blocks)
            tool_names = extract_tool_names(content_blocks) if entry_type == "assistant" else []

            if not text.strip():
                # Check if it's an assistant turn with only tool use
                tool_uses = extract_tool_uses(content_blocks)
                if not tool_uses:
                    continue
                text = "\n".join(tool_uses)

            thinking = ""
            if entry_type == "assistant":
                thinking = extract_thinking_content(content_blocks)

            turn = {
                "type": entry_type,
                "timestamp": timestamp,
                "text": text,
                "thinking": thinking,
                "model": msg.get("model", ""),
                "source_file": jf.name,
                "tool_names": tool_names,
            }

            if logical_id not in sessions:
                sessions[logical_id] = []
            sessions[logical_id].append(turn)

    # Sort turns within each session by timestamp
    for sid in sessions:
        sessions[sid].sort(key=lambda t: parse_timestamp(t["timestamp"]))

    return sessions


def format_turns_markdown(turns: list, start_number: int = 1,
                          semantic_mappings: dict = None) -> str:
    """Format turns as Markdown. start_number controls turn numbering.

    Extracted so both full-session formatting and append-only use the same logic.
    """
    lines = []
    for i, turn in enumerate(turns, start_number):
        role = "User" if turn["type"] == "user" else "Claude"
        ts = turn["timestamp"]
        time_str = ts[11:19] if len(ts) >= 19 else ""
        text = turn["text"]

        # Normalize line endings (Windows \r\n from .jsonl source text)
        # Without this, \r\n double-expands when written to file on Windows,
        # causing content comparison mismatches on subsequent reads.
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        if semantic_mappings:
            # Split into paragraphs, scan each, insert markers between them
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            para_tags = [scan_text_for_semantics(p, semantic_mappings) for p in paragraphs]

            # Turn header gets union of all paragraph tags
            all_chars = set()
            for tag in para_tags:
                all_chars.update(tag)
            turn_tag = "".join(sorted(all_chars, key=ord))

            if turn_tag:
                lines.append(f"## Turn {i} — {role} [{time_str}] {{{turn_tag}}}")
            else:
                lines.append(f"## Turn {i} — {role} [{time_str}]")
            lines.append("")

            for j, (para, tag) in enumerate(zip(paragraphs, para_tags)):
                lines.append(para)
                lines.append("")
                if tag:
                    lines.append(f"{{{tag}}}")
                    lines.append("")
        else:
            # No semantic mappings — plain output
            lines.append(f"## Turn {i} — {role} [{time_str}]")
            lines.append("")
            lines.append(text)
            lines.append("")

        # Thinking blocks in collapsed details
        if turn["thinking"]:
            lines.append("<details><summary>Thinking</summary>")
            lines.append("")
            lines.append(turn["thinking"])
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def format_session_markdown(session_id: str, turns: list, project_name: str,
                            enrichment: dict = None, original_file: str = None,
                            semantic_tag: str = "", semantic_mappings: dict = None) -> str:
    """Format a session's turns as Markdown with optional enrichment metadata."""
    lines = []

    # Header
    first_ts = turns[0]["timestamp"] if turns else ""
    date_str = first_ts[:10] if len(first_ts) >= 10 else "unknown-date"
    lines.append(f"# Session: {date_str} | {project_name}")
    lines.append(f"")
    lines.append(f"**Session ID**: `{session_id}`  ")
    lines.append(f"**Turns**: {len(turns)}  ")
    if turns and turns[0].get("model"):
        lines.append(f"**Model**: `{turns[0]['model']}`  ")
    lines.append(f"**Archived**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")

    # Enrichment metadata
    if enrichment:
        if enrichment.get("summary"):
            lines.append(f"**Summary**: {enrichment['summary']}  ")
        if enrichment.get("topics"):
            lines.append(f"**Topics**: {', '.join(enrichment['topics'])}  ")
        if enrichment.get("tools_used"):
            lines.append(f"**Tools Used**: {', '.join(enrichment['tools_used'])}  ")
        if enrichment.get("files_referenced"):
            refs = enrichment["files_referenced"][:10]
            lines.append(f"**Files Referenced**: {', '.join(refs)}  ")
    # Semantic tags (self-documenting monitor in the header)
    if semantic_tag and semantic_mappings:
        lines.append(format_semantic_header(semantic_tag, semantic_mappings))
    if original_file:
        lines.append(f"**Original**: [{original_file}]({original_file})  ")

    lines.append(f"")
    lines.append("---")
    lines.append("")

    # Turn content (delegated to shared formatter)
    lines.append(format_turns_markdown(turns, start_number=1,
                                       semantic_mappings=semantic_mappings))

    return "\n".join(lines)


def get_archived_turn_count(filepath: Path) -> int:
    """Count the number of ## Turn headers in an existing .md file.

    More robust than reading **Turns**: N from the header, because
    the header count may not reflect appended turns.
    """
    count = 0
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if re.match(r'^## Turn \d+ ', line):
                    count += 1
    except (OSError, UnicodeDecodeError):
        pass
    return count


def find_active_file(existing_all: list) -> Path:
    """Find the file with the highest enrichment version (the active save target).

    This is the file that new turns should be appended to.
    """
    if not existing_all:
        return None
    return max(existing_all, key=lambda f: get_enrichment_version(f.name))


def format_index_markdown(sessions_meta: list, project_name: str) -> str:
    """Format the index file listing all archived sessions."""
    lines = []
    lines.append(f"# Context Archive: {project_name}")
    lines.append(f"")
    lines.append(f"**Updated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**Sessions**: {len(sessions_meta)}  ")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("| Date | Turns | Topics | Summary | File |")
    lines.append("|------|-------|--------|---------|------|")

    for meta in sorted(sessions_meta, key=lambda m: m["date"], reverse=True):
        topics = meta.get("topics_str", "")
        summary = meta.get("summary", "")[:60].replace("|", "\\|").replace("\n", " ")
        link_file = meta.get("link_file", meta["filename"])
        lines.append(
            f"| {meta['date']} | {meta['turns']} | {topics} | {summary} | "
            f"[{link_file}]({link_file}) |"
        )

    lines.append("")
    return "\n".join(lines)


def load_semantic_map(map_path: Path = None) -> dict:
    """Load the global semantic mapping table. Returns {char: topic} dict."""
    path = map_path or SEMANTIC_MAP_PATH
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("mappings", {})
    except (json.JSONDecodeError, OSError):
        return {}


def build_semantic_tag(topics: list, mappings: dict) -> str:
    """Build a semantic tag string from extracted topics and the mapping table.

    Matches topics to mapping values via case-insensitive substring matching.
    Returns characters sorted by codepoint for canonical ordering.
    """
    if not mappings or not topics:
        return ""

    # Invert: topic_lower_fragment -> char
    matched_chars = set()
    for topic in topics:
        topic_lower = topic.lower()
        for char, mapped_topic in mappings.items():
            if mapped_topic.lower() in topic_lower or topic_lower in mapped_topic.lower():
                matched_chars.add(char)

    if not matched_chars:
        return ""

    # Canonical order: sorted by codepoint
    return "".join(sorted(matched_chars, key=ord))


def scan_text_for_semantics(text: str, mappings: dict) -> str:
    """Scan full text against the semantic map with threshold=1.

    Instead of relying on extract_topics() frequency thresholds, this scans
    the raw session text for every mapped topic. If a mapped topic appears
    anywhere in the text (case-insensitive, word-boundary matched), it's tagged.

    Uses \\b word boundaries to prevent false positives from substring matches
    (e.g., "IDE" won't match inside "provide", "MIT" won't match inside "commit").

    Returns matched characters sorted by codepoint for canonical ordering.
    """
    if not mappings or not text:
        return ""
    text_lower = text.lower()
    matched_chars = set()
    for char, topic in mappings.items():
        pattern = r'\b' + re.escape(topic.lower()) + r'\b'
        if re.search(pattern, text_lower):
            matched_chars.add(char)
    if not matched_chars:
        return ""
    return "".join(sorted(matched_chars, key=ord))


def format_semantic_header(tag: str, mappings: dict) -> str:
    """Format the semantic tag line for .md file headers."""
    if not tag:
        return ""
    parts = []
    for char in tag:
        topic = mappings.get(char, "?")
        parts.append(f"{char} ({topic})")
    return f"**Semantic Tags**: {', '.join(parts)}  "


def get_enrichment_version(filename: str) -> int:
    """Extract enrichment version number from filename.

    .md = 0 (not enriched), .enriched.md = 1, .enriched2.md = 2, etc.
    Backward compatible: unnumbered .enriched.md is implicitly v1.
    """
    if ".enriched" not in filename:
        return 0
    m = re.search(r'\.enriched(\d*)\.md$', filename)
    if not m:
        return 0
    return int(m.group(1)) if m.group(1) else 1


def session_filename(session_id: str, first_timestamp: str, semantic_tag: str = "") -> str:
    """Generate a filename for a session archive.

    Handles logical session suffixes from compaction splitting:
    __compact_1 -> _b, __compact_2 -> _c, etc.
    """
    date_str = first_timestamp[:10] if len(first_timestamp) >= 10 else "unknown"

    # Handle logical session suffixes from compaction splitting
    suffix = ""
    if "__compact_" in session_id:
        parts = session_id.rsplit("__compact_", 1)
        session_id = parts[0]
        n = int(parts[1])
        suffix = "_" + chr(ord('a') + n)  # 1->_b, 2->_c, 3->_d

    # Use first 8 chars of session ID for uniqueness
    short_id = session_id[:8] if session_id != "unknown" else "nosession"
    # Sanitize the identity portion (session ID part only)
    safe = re.sub(r'[^\w\-]', '_', f"session_{date_str}_{short_id}")
    # Semantic tag appended raw (already validated Unicode, not sanitized)
    tag_part = f"{SEMANTIC_SEPARATOR}{semantic_tag}" if semantic_tag else ""
    return safe + suffix + tag_part + ".md"


def is_legacy_file(filepath: Path) -> bool:
    """Check if an existing session file lacks enrichment metadata."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            header = f.read(2000)
        return "**Topics**:" not in header
    except (OSError, UnicodeDecodeError):
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Preserve Claude Code conversations as human-readable Markdown"
    )
    parser.add_argument(
        "--project-path",
        default=None,
        help="Workspace path (default: current directory)"
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Only archive a specific session ID"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: <project>/context_archive/)"
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Create .enriched.md copies of legacy session files with richer metadata"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing"
    )
    args = parser.parse_args()

    # Resolve project path
    project_path = args.project_path or os.getcwd()
    project_path = os.path.abspath(project_path)
    project_name = os.path.basename(project_path)

    print(f"Project: {project_path}")
    print(f"Project name: {project_name}")

    # Find Claude's project directory
    try:
        project_dir = find_project_dir(project_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Transcript source: {project_dir}")

    # Collect turns
    sessions = collect_turns(project_dir, session_filter=args.session)
    if not sessions:
        print("No conversation turns found.")
        sys.exit(0)

    print(f"Found {len(sessions)} session(s), {sum(len(t) for t in sessions.values())} total turns")

    # Output directory
    output_dir = Path(args.output) if args.output else Path(project_path) / "context_archive"

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    # Load semantic mapping table
    semantic_mappings = load_semantic_map()
    if semantic_mappings:
        print(f"Semantic map loaded: {len(semantic_mappings)} mappings from {SEMANTIC_MAP_PATH}")
    else:
        print(f"No semantic map found at {SEMANTIC_MAP_PATH} (filenames will have no semantic tags)")

    # Process each session
    sessions_meta = []
    files_written = 0
    all_unmapped = set()

    for sid, turns in sessions.items():
        if not turns:
            continue

        # Generate enrichment metadata
        enrichment = collect_session_enrichment(turns)

        # Build semantic tag by scanning full session text against the map (threshold=1)
        all_session_text = " ".join(t["text"] for t in turns)
        semantic_tag = scan_text_for_semantics(all_session_text, semantic_mappings)
        topics = enrichment.get("topics", [])

        # Track unmapped topics
        if semantic_mappings and topics:
            mapped_topics = set()
            for t in topics:
                t_lower = t.lower()
                for char, mt in semantic_mappings.items():
                    if mt.lower() in t_lower or t_lower in mt.lower():
                        mapped_topics.add(t)
                        break
            unmapped = set(topics) - mapped_topics
            all_unmapped.update(unmapped)

        # Build filenames: identity (no tag) for matching, full (with tag) for creation
        identity_base = session_filename(sid, turns[0]["timestamp"], "").replace(".md", "")
        fname = session_filename(sid, turns[0]["timestamp"], semantic_tag)
        out_path = output_dir / fname
        topics_str = ", ".join(enrichment["topics"][:5])

        # Identity-based matching: find any existing files for this session
        # Glob for exact identity match (with or without semantic tag), avoiding
        # false matches on compaction suffixes (e.g., _b, _c)
        # The enriched* glob catches .enriched.md, .enriched2.md, .enriched3.md, etc.
        if output_dir.exists():
            existing_all = (list(output_dir.glob(f"{identity_base}.md")) +
                            list(output_dir.glob(f"{identity_base}~*.md")) +
                            list(output_dir.glob(f"{identity_base}.enriched*.md")) +
                            list(output_dir.glob(f"{identity_base}~*.enriched*.md")))
        else:
            existing_all = []
        existing_base = [f for f in existing_all if get_enrichment_version(f.name) == 0]

        # First user message for index
        first_user = next((t["text"] for t in turns if t["type"] == "user"), "(no user message)")

        if args.enrich:
            # --enrich mode: version-aware enrichment
            # Find highest existing enrichment version across all files for this identity
            max_version = 0
            for ef in existing_all:
                v = get_enrichment_version(ef.name)
                if v > max_version:
                    max_version = v

            # Find the original base file (for the Original: header pointer)
            original_file = None
            for ef in existing_all:
                if get_enrichment_version(ef.name) == 0:
                    original_file = ef
                    break

            if existing_all:
                # Files exist — only create new enriched version if content differs
                original_ref = original_file.name if original_file else existing_all[0].name
                md_content = format_session_markdown(
                    sid, turns, project_name,
                    enrichment=enrichment, original_file=original_ref,
                    semantic_tag=semantic_tag, semantic_mappings=semantic_mappings
                )

                # Compare with latest existing file (strip **Archived** line which always changes)
                latest_file = find_active_file(existing_all)
                content_matches = False
                if latest_file:
                    try:
                        with open(latest_file, "r", encoding="utf-8") as f:
                            existing_content = f.read()
                        # Strip the **Archived** timestamp line from both for comparison
                        strip_re = re.compile(r'\*\*Archived\*\*:.*?\n')
                        new_stripped = strip_re.sub('', md_content)
                        old_stripped = strip_re.sub('', existing_content)
                        # Also strip <!-- Appended ... --> comments (append metadata)
                        append_re = re.compile(r'<!-- Appended .+?-->\n*')
                        new_stripped = append_re.sub('', new_stripped)
                        old_stripped = append_re.sub('', old_stripped)
                        # Normalize line endings (Windows \r\n vs Unix \n)
                        new_stripped = new_stripped.replace('\r\n', '\n')
                        old_stripped = old_stripped.replace('\r\n', '\n')
                        content_matches = (new_stripped.strip() == old_stripped.strip())
                    except (OSError, UnicodeDecodeError):
                        pass

                if content_matches:
                    print(f"  Skipped (content unchanged): {latest_file.name}")
                    link_file = latest_file.name
                else:
                    next_version = max_version + 1
                    version_suffix = "" if next_version == 1 else str(next_version)
                    next_fname = fname.replace(".md", f".enriched{version_suffix}.md")
                    next_path = output_dir / next_fname

                    if next_path.exists():
                        print(f"  Skipped (enriched v{next_version} exists): {next_fname}")
                        link_file = next_fname
                    elif args.dry_run:
                        print(f"  [DRY RUN] Would create enriched v{next_version}: {next_path}")
                        link_file = next_fname
                    else:
                        with open(next_path, "w", encoding="utf-8") as f:
                            f.write(md_content)
                        files_written += 1
                        print(f"  Created enriched v{next_version}: {next_path}")
                        link_file = next_fname
            else:
                # No archive exists yet — create born-enriched base file
                md_content = format_session_markdown(
                    sid, turns, project_name, enrichment=enrichment,
                    semantic_tag=semantic_tag, semantic_mappings=semantic_mappings
                )
                if args.dry_run:
                    print(f"  [DRY RUN] Would write (born enriched): {out_path}")
                else:
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    files_written += 1
                    print(f"  Wrote (born enriched): {out_path}")
                link_file = fname
        else:
            # Normal run: create new file OR append new turns to existing file
            if existing_all:
                # Find the active file (highest enrichment version)
                active = find_active_file(existing_all)
                archived_count = get_archived_turn_count(active)
                current_count = len(turns)

                if current_count > archived_count:
                    # New turns to append
                    new_turns = turns[archived_count:]
                    append_text = format_turns_markdown(
                        new_turns, start_number=archived_count + 1,
                        semantic_mappings=semantic_mappings
                    )
                    append_block = (
                        f"\n<!-- Appended {len(new_turns)} turns at "
                        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                        f"(was {archived_count}, now {current_count}) -->\n\n"
                        + append_text
                    )
                    if args.dry_run:
                        print(f"  [DRY RUN] Would append {len(new_turns)} turns to: {active.name}")
                    else:
                        with open(active, "a", encoding="utf-8") as f:
                            f.write(append_block)
                        files_written += 1
                        print(f"  Appended {len(new_turns)} turns to: {active.name} ({archived_count} -> {current_count})")
                    link_file = active.name
                else:
                    print(f"  Up to date ({archived_count} turns): {active.name}")
                    link_file = active.name
            else:
                # No files exist — create new base file
                md_content = format_session_markdown(
                    sid, turns, project_name, enrichment=enrichment,
                    semantic_tag=semantic_tag, semantic_mappings=semantic_mappings
                )

                if args.dry_run:
                    print(f"  [DRY RUN] Would write: {out_path} ({len(turns)} turns, {len(md_content)} chars)")
                else:
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(md_content)
                    files_written += 1
                    print(f"  Wrote: {out_path} ({len(turns)} turns)")
                link_file = fname

        sessions_meta.append({
            "session_id": sid,
            "date": turns[0]["timestamp"][:10] if turns[0]["timestamp"] else "unknown",
            "turns": len(turns),
            "first_message": first_user,
            "filename": fname,
            "link_file": link_file,
            "topics_str": topics_str,
            "summary": enrichment.get("summary", ""),
        })

    # Write index
    index_content = format_index_markdown(sessions_meta, project_name)
    index_path = output_dir / "index.md"
    if args.dry_run:
        print(f"  [DRY RUN] Would write: {index_path}")
    else:
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_content)
        files_written += 1
        print(f"  Wrote: {index_path}")

    print(f"\nDone. {files_written} file(s) written to {output_dir}")

    # Report unmapped topics
    if all_unmapped:
        print(f"\nUnmapped topics ({len(all_unmapped)}):")
        for topic in sorted(all_unmapped, key=str.lower):
            print(f"  Unmapped topic: {topic}")
        print(f"Add mappings in {SEMANTIC_MAP_PATH} to include these in semantic tags.")


if __name__ == "__main__":
    main()
