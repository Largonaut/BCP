#!/usr/bin/env python3
"""context_autoarchive.py - Compaction-Aware Auto-Archival (Tool #4)

Orchestrates the archive-audit pipeline for Claude Code compaction events.
Designed to run as a Claude Code hook, injecting audit results into
post-compaction context so the new instance knows what it lost.

Part of the Better Compaction Protocol.

Location: F:\claude_tools\context_autoarchive.py
Usage (manual):
    python F:/claude_tools/context_autoarchive.py --phase pre --project-path F:/some/project
    python F:/claude_tools/context_autoarchive.py --phase post --project-path F:/some/project

Usage (as Claude Code hook):
    Configured in ~/.claude/settings.json under "hooks" key.
    Receives JSON on stdin from Claude Code with session metadata.

Hook configuration:
    PreCompact       -> --phase pre  (archive before compaction)
    SessionStart     -> --phase post (audit + report after compaction)
"""

import argparse
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 on Windows
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add claude_tools to path for sibling imports
TOOLS_DIR = Path(__file__).parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def read_hook_stdin():
    """Read and parse JSON from stdin (sent by Claude Code hooks).

    Returns parsed dict, or empty dict if stdin is empty/invalid/TTY.
    """
    try:
        if sys.stdin.isatty():
            return {}
        data = sys.stdin.read(102400)  # 100KB limit — hook payloads are small
        if not data.strip():
            return {}
        return json.loads(data)
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def resolve_project_path(args, hook_data):
    """Determine project path from CLI args, hook stdin, or CWD.

    Priority: CLI --project-path > hook stdin fields > CWD
    """
    if args.project_path:
        return os.path.abspath(args.project_path)

    # Try hook stdin for project path (field name may vary)
    if hook_data:
        for key in ('project_path', 'projectPath', 'cwd', 'workingDirectory'):
            if key in hook_data:
                return os.path.abspath(hook_data[key])

    # Fallback: CWD (Claude Code sets this to project root)
    return os.path.abspath(os.getcwd())


def phase_pre(project_path):
    """Pre-compaction phase: archive current session state + inject ground truth.

    Runs context_preserver.py via import, then reads the archive file
    just written and outputs structured metadata to stdout. This metadata
    gets injected into Claude's context immediately before compaction,
    giving the compaction process real data to cite (turn counts, topics, etc).

    Preserver progress output goes to stderr (informational).
    Ground truth metadata block goes to stdout (injected into context).
    """
    print(f"[autoarchive:pre] Archiving {project_path}", file=sys.stderr)

    try:
        import context_preserver
    except ImportError as e:
        print(f"[autoarchive:pre] ERROR: Cannot import context_preserver: {e}", file=sys.stderr)
        return False

    # Capture preserver's stdout (it prints progress there)
    old_stdout = sys.stdout
    old_argv = sys.argv
    captured = io.StringIO()

    try:
        sys.stdout = captured
        sys.argv = ['context_preserver', '--project-path', project_path]
        context_preserver.main()
    except SystemExit as e:
        if e.code and e.code != 0:
            sys.stdout = old_stdout
            print(f"[autoarchive:pre] Preserver exited with code {e.code}", file=sys.stderr)
            output = captured.getvalue()
            if output:
                print(output, file=sys.stderr)
            return False
    except Exception as e:
        sys.stdout = old_stdout
        print(f"[autoarchive:pre] ERROR: {e}", file=sys.stderr)
        return False
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv

    # Send preserver output to stderr (informational, not for context injection)
    output = captured.getvalue()
    if output:
        print(output, file=sys.stderr)

    print("[autoarchive:pre] Archive complete", file=sys.stderr)

    # --- Ground Truth Injection ---
    # Read the archive file just written and output structured metadata to stdout.
    # This gets injected into context before compaction generates its summary.
    try:
        import context_auditor

        archive_dir = Path(project_path) / 'context_archive'
        if not archive_dir.is_dir():
            print("[autoarchive:pre] No archive dir for ground truth", file=sys.stderr)
            return True  # Archive succeeded, just no ground truth to inject

        # Find the most recently modified session file
        session_files = sorted(
            archive_dir.glob("session_*.md"),
            key=lambda f: f.stat().st_mtime
        )
        if not session_files:
            print("[autoarchive:pre] No session files for ground truth", file=sys.stderr)
            return True

        target = session_files[-1]
        print(f"[autoarchive:pre] Ground truth source: {target.name}", file=sys.stderr)

        # Parse header metadata
        meta = context_auditor.parse_session_header(target)

        # Count actual turns (more reliable than header field)
        turn_count = context_preserver.get_archived_turn_count(target)

        # Extract first and last turn timestamps for duration
        turns = context_auditor.parse_turns(target)
        first_time = turns[0]['time'] if turns else '?'
        last_time = turns[-1]['time'] if turns else '?'

        # Parse date from filename
        session_date = meta.get('date', '?')

        # Build and output the ground truth block
        print("=== SESSION GROUND TRUTH (for compaction reference) ===")
        print(f"Turn count: {turn_count}")
        print(f"Session ID: {meta.get('session_id', '?')}")
        print(f"Duration: {session_date} {first_time} to {last_time}")
        if meta.get('topics'):
            print(f"Topics: {meta['topics']}")
        if meta.get('files_referenced'):
            print(f"Files referenced: {meta['files_referenced']}")
        if meta.get('tools_used'):
            print(f"Tools used: {meta['tools_used']}")
        print(f"Archive file: {target.name}")
        print("===")

        # Save ground truth to file for post-phase bundling
        try:
            reports_dir = archive_dir / 'compaction_reports'
            reports_dir.mkdir(parents=True, exist_ok=True)
            ground_truth = {
                'turn_count': turn_count,
                'session_id': meta.get('session_id', '?'),
                'duration': {
                    'date': session_date,
                    'start': first_time,
                    'end': last_time,
                },
                'topics': meta.get('topics', ''),
                'files_referenced': meta.get('files_referenced', ''),
                'tools_used': meta.get('tools_used', ''),
                'archive_file': target.name,
            }
            pending_path = reports_dir / 'ground_truth_pending.json'
            with open(pending_path, 'w', encoding='utf-8') as f:
                json.dump(ground_truth, f, indent=2, ensure_ascii=False)
            print(f"[autoarchive:pre] Ground truth saved: {pending_path.name}",
                  file=sys.stderr)
        except Exception as e:
            print(f"[autoarchive:pre] Warning: Could not save ground truth file: {e}",
                  file=sys.stderr)

        print("[autoarchive:pre] Ground truth injected", file=sys.stderr)

    except Exception as e:
        # Ground truth injection is best-effort — don't fail the archive
        print(f"[autoarchive:pre] Warning: Ground truth extraction failed: {e}",
              file=sys.stderr)

    return True


