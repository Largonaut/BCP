#!/usr/bin/env python3
"""context_auditor.py - Compaction Summary Auditor (Tool #3)

Extracts verifiable claims from Claude Code compaction summaries and
checks them against archived session .md files.

Part of the Better Compaction Protocol.

Usage:
    python context_auditor.py <jsonl_path> [--archive <dir>] [--which N]
    python context_auditor.py --summary <file> --archive <dir>
    python context_auditor.py <jsonl_path> --format json   # structured JSON output

Examples:
    python context_auditor.py transcript.jsonl
    python context_auditor.py transcript.jsonl --which 0   # audit first compaction
    python context_auditor.py --summary pasted.txt --archive ./context_archive
"""

import json
import re
import sys
import io
import os
import argparse
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone


# ============================================================
# SEVERITY LEVELS
# ============================================================

# Category -> severity. CRITICAL = data loss indicators, MAJOR = workflow accuracy,
# MINOR = vocabulary drift, INFO = known structural flaws
CATEGORY_SEVERITY = {
    'File Paths': 'CRITICAL',
    'Functions/Classes': 'CRITICAL',
    'Tools Used': 'MAJOR',
    'User Quotes': 'MAJOR',
    'Topics': 'MINOR',
    'Turn Counts': 'INFO',
}

SEVERITY_WEIGHT = {
    'CRITICAL': 4,
    'MAJOR': 3,
    'MINOR': 2,
    'INFO': 1,
}

# Force UTF-8 on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ============================================================
# COMPACTION SUMMARY EXTRACTION
# ============================================================

COMPACTION_MARKER = "This session is being continued from a previous conversation"


def find_compaction_summaries(jsonl_path):
    """Find all compaction summary messages in a .jsonl transcript.

    Returns list of dicts: {'text', 'timestamp', 'session_id', 'line'}
    """
    summaries = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            # Fast pre-check before parsing JSON
            if 'isCompactSummary' not in line and COMPACTION_MARKER not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Primary detection: explicit flag
            is_compact = entry.get('isCompactSummary', False)

            # Fallback detection: marker text in user message
            if not is_compact:
                msg = entry.get('message', {})
                content = msg.get('content', '')
                if isinstance(content, str) and COMPACTION_MARKER in content[:200]:
                    is_compact = True

            if is_compact:
                msg = entry.get('message', {})
                content = msg.get('content', '')
                # Handle content-blocks format (list of dicts)
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            parts.append(block.get('text', ''))
                        elif isinstance(block, str):
                            parts.append(block)
                    content = '\n'.join(parts)
                summaries.append({
                    'text': content,
                    'timestamp': entry.get('timestamp', ''),
                    'session_id': entry.get('sessionId', ''),
                    'line': lineno,
                })
    return summaries


