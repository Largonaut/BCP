#!/usr/bin/env python3
"""context_rerunner.py - Audit Reproducibility Checker (Tool #5)

Reruns stored audits from audit_history.jsonl and compares original
results side-by-side with fresh reruns using current auditor code.
Verifies auditor determinism and detects regression from code changes.

Part of the Better Compaction Protocol.

Usage:
    python context_rerunner.py --project-path F:/Better_Compaction_Protocol
    python context_rerunner.py --run 4 --run 5
    python context_rerunner.py --dry-run
    python context_rerunner.py --format json
"""

import argparse
import io
import json
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 on Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Sibling import
TOOLS_DIR = Path(__file__).parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import context_auditor
import context_preserver


# ============================================================
# HISTORY LOADING & FILTERING
# ============================================================

def load_history(archive_dir):
    """Load audit_history.jsonl from the archive directory."""
    history_path = Path(archive_dir) / 'audit_history.jsonl'
    if not history_path.exists():
        return []
    return context_auditor.load_audit_history(str(history_path))


def is_rerunnable(entry):
    """Determine if an audit history entry can be rerun.

    Skips historical baselines that lack stored compaction data.
    """
    af = entry.get('archive_file', '')
    if af == '(pre-structured-output)' or not af:
        return False
    sid = entry.get('session_id', '')
    if sid.startswith('session-') and sid.endswith('-start'):
        return False
    return True


def get_run_number(entry, index):
    """Extract run number from entry, falling back to 1-based index."""
    return entry.get('run', index + 1)


def filter_entries(history, run_numbers=None):
    """Filter history to rerunnable entries, optionally by run number.

    Returns list of (run_number, entry) tuples.
    """
    result = []
    for i, entry in enumerate(history):
        run_num = get_run_number(entry, i)
        if not is_rerunnable(entry):
            continue
        if run_numbers and run_num not in run_numbers:
            continue
        result.append((run_num, entry))
    return result


# ============================================================
# COMPACTION MATCHING
# ============================================================

def build_compaction_index(jsonl_dir):
    """Scan .jsonl files and build timestamp -> compaction info lookup.

    Returns dict mapping timestamp_str -> {jsonl_path, which, session_id, text_len}.
    """
    index = {}
    for jf in sorted(Path(jsonl_dir).glob("*.jsonl")):
        try:
            summaries = context_auditor.find_compaction_summaries(str(jf))
        except Exception as e:
            print(f"  Warning: failed to scan {jf.name}: {e}", file=sys.stderr)
            continue
        for i, s in enumerate(summaries):
            ts = s.get('timestamp', '')
            if ts:
                index[ts] = {
                    'jsonl_path': jf,
                    'which': i,
                    'session_id': s.get('session_id', ''),
                    'text_len': len(s.get('text', '')),
                }
    return index