def phase_post(project_path):
    """Post-compaction phase: audit compaction summary and report.

    Runs context_auditor.py verification logic via import.
    Full audit report goes to stdout (injected into Claude's context).
    Structured results appended to audit_history.jsonl.
    Status messages go to stderr.
    """
    print(f"[autoarchive:post] Auditing compaction for {project_path}", file=sys.stderr)

    try:
        import context_preserver
        import context_auditor
    except ImportError as e:
        print(f"[autoarchive:post] ERROR: Cannot import tools: {e}", file=sys.stderr)
        return False

    # Find the Claude project directory with .jsonl files
    try:
        project_dir = context_preserver.find_project_dir(project_path)
    except FileNotFoundError as e:
        print(f"[autoarchive:post] ERROR: {e}", file=sys.stderr)
        return False

    # Search all .jsonl files for compaction summaries
    jsonl_files = sorted(project_dir.glob("*.jsonl"))
    if not jsonl_files:
        print("[autoarchive:post] No .jsonl files found", file=sys.stderr)
        print("[COMPACTION AUDIT — auto-generated]")
        print("No transcript files found to audit.")
        print(f"Project: {project_path}")
        return True

    all_summaries = []
    for jf in jsonl_files:
        try:
            summaries = context_auditor.find_compaction_summaries(str(jf))
            for s in summaries:
                s['jsonl_file'] = jf
            all_summaries.extend(summaries)
        except Exception as e:
            print(f"[autoarchive:post] Warning: Error reading {jf.name}: {e}", file=sys.stderr)

    if not all_summaries:
        print("[autoarchive:post] No compaction summaries found", file=sys.stderr)
        print("[COMPACTION AUDIT — auto-generated]")
        print("No compaction summaries found to audit.")
        print(f"Project: {project_path}")
        return True

    # Sort by timestamp to find the chronologically latest compaction
    all_summaries.sort(key=lambda s: s.get('timestamp', ''))

    # Use the latest compaction summary
    latest = all_summaries[-1]
    summary_text = latest['text']
    session_id_hint = latest.get('session_id', '')
    summary_info = {
        'timestamp': latest.get('timestamp', ''),
        'length': len(summary_text),
        'line': latest.get('line', '?'),
    }

    print(f"[autoarchive:post] Found {len(all_summaries)} compaction(s), auditing latest",
          file=sys.stderr)

    # Find archive directory
    archive_dir = context_auditor.find_archive_dir(project_path)
    if not archive_dir:
        archive_dir = Path(project_path) / 'context_archive'
    if not archive_dir.is_dir():
        print(f"[autoarchive:post] ERROR: Archive not found: {archive_dir}", file=sys.stderr)
        return False

    # Find target session file
    session_files = context_auditor.list_session_files(archive_dir)
    target = None

    if session_id_hint:
        sid_short = session_id_hint[:8]
        for sf in session_files:
            if sid_short in sf.name:
                target = sf
                break
    if not target and session_files:
        target = session_files[-1]
    if not target:
        print("[autoarchive:post] ERROR: No session files in archive", file=sys.stderr)
        return False

    print(f"[autoarchive:post] Comparing against: {target.name}", file=sys.stderr)

    # Load archive data
    archive_meta = context_auditor.parse_session_header(target)
    archive_turns = context_auditor.parse_turns(target)

    # Extract claims from compaction summary
    claimed_files = context_auditor.extract_file_claims(summary_text)
    claimed_tools = context_auditor.extract_tool_claims(summary_text)
    claimed_quotes = context_auditor.extract_user_quotes(summary_text)
    claimed_topics = context_auditor.extract_topic_claims(summary_text)
    claimed_counts = context_auditor.extract_turn_count_claims(summary_text)
    claimed_functions = context_auditor.extract_function_claims(summary_text)

    # Verify each category
    all_results = {}
    all_results['File Paths'] = context_auditor.verify_files(claimed_files, archive_meta)
    all_results['Tools Used'] = context_auditor.verify_tools(claimed_tools, archive_meta)
    all_results['User Quotes'] = context_auditor.verify_quotes(claimed_quotes, archive_turns)
    all_results['Topics'] = context_auditor.verify_topics(claimed_topics, archive_meta)
    all_results['Turn Counts'] = context_auditor.verify_turn_counts(claimed_counts, archive_meta)
    all_results['Functions/Classes'] = context_auditor.verify_functions(
        claimed_functions, archive_turns
    )

    # Deep search for MISSING claims in full turn content
    for category, results in all_results.items():
        missing = [r['claim'] for r in results if r['status'] == 'MISSING']
        if missing:
            found_deep = context_auditor.deep_search_missing(missing, archive_turns)
            for r in results:
                if r['status'] == 'MISSING' and found_deep.get(r['claim'], False):
                    r['status'] = 'FOUND (deep)'

    # Load audit history for trend analysis
    history_path = archive_dir / 'audit_history.jsonl'
    history = context_auditor.load_audit_history(str(history_path))

    # Build structured results for history log
    structured = context_auditor.build_structured_results(
        all_results, archive_meta, summary_info
    )
    structured['run'] = len(history) + 1

    # Append to audit_history.jsonl (data-sacred: append-only)
    try:
        with open(history_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(structured, ensure_ascii=False) + '\n')
        print(f"[autoarchive:post] Appended run #{structured['run']} to {history_path.name}",
              file=sys.stderr)
    except Exception as e:
        print(f"[autoarchive:post] Warning: Could not write history: {e}", file=sys.stderr)

    # --- Report Bundling ---
    # Bundle ground truth + compaction summary + audit into single report file
    reports_dir = archive_dir / 'compaction_reports'
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Read ground truth from pre-phase (if available)
    ground_truth = None
    pending_path = reports_dir / 'ground_truth_pending.json'
    if pending_path.exists():
        try:
            with open(pending_path, 'r', encoding='utf-8') as f:
                ground_truth = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[autoarchive:post] Warning: Could not read ground truth: {e}",
                  file=sys.stderr)

    # Build trend from history + current run
    trend = []
    for h in history:
        s = h.get('summary', {})
        r = s.get('rate', 0)
        trend.append(round(r * 100) if isinstance(r, float) and r <= 1 else round(r))
    current_rate = structured.get('summary', {}).get('rate', 0)
    current_pct = round(current_rate * 100) if isinstance(current_rate, float) and current_rate <= 1 else round(current_rate)
    trend.append(current_pct)

    # Detect regressions (>5pp drop from previous run)
    regressions = []
    if history:
        prev = history[-1]
        prev_cats = prev.get('categories', {})
        curr_cats = structured.get('categories', {})
        for cat in curr_cats:
            if cat in prev_cats:
                prev_r = prev_cats[cat].get('rate', 0)
                curr_r = curr_cats[cat].get('rate', 0)
                if isinstance(prev_r, float) and prev_r <= 1:
                    prev_r = round(prev_r * 100)
                if isinstance(curr_r, float) and curr_r <= 1:
                    curr_r = round(curr_r * 100)
                if curr_r < prev_r - 5:
                    regressions.append({
                        'category': cat,
                        'previous': prev_r,
                        'current': curr_r,
                    })

    # Build bundled report
    bundled = {
        'report_version': 1,
        'timestamp': datetime.now().isoformat(),
        'session_id': session_id_hint or structured.get('session_id', '?'),
        'run_number': structured.get('run', len(history) + 1),
    }
    if ground_truth:
        bundled['ground_truth'] = ground_truth
    bundled['compaction_summary'] = {
        'text': summary_text,
        'length': len(summary_text),
        'compaction_timestamp': summary_info.get('timestamp', ''),
    }
    bundled['audit'] = {
        'rate': structured.get('summary', {}).get('rate', 0),
        'severity_weighted_rate': structured.get('summary', {}).get('severity_weighted_rate', 0),
        'categories': structured.get('categories', {}),
        'claims': structured.get('claims', []),
        'regressions': regressions,
    }
    bundled['trend'] = trend

    # Save bundled report
    ts_str = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    report_path = reports_dir / f'compaction_report_{ts_str}.json'
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(bundled, f, indent=2, ensure_ascii=False)
        print(f"[autoarchive:post] Bundled report: {report_path.name}", file=sys.stderr)
    except Exception as e:
        print(f"[autoarchive:post] Warning: Could not write bundled report: {e}",
              file=sys.stderr)
        report_path = None

    # Delete pending ground truth file after successful bundle
    if ground_truth and pending_path.exists():
        try:
            pending_path.unlink()
        except OSError:
            pass

    # Brief stdout beacon (replaces full report wall — details in bundled JSON)
    weighted = structured.get('summary', {}).get('severity_weighted_rate', 0)
    weighted_pct = round(weighted * 100) if isinstance(weighted, float) and weighted <= 1 else round(weighted)
    trend_str = ' \u2192 '.join(str(t) + '%' for t in trend)
    print("=== COMPACTION AUDIT ===")
    print(f"Run {structured.get('run', '?')}: {current_pct}% (severity-weighted: {weighted_pct}%)")
    print(f"Trend: {trend_str}")
    if regressions:
        reg_parts = [f"{r['category']}: {r['previous']}% \u2192 {r['current']}%" for r in regressions]
        print(f"Regressions: {', '.join(reg_parts)}")
    else:
        print("Regressions: None")
    if report_path:
        print(f"Report: {report_path}")
    print(f"Archive: {archive_dir}")
    print("===")

    # --- Plan File Migration ---
    # Detect the most recent plan file so post-compaction instances know where it is.
    try:
        plans_dir = Path(os.path.expanduser("~")) / ".claude" / "plans"
        if plans_dir.is_dir():
            plan_files = sorted(
                plans_dir.glob("*.md"),
                key=lambda f: f.stat().st_mtime
            )
            if plan_files:
                latest_plan = plan_files[-1]
                print(f"\nActive plan file: {latest_plan}")
                print(f"[autoarchive:post] Plan file detected: {latest_plan.name}",
                      file=sys.stderr)
    except Exception as e:
        print(f"[autoarchive:post] Warning: Plan file detection failed: {e}",
              file=sys.stderr)

    print("[autoarchive:post] Audit complete", file=sys.stderr)
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Compaction-aware auto-archival for Claude Code hooks',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Phases:
  pre   Archive current session state (before compaction). Output to stderr.
  post  Audit compaction summary (after compaction). Full report to stdout.

Manual usage:
  python context_autoarchive.py --phase pre --project-path F:/my/project
  python context_autoarchive.py --phase post --project-path F:/my/project

As Claude Code hook:
  Receives JSON on stdin with session metadata.
  Falls back to CWD for project path detection.
"""
    )
    parser.add_argument(
        '--phase', choices=['pre', 'post'], required=True,
        help='Which phase to run: pre (archive) or post (audit+report)'
    )
    parser.add_argument(
        '--project-path', default=None,
        help='Workspace path (default: from hook stdin or CWD)'
    )
    args = parser.parse_args()

    # Read hook stdin (if available)
    hook_data = read_hook_stdin()
    if hook_data:
        print(f"[autoarchive] Hook data keys: {list(hook_data.keys())}", file=sys.stderr)

    # Resolve project path
    project_path = resolve_project_path(args, hook_data)

    if args.phase == 'pre':
        success = phase_pre(project_path)
    else:
        success = phase_post(project_path)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