def read_summary_file(filepath):
    """Read a compaction summary from a plain text file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================
# CLAIM EXTRACTION
# ============================================================

def strip_code_blocks(text):
    """Remove fenced code blocks (```...```) to avoid false matches."""
    return re.sub(r'```[\s\S]*?```', '', text)


def extract_file_claims(text):
    """Extract file paths mentioned in the compaction summary."""
    patterns = [
        r'[A-Za-z]:[/\\][\w./\\-]+',              # Windows: C:\foo\bar.py
        r'(?<!\w)/(?:[\w.-]+/)+[\w.-]+',            # Unix: /foo/bar/baz.py
    ]
    paths = set()
    for pattern in patterns:
        for match in re.findall(pattern, text):
            cleaned = match.rstrip('/\\).,:;')
            if len(cleaned) > 5:
                paths.add(cleaned)
    return sorted(paths)


def extract_tool_claims(text):
    """Extract Claude Code tool names mentioned in the summary."""
    known_tools = {
        'Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'Task',
        'TodoWrite', 'AskUserQuestion', 'ExitPlanMode', 'EnterPlanMode',
        'WebFetch', 'WebSearch', 'NotebookEdit', 'Skill',
    }
    found = set()
    for tool in known_tools:
        if re.search(r'\b' + re.escape(tool) + r'\b', text):
            found.add(tool)
    return sorted(found)


def extract_user_quotes(text):
    """Extract quoted user messages from the summary.

    Focuses on the 'All User Messages' section if present, strips code blocks,
    and handles both smart quotes and straight quotes.
    """
    # Try to isolate the "All User Messages" section first
    target = text
    um_match = re.search(r'All User Messages[:\s]*\n', text, re.IGNORECASE)
    if um_match:
        start = um_match.end()
        # Find next numbered section header
        next_section = re.search(r'^\s*\d+\.\s+[A-Z]', text[start:], re.MULTILINE)
        end = start + next_section.start() if next_section else len(text)
        target = text[start:end]

    # Strip code blocks to avoid false matches
    target = strip_code_blocks(target)

    quotes = []
    # Smart quotes
    for match in re.finditer(r'\u201c([^\u201d]{8,})\u201d', target):
        quotes.append(match.group(1))
    # Straight quotes
    for match in re.finditer(r'"([^"]{8,})"', target):
        q = match.group(1)
        # Skip code-like strings
        if q.startswith('{') or q.startswith('[') or '\\n' in q:
            continue
        # Skip strings that look like paths or code
        if re.match(r'^[\w./\\:]+$', q):
            continue
        quotes.append(q)

    # Deduplicate by prefix
    seen = set()
    unique = []
    for q in quotes:
        key = q[:40].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def _load_blacklist(archive_dir=None):
    """Load user-managed blacklist from semantic_map.json if available."""
    blacklist = set()
    # Try semantic_map.json in the tools directory (sibling to this file)
    tools_dir = Path(__file__).resolve().parent
    map_path = tools_dir / 'semantic_map.json'
    if map_path.exists():
        try:
            with open(map_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for word in data.get('blacklist', []):
                blacklist.add(word.upper())
        except (json.JSONDecodeError, OSError):
            pass
    return blacklist


def _is_formatting_artifact(text):
    """Return True if text is a formatting artifact, not a real topic."""
    # Contains newlines or carriage returns
    if '\n' in text or '\r' in text:
        return True
    # Mostly punctuation/whitespace (less than 50% alphanumeric)
    alnum = sum(1 for c in text if c.isalnum())
    if len(text) > 0 and alnum / len(text) < 0.5:
        return True
    # Starts with punctuation or markdown artifacts
    if text and text[0] in ':-()[]{}|>':
        return True
    return False


def extract_topic_claims(text):
    """Extract key topic terms from the summary.

    Strips code blocks and filters out section headers, status labels,
    formatting artifacts, and blacklisted English words.
    """
    cleaned = strip_code_blocks(text)
    topics = set()
    user_blacklist = _load_blacklist()

    # Section headers to skip (these are summary structure, not topic claims)
    section_headers = {
        'primary request and intent', 'key technical concepts',
        'files and code sections', 'errors and fixes', 'problem solving',
        'all user messages', 'pending tasks', 'current work',
        'optional next step', 'analysis', 'summary',
    }

    # Status/label words to skip
    skip_labels = {
        'NOTE', 'CRITICAL', 'IMPORTANT', 'SOLVED', 'NOT FIXED', 'ONGOING',
        'MODIFIED', 'CREATED', 'READ', 'GENERATED', 'BUG', 'COMPLETE',
        'WHAT', 'WHY', 'HOW', 'FIX', 'ERROR', 'FIXED', 'DEFERRED',
        'IN', 'ADD', 'JUST', 'ONLY', 'CHANGE',
    }

    # Bold terms: **Something** (domain-specific emphasis)
    for match in re.finditer(r'\*\*([^*]{3,50})\*\*', cleaned):
        term = match.group(1).strip()
        if term.upper() in skip_labels or term.upper() in user_blacklist:
            continue
        if term.lower() in section_headers:
            continue
        if re.match(r'^Message\s+\d+', term):
            continue
        if '/' in term or '\\' in term:
            continue
        if _is_formatting_artifact(term):
            continue
        if len(term) > 3:
            topics.add(term)

    # Capitalized multi-word phrases (domain-specific names)
    for match in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', cleaned):
        phrase = match.group(1).strip()
        if phrase.lower() in section_headers:
            continue
        if phrase.upper() in user_blacklist:
            continue
        if re.match(r'^(Message|Session|Turn|Step|Phase|Option)\s', phrase):
            continue
        if _is_formatting_artifact(phrase):
            continue
        if len(phrase) > 5:
            topics.add(phrase)

    # ALL-CAPS acronyms (project-specific abbreviations)
    # Hardcoded: common English words, technical boilerplate, status labels
    skip_acr = {
        # 2-letter
        'OK', 'ID', 'VS', 'IE', 'EG', 'IF', 'OR', 'IS', 'IT', 'DO', 'AS',
        'ON', 'TO', 'AT', 'OF', 'NO', 'UP', 'SO', 'BE', 'BY', 'AM', 'AN',
        'PC', 'IN',
        # 3-letter
        'NOT', 'THE', 'AND', 'FOR', 'ALL', 'HAS', 'WAS', 'GET', 'SET', 'PUT',
        'API', 'CLI', 'URL', 'SQL', 'ADD', 'BUT', 'CAN', 'DID', 'HAD', 'HER',
        'HIS', 'HIM', 'HOW', 'ITS', 'LET', 'MAY', 'NEW', 'NOW', 'OLD', 'OUR',
        'OWN', 'RAN', 'SAY', 'SHE', 'THE', 'TRY', 'USE', 'WAY', 'WHO', 'WIN',
        'YET', 'ANY', 'FEW', 'GOT', 'NOR', 'RUN', 'TWO',
        # 4-letter
        'JSON', 'HTML', 'TEXT', 'FILE', 'PATH', 'UUID', 'NULL', 'TRUE', 'ARGS',
        'HTTP', 'SELF', 'NONE', 'JUST', 'ONLY', 'ALSO', 'BACK', 'BEEN', 'BOTH',
        'CALL', 'COME', 'DONE', 'EACH', 'EVEN', 'FIND', 'FROM', 'GAVE', 'GOES',
        'GONE', 'GOOD', 'HAVE', 'HERE', 'INTO', 'KEEP', 'KNOW', 'LAST', 'LEFT',
        'LIKE', 'LIST', 'LOOK', 'MADE', 'MAKE', 'MANY', 'MORE', 'MOST', 'MUCH',
        'MUST', 'NAME', 'NEED', 'NEXT', 'ONCE', 'OVER', 'PART', 'SAME', 'SHOW',
        'SIDE', 'SOME', 'SUCH', 'SURE', 'TAKE', 'TELL', 'THAN', 'THAT', 'THEM',
        'THEN', 'THEY', 'THIS', 'TOOK', 'VERY', 'WANT', 'WELL', 'WENT', 'WERE',
        'WHAT', 'WHEN', 'WILL', 'WITH', 'WORK', 'YOUR',
        # 5+ letter common English
        'FALSE', 'ABOUT', 'ABOVE', 'AFTER', 'AGAIN', 'BEING', 'BELOW', 'COULD',
        'EVERY', 'FIRST', 'FOUND', 'NEVER', 'OTHER', 'SHALL', 'SINCE', 'STILL',
        'THEIR', 'THERE', 'THESE', 'THINK', 'THOSE', 'THREE', 'UNDER', 'UNTIL',
        'WHERE', 'WHICH', 'WHILE', 'WHOSE', 'WOULD', 'SHOULD', 'THROUGH',
        'BEFORE', 'BETWEEN', 'BECAUSE', 'DURING', 'WITHOUT', 'ALREADY',
        'ANOTHER', 'ALWAYS', 'APPEAR', 'CHANGE', 'DISCUSSED', 'IDENTIFIED',
        'PREVIOUS', 'UPDATED', 'UNLESS',
        # Technical/formatting labels
        'CREATED', 'MODIFIED', 'GENERATED', 'MEMORY', 'README',
        'UTF', 'STDERR', 'STDOUT', 'TYPE', 'LOCAL',
    }
    # Merge user blacklist
    skip_acr.update(user_blacklist)
    for match in re.finditer(r'\b([A-Z]{2,})\b', cleaned):
        acr = match.group(1)
        if acr not in skip_acr:
            topics.add(acr)

    return sorted(topics)


def extract_turn_count_claims(text):
    """Extract any turn count claims (e.g., '68-turn', '143 turns')."""
    counts = []
    for match in re.finditer(r'(\d+)[\s-]*turns?\b', text, re.IGNORECASE):
        counts.append(int(match.group(1)))
    return counts


def extract_function_claims(text):
    """Extract function/class names from code blocks in the summary."""
    names = set()
    for match in re.finditer(r'\bdef\s+(\w+)\s*\(', text):
        names.add(match.group(1))
    for match in re.finditer(r'\bclass\s+(\w+)', text):
        name = match.group(1)
        # Skip common non-class words that might match
        if name not in ('Task', 'Path', 'Counter'):
            names.add(name)
    return sorted(names)


# ============================================================
# ARCHIVE LOADING
# ============================================================

def find_archive_dir(start_path):
    """Locate the context_archive directory from a starting path."""
    candidates = [
        Path(start_path) / 'context_archive',
        Path(start_path).parent / 'context_archive',
        Path(start_path),
    ]
    for c in candidates:
        if c.is_dir() and (c.name == 'context_archive' or list(c.glob('session_*.md'))):
            return c
    return None


def list_session_files(archive_dir):
    """List session files, preferring .enriched.md over .md."""
    files = {}
    for f in Path(archive_dir).glob("session_*.md"):
        if f.name == "index.md":
            continue
        base = f.name.replace(".enriched.md", ".md")
        if base not in files:
            files[base] = f
        elif f.name.endswith(".enriched.md"):
            files[base] = f
    return sorted(files.values(), key=lambda p: p.name)


def parse_session_header(filepath):
    """Parse metadata from a session .md file header."""
    meta = {
        'filepath': filepath,
        'filename': filepath.name,
        'topics': '',
        'tools_used': '',
        'files_referenced': '',
        'turns': 0,
        'summary': '',
        'session_id': '',
        'date': '',
    }
    with open(filepath, 'r', encoding='utf-8') as f:
        header = f.read(4000)

    date_match = re.search(r'session_(\d{4}-\d{2}-\d{2})', filepath.name)
    if date_match:
        meta['date'] = date_match.group(1)

    for match in re.finditer(r'\*\*(\w[\w\s]*)\*\*:\s*(.+)', header):
        key = match.group(1).strip().lower().replace(' ', '_')
        val = match.group(2).strip().strip('`')
        if key == 'session_id':
            meta['session_id'] = val
        elif key == 'turns':
            try:
                meta['turns'] = int(val)
            except ValueError:
                pass
        elif key == 'summary':
            meta['summary'] = val
        elif key == 'topics':
            meta['topics'] = val
        elif key == 'tools_used':
            meta['tools_used'] = val
        elif key == 'files_referenced':
            meta['files_referenced'] = val

    return meta


def parse_turns(filepath):
    """Parse turns from a session .md file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    turn_pattern = re.compile(r'^## Turn (\d+) \u2014 (User|Claude) \[(\S*)\]', re.MULTILINE)
    matches = list(turn_pattern.finditer(content))
    turns = []

    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        turn_content = content[start:end].strip().rstrip('---').strip()
        turns.append({
            'number': int(match.group(1)),
            'role': match.group(2).lower(),
            'time': match.group(3),
            'content': turn_content,
        })

    return turns