def match_entry_to_compaction(entry, compaction_index):
    """Match an audit history entry to its compaction summary.

    Primary: exact timestamp match.
    Fallback: closest timestamp within 5 seconds.
    """
    ts = entry.get('timestamp', '')

    # Exact match
    if ts in compaction_index:
        return compaction_index[ts]

    # Fallback: parse and find closest
    try:
        entry_dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None

    best = None
    best_delta = None
    for idx_ts, info in compaction_index.items():
        try:
            idx_dt = datetime.fromisoformat(idx_ts.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        delta = abs((entry_dt - idx_dt).total_seconds())
        if delta <= 5.0 and (best_delta is None or delta < best_delta):
            best = info
            best_delta = delta

    return best


# ============================================================
# RERUN EXECUTION
# ============================================================

def build_audit_args(jsonl_path, which_index, archive_dir):
    """Construct argparse.Namespace for run_audit()."""
    return Namespace(
        jsonl=str(jsonl_path),
        summary=None,
        archive=str(archive_dir),
        session=None,
        which=which_index,
        deep=True,
        output_format='json',
    )


def execute_rerun(compaction_match, archive_dir):
    """Execute a single audit rerun.

    Returns structured results dict, or None on failure.
    """
    args = build_audit_args(
        compaction_match['jsonl_path'],
        compaction_match['which'],
        archive_dir,
    )

    # Suppress stderr (auditor status messages)
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = context_auditor.run_audit(args)
    except SystemExit:
        sys.stderr = old_stderr
        return None
    except Exception as e:
        sys.stderr = old_stderr
        print(f"  Error during rerun: {e}", file=sys.stderr)
        return None
    finally:
        if sys.stderr != old_stderr:
            sys.stderr = old_stderr

    if result is None:
        return None

    all_results, archive_meta, summary_info, _ = result
    return context_auditor.build_structured_results(all_results, archive_meta, summary_info)


# ============================================================
# COMPARISON
# ============================================================

def compare_summaries(original, rerun):
    """Compare top-level summary stats.

    Prefers integer count comparison (found/total) over floating-point rate,
    since historical entries may store truncated rates.
    """
    o = original.get('summary', {})
    r = rerun.get('summary', {})
    o_rate = o.get('rate', 0)
    r_rate = r.get('rate', 0)

    # Integer comparison is exact and reliable
    o_total = o.get('total', 0)
    r_total = r.get('total', 0)
    o_found = o.get('found', 0)
    r_found = r.get('found', 0)

    if o_total > 0 and r_total > 0:
        # Compare by counts — handles rounded rates in historical entries
        counts_match = (o_total == r_total and o_found == r_found
                        and o.get('missing', 0) == r.get('missing', 0)
                        and o.get('mismatched', 0) == r.get('mismatched', 0))
    else:
        # Fallback to rate comparison with tolerance
        counts_match = abs(o_rate - r_rate) < 0.005

    return {
        'rate_match': counts_match,
        'rate_original': o_rate,
        'rate_rerun': r_rate,
        'rate_delta': r_rate - o_rate,
        'total_original': o_total,
        'total_rerun': r_total,
        'found_original': o_found,
        'found_rerun': r_found,
    }


def compare_categories(original, rerun):
    """Compare per-category rates."""
    o_cats = original.get('categories', {})
    r_cats = rerun.get('categories', {})
    all_cats = sorted(set(list(o_cats.keys()) + list(r_cats.keys())))

    results = []
    for cat in all_cats:
        o_rate = o_cats.get(cat, {}).get('rate', 0)
        r_rate = r_cats.get(cat, {}).get('rate', 0)
        results.append({
            'category': cat,
            'original_rate': o_rate,
            'rerun_rate': r_rate,
            'delta': r_rate - o_rate,
            'changed': abs(o_rate - r_rate) > 1e-9,
        })
    return results


def compare_claims(original_claims, rerun_claims):
    """Compare per-claim status between original and rerun.

    Matches by (category, claim_text) since IDs may differ.
    """
    if not original_claims and not rerun_claims:
        return {'unchanged': 0, 'upgraded': [], 'downgraded': [],
                'new_claims': [], 'removed_claims': [],
                'note': 'both empty'}

    if not original_claims:
        return {'unchanged': 0, 'upgraded': [], 'downgraded': [],
                'new_claims': [{'claim': c['claim'], 'category': c['category'],
                                'status': c['status']} for c in rerun_claims],
                'removed_claims': [],
                'note': 'original had no per-claim data'}

    orig_map = {(c['category'], c['claim']): c for c in original_claims}
    rerun_map = {(c['category'], c['claim']): c for c in rerun_claims}
    all_keys = sorted(set(list(orig_map.keys()) + list(rerun_map.keys())))

    unchanged = 0
    upgraded = []
    downgraded = []
    new_claims = []
    removed_claims = []

    for key in all_keys:
        o = orig_map.get(key)
        r = rerun_map.get(key)
        if o and r:
            if o['status'] == r['status']:
                unchanged += 1
            elif o['status'] in ('MISSING', 'MISMATCH') and r['status'] == 'FOUND':
                upgraded.append({'claim': key[1], 'category': key[0],
                                 'original': o['status'], 'rerun': r['status']})
            elif o['status'] == 'FOUND' and r['status'] in ('MISSING', 'MISMATCH'):
                downgraded.append({'claim': key[1], 'category': key[0],
                                   'original': o['status'], 'rerun': r['status']})
            else:
                upgraded.append({'claim': key[1], 'category': key[0],
                                 'original': o['status'], 'rerun': r['status']})
        elif o and not r:
            removed_claims.append({'claim': key[1], 'category': key[0],
                                   'status': o['status']})
        else:
            new_claims.append({'claim': key[1], 'category': key[0],
                               'status': r['status']})

    return {'unchanged': unchanged, 'upgraded': upgraded, 'downgraded': downgraded,
            'new_claims': new_claims, 'removed_claims': removed_claims}


# ============================================================
# OUTPUT FORMATTING
# ============================================================

def format_text_report(rerun_results, total_history, skipped_count):
    """Format human-readable comparison report."""
    batch_ts = rerun_results[0]['batch'] if rerun_results else '?'
    lines = []
    lines.append('')
    lines.append('=' * 64)
    lines.append('  AUDIT RERUN REPORT')
    lines.append(f'  Batch: {batch_ts}')
    lines.append(f'  Reruns: {len(rerun_results)} of {total_history} entries'
                 f' ({skipped_count} baselines skipped)')
    lines.append('=' * 64)
    lines.append('')

    # Summary table
    lines.append('  Run | Original Rate | Rerun Rate | Delta  | Match')
    lines.append('  ----|---------------|------------|--------|------')

    exact_count = 0
    diff_runs = []

    for r in rerun_results:
        run_num = r['rerun_of']
        if r.get('status') == 'SKIPPED':
            lines.append(f'  {run_num:3d} |  SKIPPED      |            |        | {r.get("reason", "?")}')
            continue
        if r.get('status') == 'FAILED':
            lines.append(f'  {run_num:3d} |  FAILED       |            |        | auditor error')
            continue

        comp = r['comparison']
        o_pct = comp['rate_original'] * 100
        r_pct = comp['rate_rerun'] * 100
        delta = comp['rate_delta'] * 100
        match = comp['rate_match']

        if match:
            exact_count += 1
            match_str = 'YES'
        else:
            match_str = 'NO'
            diff_runs.append(r)

        delta_str = f'{delta:+.1f}pp' if not match else '  0pp'
        lines.append(f'  {run_num:3d} |       {o_pct:5.1f}%  |     {r_pct:5.1f}% | {delta_str:>6s} |  {match_str}')

    # Per-run diffs (if any)
    for r in diff_runs:
        run_num = r['rerun_of']
        claim_diffs = r.get('claim_diffs', {})
        cat_deltas = r.get('category_deltas', [])

        changes = []
        for u in claim_diffs.get('upgraded', []):
            changes.append(f'    [UPGRADED]  {u["category"]} / "{u["claim"][:50]}"  '
                          f'{u["original"]} -> {u["rerun"]}')
        for d in claim_diffs.get('downgraded', []):
            changes.append(f'    [DOWNGRADED]  {d["category"]} / "{d["claim"][:50]}"  '
                          f'{d["original"]} -> {d["rerun"]}')

        if changes:
            lines.append('')
            lines.append(f'  --- Run {run_num}: Claim Diffs ({len(changes)} changes) ---')
            lines.extend(changes)

        cat_changes = [c for c in cat_deltas if c['changed']]
        if cat_changes:
            lines.append('')
            lines.append(f'  --- Run {run_num}: Category Deltas ---')
            for c in cat_changes:
                lines.append(f'    {c["category"]:25s} {c["original_rate"]:.0%} -> '
                            f'{c["rerun_rate"]:.0%}  ({c["delta"]:+.1%})')

    # Final summary
    run_count = sum(1 for r in rerun_results
                    if r.get('status') not in ('SKIPPED', 'FAILED'))
    lines.append('')
    lines.append('=' * 64)
    lines.append(f'  RESULT: {exact_count}/{run_count} runs reproduced exactly')
    lines.append('=' * 64)
    lines.append('')

    return '\n'.join(lines)


def format_json_output(rerun_results):
    """Format results as JSON."""
    return json.dumps(rerun_results, indent=2, ensure_ascii=False)


# ============================================================
# PERSISTENCE
# ============================================================

def save_rerun_history(archive_dir, rerun_results):
    """Append rerun results to audit_rerun_history.jsonl."""
    history_path = Path(archive_dir) / 'audit_rerun_history.jsonl'
    with open(history_path, 'a', encoding='utf-8') as f:
        for entry in rerun_results:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    print(f"Saved {len(rerun_results)} rerun entries to {history_path}",
          file=sys.stderr)


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Rerun stored audits and compare results side-by-side.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python context_rerunner.py --project-path F:/Better_Compaction_Protocol
  python context_rerunner.py --run 4 --run 5
  python context_rerunner.py --dry-run
  python context_rerunner.py --format json"""
    )
    parser.add_argument('--archive',
                        help='Path to context_archive/ directory')
    parser.add_argument('--project-path', default=None,
                        help='Project root for finding .jsonl files (default: CWD)')
    parser.add_argument('--run', type=int, action='append', dest='runs',
                        help='Specific run number(s) to rerun (repeatable)')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                        dest='output_format',
                        help='Output format (default: text)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show which runs would be rerun without executing')
    args = parser.parse_args()

    # Resolve paths
    project_path = args.project_path or os.getcwd()
    if args.archive:
        archive_dir = Path(args.archive)
    else:
        archive_dir = Path(project_path) / 'context_archive'
    if not archive_dir.is_dir():
        print(f"ERROR: Archive directory not found: {archive_dir}", file=sys.stderr)
        sys.exit(1)

    # Load history
    history = load_history(archive_dir)
    if not history:
        print("ERROR: No audit history found", file=sys.stderr)
        sys.exit(1)

    total_history = len(history)
    rerunnable = filter_entries(history, args.runs)
    skipped_count = total_history - len(rerunnable)

    if not rerunnable:
        print("No rerunnable entries found", file=sys.stderr)
        sys.exit(0)

    # Find .jsonl files
    try:
        jsonl_dir = context_preserver.find_project_dir(project_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {jsonl_dir} for compaction summaries...", file=sys.stderr)
    compaction_index = build_compaction_index(jsonl_dir)
    print(f"Found {len(compaction_index)} compaction summaries", file=sys.stderr)

    # Dry run
    if args.dry_run:
        print(f"\nDry run: {len(rerunnable)} entries to rerun, "
              f"{skipped_count} baselines skipped\n", file=sys.stderr)
        for run_num, entry in rerunnable:
            match = match_entry_to_compaction(entry, compaction_index)
            status = "MATCHED" if match else "NO MATCH"
            rate = entry.get('summary', {}).get('rate', 0)
            print(f"  Run {run_num}: rate={rate:.1%}, "
                  f"ts={entry.get('timestamp', '?')}, {status}",
                  file=sys.stderr)
        sys.exit(0)

    # Execute reruns
    batch_id = datetime.now(timezone.utc).isoformat()
    rerun_results = []

    for run_num, entry in rerunnable:
        print(f"Rerunning Run {run_num}...", file=sys.stderr)

        match = match_entry_to_compaction(entry, compaction_index)
        if not match:
            rerun_results.append({
                'rerun_of': run_num,
                'batch': batch_id,
                'status': 'SKIPPED',
                'reason': 'compaction not found',
            })
            continue

        rerun_structured = execute_rerun(match, archive_dir)
        if rerun_structured is None:
            rerun_results.append({
                'rerun_of': run_num,
                'batch': batch_id,
                'status': 'FAILED',
                'reason': 'auditor error',
            })
            continue

        # Compare
        comparison = compare_summaries(entry, rerun_structured)
        cat_deltas = compare_categories(entry, rerun_structured)
        claim_diffs = compare_claims(
            entry.get('claims', []),
            rerun_structured.get('claims', []),
        )

        rerun_results.append({
            'rerun_of': run_num,
            'batch': batch_id,
            'rerun_timestamp': datetime.now(timezone.utc).isoformat(),
            'original_summary': entry.get('summary', {}),
            'rerun_summary': rerun_structured.get('summary', {}),
            'comparison': comparison,
            'category_deltas': cat_deltas,
            'claim_diffs': claim_diffs,
            'reproduced': comparison['rate_match'],
        })

    # Save
    save_rerun_history(archive_dir, rerun_results)

    # Output
    if args.output_format == 'json':
        print(format_json_output(rerun_results))
    else:
        print(format_text_report(rerun_results, total_history, skipped_count))


import os

if __name__ == '__main__':
    main()