# ============================================================
# VERIFICATION
# ============================================================

def verify_files(claimed_files, archive_meta):
    """Check claimed file paths against archive's Files Referenced."""
    archive_ref = archive_meta.get('files_referenced', '')
    # Normalize: lowercase, forward slashes
    archive_norm = archive_ref.replace('\\\\', '/').replace('\\', '/').lower()

    results = []
    for f in claimed_files:
        f_norm = f.replace('\\\\', '/').replace('\\', '/').lower()
        # Direct substring match
        found = f_norm in archive_norm
        if not found:
            # Try filename-only match (last path component)
            fname = f_norm.rstrip('/').rsplit('/', 1)[-1]
            if len(fname) > 3:
                found = fname in archive_norm
        results.append({
            'claim': f,
            'status': 'FOUND' if found else 'MISSING',
        })
    return results


def verify_tools(claimed_tools, archive_meta):
    """Check claimed tool names against archive's Tools Used."""
    archive_tools = set(
        t.strip() for t in archive_meta.get('tools_used', '').split(',')
    )
    results = []
    for tool in claimed_tools:
        results.append({
            'claim': tool,
            'status': 'FOUND' if tool in archive_tools else 'MISSING',
        })
    return results


def verify_quotes(quotes, turns):
    """Search for quoted user messages in archive turn content."""
    user_text = ' '.join(t['content'] for t in turns if t['role'] == 'user').lower()

    results = []
    for quote in quotes:
        display = quote[:80] + ('...' if len(quote) > 80 else '')
        q_lower = quote.lower()

        # Exact substring
        if q_lower in user_text:
            results.append({'claim': display, 'status': 'FOUND'})
            continue

        # First 40 chars as prefix
        prefix = q_lower[:40].strip()
        if len(prefix) > 10 and prefix in user_text:
            results.append({'claim': display, 'status': 'FOUND'})
            continue

        # Significant-word overlap (60% threshold)
        words = [w for w in q_lower.split() if len(w) > 4]
        if words:
            hits = sum(1 for w in words if w in user_text)
            if hits >= max(1, len(words) * 0.6):
                results.append({'claim': display, 'status': 'FOUND'})
                continue

        results.append({'claim': display, 'status': 'MISSING'})
    return results


def verify_topics(claimed_topics, archive_meta):
    """Check topic claims against archive's Topics field."""
    archive_topics = archive_meta.get('topics', '').lower()

    results = []
    for topic in claimed_topics:
        t_lower = topic.lower()
        # Direct match
        found = t_lower in archive_topics
        if not found:
            # Try individual words (for multi-word topics)
            words = t_lower.split()
            found = any(w in archive_topics for w in words if len(w) > 3)
        results.append({
            'claim': topic,
            'status': 'FOUND' if found else 'MISSING',
        })
    return results


def verify_turn_counts(claimed_counts, archive_meta):
    """Check turn count claims against archive metadata."""
    actual = archive_meta.get('turns', 0)
    results = []
    for count in claimed_counts:
        if count == actual:
            status = 'FOUND'
        else:
            status = f'MISMATCH (archive: {actual} turns)'
        results.append({'claim': f'{count} turns', 'status': status})
    return results


def verify_functions(claimed_functions, turns):
    """Search for function/class names in archive turn content."""
    all_text = ' '.join(t['content'] for t in turns)

    results = []
    for name in claimed_functions:
        found = name in all_text
        label = f'def {name}()' if not name[0].isupper() else f'class {name}'
        results.append({'claim': label, 'status': 'FOUND' if found else 'MISSING'})
    return results


# ============================================================
# FULL-TEXT DEEP SEARCH (secondary verification for MISSING claims)
# ============================================================

def deep_search_missing(missing_claims, turns):
    """For claims marked MISSING against headers, try full turn content.

    Returns dict of claim -> bool (found in content or not).
    """
    all_text = ' '.join(t['content'] for t in turns).lower()
    found_in_content = {}
    for claim in missing_claims:
        # Try the claim text directly
        key = claim.lower().replace('\\', '/').rstrip('/')
        # For file paths, try the filename
        if '/' in key or ':' in key:
            fname = key.rstrip('/').rsplit('/', 1)[-1]
            found_in_content[claim] = fname in all_text if len(fname) > 3 else False
        else:
            found_in_content[claim] = key in all_text
    return found_in_content


# ============================================================
# REPORT
# ============================================================

def format_report(all_results, archive_meta=None, summary_info=None):
    """Format verification results as a readable audit report."""
    lines = []
    lines.append("=" * 64)
    lines.append("  COMPACTION SUMMARY AUDIT REPORT")
    lines.append("=" * 64)

    if summary_info:
        lines.append(f"  Compaction timestamp : {summary_info.get('timestamp', '?')}")
        lines.append(f"  Summary length       : {summary_info.get('length', '?')} chars")
    if archive_meta:
        lines.append(f"  Archive file         : {archive_meta.get('filename', '?')}")
        lines.append(f"  Archive session ID   : {archive_meta.get('session_id', '?')[:12]}...")
        lines.append(f"  Archive turns        : {archive_meta.get('turns', '?')}")
        lines.append(f"  Archive date         : {archive_meta.get('date', '?')}")
    lines.append("=" * 64)

    total_found = 0
    total_missing = 0
    total_mismatch = 0
    category_stats = {}

    for category, results in all_results.items():
        if not results:
            continue

        cat_found = sum(1 for r in results if r['status'].startswith('FOUND'))
        cat_total = len(results)
        category_stats[category] = (cat_found, cat_total)

        lines.append(f"\n  --- {category} ({cat_found}/{cat_total}) ---")
        for r in results:
            status = r['status']
            if status == 'FOUND':
                marker = '[FOUND]   '
                total_found += 1
            elif status == 'FOUND (deep)':
                marker = '[DEEP]    '
                total_found += 1
            elif status == 'MISSING':
                marker = '[MISSING] '
                total_missing += 1
            else:
                marker = '[MISMATCH]'
                total_mismatch += 1
            lines.append(f"    {marker} {r['claim']}")

    total = total_found + total_missing + total_mismatch
    lines.append(f"\n{'=' * 64}")
    lines.append(f"  TOTALS: {total_found} found / {total_missing} missing / {total_mismatch} mismatched")
    if total > 0:
        pct = total_found / total * 100
        lines.append(f"  Verification rate: {pct:.0f}% ({total_found}/{total} claims)")
    lines.append("=" * 64)

    # Category breakdown
    if category_stats:
        lines.append("\n  Category Breakdown:")
        for cat, (found, tot) in category_stats.items():
            pct = found / tot * 100 if tot > 0 else 0
            bar = '#' * int(pct / 5) + '-' * (20 - int(pct / 5))
            lines.append(f"    {cat:<22} [{bar}] {pct:3.0f}%")

    return '\n'.join(lines)


# ============================================================
# STRUCTURED JSON OUTPUT
# ============================================================

def build_structured_results(all_results, archive_meta=None, summary_info=None):
    """Build structured dict from verification results.

    Returns a dict suitable for JSON serialization or history logging.
    """
    timestamp = summary_info.get('timestamp', '') if summary_info else ''
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    total_found = 0
    total_missing = 0
    total_mismatch = 0
    categories = {}
    claims = []
    claim_counter = {}

    for category, results in all_results.items():
        if not results:
            categories[category] = {
                'total': 0, 'found': 0, 'missing': 0, 'mismatched': 0,
                'rate': 1.0, 'severity': CATEGORY_SEVERITY.get(category, 'INFO'),
            }
            continue

        severity = CATEGORY_SEVERITY.get(category, 'INFO')
        cat_found = 0
        cat_missing = 0
        cat_mismatch = 0

        # Generate claim IDs: fp-1, fp-2, tu-1, etc.
        prefix = ''.join(w[0].lower() for w in category.split('/')[:1])
        if category not in claim_counter:
            claim_counter[category] = 0

        for r in results:
            claim_counter[category] += 1
            cid = f"{prefix}-{claim_counter[category]}"

            status = r['status']
            if status.startswith('FOUND'):
                cat_found += 1
                total_found += 1
                location = 'deep' if 'deep' in status else 'header'
            elif status == 'MISSING':
                cat_missing += 1
                total_missing += 1
                location = 'none'
            else:
                cat_mismatch += 1
                total_mismatch += 1
                location = 'none'

            # Normalize status for JSON
            json_status = 'FOUND' if status.startswith('FOUND') else status.split(' ')[0]

            claims.append({
                'id': cid,
                'category': category,
                'claim': r['claim'],
                'status': json_status,
                'severity': severity,
                'location': location,
            })

        cat_total = cat_found + cat_missing + cat_mismatch
        categories[category] = {
            'total': cat_total,
            'found': cat_found,
            'missing': cat_missing,
            'mismatched': cat_mismatch,
            'rate': cat_found / cat_total if cat_total > 0 else 1.0,
            'severity': severity,
        }

    total = total_found + total_missing + total_mismatch

    # Severity-weighted score
    weighted_found = 0
    weighted_total = 0
    for category, stats in categories.items():
        weight = SEVERITY_WEIGHT.get(stats['severity'], 1)
        weighted_found += stats['found'] * weight
        weighted_total += stats['total'] * weight

    result = {
        'timestamp': timestamp,
        'session_id': archive_meta.get('session_id', '') if archive_meta else '',
        'archive_file': archive_meta.get('filename', '') if archive_meta else '',
        'archive_turns': archive_meta.get('turns', 0) if archive_meta else 0,
        'summary_length': summary_info.get('length', 0) if summary_info else 0,
        'summary': {
            'total': total,
            'found': total_found,
            'missing': total_missing,
            'mismatched': total_mismatch,
            'rate': total_found / total if total > 0 else 1.0,
            'severity_weighted_rate': weighted_found / weighted_total if weighted_total > 0 else 1.0,
        },
        'categories': categories,
        'claims': claims,
    }
    return result


def format_json_report(all_results, archive_meta=None, summary_info=None):
    """Format verification results as structured JSON string."""
    result = build_structured_results(all_results, archive_meta, summary_info)
    return json.dumps(result, indent=2, ensure_ascii=False)


# ============================================================
# HISTORY & TREND ANALYSIS
# ============================================================

def load_audit_history(history_path):
    """Load audit history from a .jsonl file.

    Returns list of dicts (one per audit run), ordered chronologically.
    """
    history = []
    if not history_path or not Path(history_path).exists():
        return history
    with open(history_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return history


def compute_trend_line(history):
    """Build a trend string like '71% → 71% → 95%' from history."""
    if not history:
        return None
    rates = []
    for run in history:
        summary = run.get('summary', {})
        rate = summary.get('rate', 0)
        rates.append(f"{rate * 100:.0f}%")
    return ' \u2192 '.join(rates)


def detect_regressions(current, previous):
    """Compare current run against previous run, flag regressions.

    Returns list of strings describing any regressions.
    """
    if not previous:
        return []
    regressions = []
    prev_cats = previous.get('categories', {})
    curr_cats = current.get('categories', {})
    for cat, curr_stats in curr_cats.items():
        prev_stats = prev_cats.get(cat, {})
        prev_rate = prev_stats.get('rate', 1.0)
        curr_rate = curr_stats.get('rate', 1.0)
        if curr_rate < prev_rate:
            severity = curr_stats.get('severity', 'INFO')
            regressions.append(
                f"[{severity}] {cat}: {prev_rate * 100:.0f}% \u2192 {curr_rate * 100:.0f}%"
            )
    return regressions


def format_report_with_trends(all_results, archive_meta=None, summary_info=None,
                               history=None):
    """Enhanced text report with trend line, regressions, and severity score.

    Falls back to basic format_report if no history available.
    """
    # Build structured data for this run
    structured = build_structured_results(all_results, archive_meta, summary_info)

    lines = []
    lines.append("=" * 64)
    lines.append("  COMPACTION SUMMARY AUDIT REPORT")
    lines.append("=" * 64)

    if summary_info:
        lines.append(f"  Compaction timestamp : {summary_info.get('timestamp', '?')}")
        lines.append(f"  Summary length       : {summary_info.get('length', '?')} chars")
    if archive_meta:
        lines.append(f"  Archive file         : {archive_meta.get('filename', '?')}")
        lines.append(f"  Archive session ID   : {archive_meta.get('session_id', '?')[:12]}...")
        lines.append(f"  Archive turns        : {archive_meta.get('turns', '?')}")
        lines.append(f"  Archive date         : {archive_meta.get('date', '?')}")

    # Run metadata
    run_number = (len(history) + 1) if history else 1
    lines.append(f"  Run number           : {run_number}")

    # Trend line
    if history:
        past_trend = compute_trend_line(history)
        current_rate = structured['summary']['rate']
        trend = f"{past_trend} \u2192 {current_rate * 100:.0f}%"
        lines.append(f"  Trend                : {trend}")

    lines.append("=" * 64)

    # Regression alerts
    if history:
        regressions = detect_regressions(structured, history[-1])
        if regressions:
            lines.append("\n  *** REGRESSIONS DETECTED ***")
            for r in regressions:
                lines.append(f"    {r}")
        else:
            lines.append("\n  No regressions vs previous run.")

    # Per-category results (same as original format_report)
    total_found = 0
    total_missing = 0
    total_mismatch = 0
    category_stats = {}

    for category, results in all_results.items():
        if not results:
            continue

        severity = CATEGORY_SEVERITY.get(category, 'INFO')
        cat_found = sum(1 for r in results if r['status'].startswith('FOUND'))
        cat_total = len(results)
        category_stats[category] = (cat_found, cat_total, severity)

        lines.append(f"\n  --- {category} [{severity}] ({cat_found}/{cat_total}) ---")
        for r in results:
            status = r['status']
            if status == 'FOUND':
                marker = '[FOUND]   '
                total_found += 1
            elif status == 'FOUND (deep)':
                marker = '[DEEP]    '
                total_found += 1
            elif status == 'MISSING':
                marker = '[MISSING] '
                total_missing += 1
            else:
                marker = '[MISMATCH]'
                total_mismatch += 1
            lines.append(f"    {marker} {r['claim']}")

    total = total_found + total_missing + total_mismatch
    lines.append(f"\n{'=' * 64}")
    lines.append(f"  TOTALS: {total_found} found / {total_missing} missing / {total_mismatch} mismatched")
    if total > 0:
        pct = total_found / total * 100
        lines.append(f"  Verification rate: {pct:.0f}% ({total_found}/{total} claims)")

    # Severity-weighted score
    sw_rate = structured['summary']['severity_weighted_rate']
    lines.append(f"  Severity-weighted  : {sw_rate * 100:.0f}%")
    lines.append("=" * 64)

    # Category breakdown with severity
    if category_stats:
        lines.append("\n  Category Breakdown:")
        for cat, (found, tot, sev) in category_stats.items():
            pct = found / tot * 100 if tot > 0 else 0
            bar = '#' * int(pct / 5) + '-' * (20 - int(pct / 5))
            lines.append(f"    {cat:<22} [{bar}] {pct:3.0f}%  ({sev})")

    return '\n'.join(lines), structured


# ============================================================
# MAIN
# ============================================================

def run_audit(args):
    """Core audit logic shared by main() and autoarchive imports.

    Returns (all_results, archive_meta, summary_info, archive_dir) or exits on error.
    """
    if not args.jsonl and not args.summary:
        return None

    # ---- Get compaction summary text ----
    summary_info = {}
    session_id_hint = ''

    if args.summary:
        summary_text = read_summary_file(args.summary)
        summary_info = {'length': len(summary_text)}
    else:
        summaries = find_compaction_summaries(args.jsonl)
        if not summaries:
            print("ERROR: No compaction summaries found in .jsonl", file=sys.stderr)
            sys.exit(1)
        idx = args.which if args.which >= 0 else len(summaries) + args.which
        if idx < 0 or idx >= len(summaries):
            print(f"ERROR: --which {args.which} out of range (found {len(summaries)} summaries)",
                  file=sys.stderr)
            sys.exit(1)
        chosen = summaries[idx]
        summary_text = chosen['text']
        session_id_hint = chosen.get('session_id', '')
        summary_info = {
            'timestamp': chosen.get('timestamp', ''),
            'length': len(summary_text),
            'line': chosen.get('line', '?'),
        }
        print(f"Found {len(summaries)} compaction summary(ies), auditing #{idx + 1} "
              f"(line {chosen.get('line', '?')}, {len(summary_text)} chars)",
              file=sys.stderr)

    # ---- Find archive ----
    archive_dir = None
    if args.archive:
        archive_dir = Path(args.archive)
    elif args.jsonl:
        archive_dir = find_archive_dir(Path(args.jsonl).parent)
    if not archive_dir:
        for candidate in [
            Path('F:/Better_Compaction_Protocol/context_archive'),
            Path('./context_archive'),
        ]:
            if candidate.is_dir():
                archive_dir = candidate
                break
    if not archive_dir or not archive_dir.is_dir():
        print("ERROR: Cannot find context_archive directory. Use --archive.", file=sys.stderr)
        sys.exit(1)
    print(f"Archive: {archive_dir}", file=sys.stderr)

    # ---- Find target session file ----
    session_files = list_session_files(archive_dir)
    target = None

    if hasattr(args, 'session') and args.session:
        for sf in session_files:
            if args.session in sf.name or args.session in str(sf):
                target = sf
                break
        if not target:
            print(f"ERROR: No session file matching '{args.session}'", file=sys.stderr)
            sys.exit(1)
    elif session_id_hint:
        sid_short = session_id_hint[:8]
        for sf in session_files:
            if sid_short in sf.name:
                target = sf
                break
    if not target and session_files:
        target = session_files[-1]
    if not target:
        print("ERROR: No session files found in archive", file=sys.stderr)
        sys.exit(1)

    print(f"Comparing against: {target.name}", file=sys.stderr)
    print(file=sys.stderr)

    # ---- Load archive data ----
    archive_meta = parse_session_header(target)
    archive_turns = parse_turns(target)

    # ---- Extract claims ----
    claimed_files = extract_file_claims(summary_text)
    claimed_tools = extract_tool_claims(summary_text)
    claimed_quotes = extract_user_quotes(summary_text)
    claimed_topics = extract_topic_claims(summary_text)
    claimed_counts = extract_turn_count_claims(summary_text)
    claimed_functions = extract_function_claims(summary_text)

    # ---- Verify ----
    all_results = {}
    all_results['File Paths'] = verify_files(claimed_files, archive_meta)
    all_results['Tools Used'] = verify_tools(claimed_tools, archive_meta)
    all_results['User Quotes'] = verify_quotes(claimed_quotes, archive_turns)
    all_results['Topics'] = verify_topics(claimed_topics, archive_meta)
    all_results['Turn Counts'] = verify_turn_counts(claimed_counts, archive_meta)
    all_results['Functions/Classes'] = verify_functions(claimed_functions, archive_turns)

    # ---- Deep search for MISSING claims ----
    deep = getattr(args, 'deep', False)
    if deep:
        for category, results in all_results.items():
            missing = [r['claim'] for r in results if r['status'] == 'MISSING']
            if missing:
                found_deep = deep_search_missing(missing, archive_turns)
                for r in results:
                    if r['status'] == 'MISSING' and found_deep.get(r['claim'], False):
                        r['status'] = 'FOUND (deep)'

    return all_results, archive_meta, summary_info, archive_dir


def main():
    parser = argparse.ArgumentParser(
        description='Audit compaction summaries against archived session files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python context_auditor.py transcript.jsonl
  python context_auditor.py transcript.jsonl --which 0
  python context_auditor.py transcript.jsonl --format json
  python context_auditor.py --summary pasted.txt --archive ./context_archive"""
    )
    parser.add_argument('jsonl', nargs='?',
                        help='Path to .jsonl transcript file')
    parser.add_argument('--summary',
                        help='Path to text file containing a compaction summary')
    parser.add_argument('--archive',
                        help='Path to context_archive directory (auto-detected if omitted)')
    parser.add_argument('--session',
                        help='Specific session file to compare against')
    parser.add_argument('--which', type=int, default=-1,
                        help='Which compaction summary to audit: 0=first, -1=last (default: -1)')
    parser.add_argument('--deep', action='store_true',
                        help='Run deep search on turn content for MISSING claims')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                        dest='output_format',
                        help='Output format: text (default) or json (structured)')
    parser.add_argument('--history-file',
                        help='Path to audit_history.jsonl for trend analysis')
    args = parser.parse_args()

    if not args.jsonl and not args.summary:
        parser.print_help()
        sys.exit(1)

    result = run_audit(args)
    if result is None:
        parser.print_help()
        sys.exit(1)

    all_results, archive_meta, summary_info, archive_dir = result

    if args.output_format == 'json':
        print(format_json_report(all_results, archive_meta, summary_info))
    else:
        # Load history for trend-aware report
        history = []
        history_path = args.history_file
        if not history_path and archive_dir:
            default_history = Path(archive_dir) / 'audit_history.jsonl'
            if default_history.exists():
                history_path = str(default_history)
        if history_path:
            history = load_audit_history(history_path)

        report, _ = format_report_with_trends(
            all_results, archive_meta, summary_info, history
        )
        print(report)


if __name__ == '__main__':
    main()
