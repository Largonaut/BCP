#!/usr/bin/env python3
"""
BCP Dashboard — Development companion for the Better Compaction Protocol toolkit.

Standalone tkinter application. Pure stdlib, zero dependencies.
Reads semantic_map.json, audit_history.jsonl, and context_archive/ files.
Runs BCP tools via subprocess with output displayed in-app.

Usage:
    python F:/claude_tools/bcp_dashboard.py [--project-path PATH]
"""

import json
import os
import re
import subprocess
import sys
import threading
import argparse
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime

# Force UTF-8 on Windows
if sys.platform == 'win32':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT = Path('F:/Better_Compaction_Protocol')

# Characters prohibited in Windows filenames + our separator + whitespace
PROHIBITED = set('\\/:*?"<>|~\t\n\r\x0b\x0c ')

# BCP tools with default argument templates
# {project} and {archive} are replaced at runtime
TOOLS = [
    {
        'name': 'Context Preserver',
        'script': 'context_preserver.py',
        'desc': 'Archive .jsonl transcripts to readable .md files',
        'default_args': '--project-path {project}',
    },
    {
        'name': 'Context Searcher',
        'script': 'context_searcher.py',
        'desc': 'Search and navigate archived session files',
        'default_args': 'search --archive {archive} --keyword ',
    },
    {
        'name': 'Context Auditor',
        'script': 'context_auditor.py',
        'desc': 'Audit compaction summaries against archive',
        'default_args': '--deep --archive {archive}',
    },
    {
        'name': 'Context Autoarchive',
        'script': 'context_autoarchive.py',
        'desc': 'Compaction-aware auto-archival orchestrator',
        'default_args': '--phase post --project-path {project}',
    },
    {
        'name': 'Context Rerunner',
        'script': 'context_rerunner.py',
        'desc': 'Audit reproducibility checker',
        'default_args': '--project-path {project}',
    },
]


# ---------------------------------------------------------------------------
# Character pool
# ---------------------------------------------------------------------------

def build_character_pool():
    """Build valid filename characters organized by Unicode block.

    Returns list of (section_name, [chars]) tuples.
    """
    sections = []

    def _collect(start, end):
        out = []
        for i in range(start, end):
            c = chr(i)
            if c.isprintable() and c not in PROHIBITED and not c.isspace():
                out.append(c)
        return out

    sections.append(('ASCII', _collect(33, 127)))
    sections.append(('Latin-1 Supplement', _collect(161, 256)))
    sections.append(('Latin Extended-A', _collect(256, 384)))
    sections.append(('Greek', _collect(880, 1024)))
    sections.append(('Cyrillic', _collect(1024, 1280)))
    sections.append(('Currency', _collect(8352, 8400)))
    sections.append(('Arrows', _collect(8592, 8704)))
    sections.append(('Math Operators', _collect(8704, 8960)))
    sections.append(('Box Drawing', _collect(9472, 9600)))
    sections.append(('Geometric Shapes', _collect(9632, 9728)))
    sections.append(('Misc Symbols', _collect(9728, 9984)))

    # Filter out empty sections
    return [(name, chars) for name, chars in sections if chars]


# ---------------------------------------------------------------------------
# Semantic Map tab
# ---------------------------------------------------------------------------

class SemanticMapTab:
    """Displays the full character pool with mapped/unmapped highlighting."""

    CHARS_PER_ROW = 32

    def __init__(self, notebook, app):
        self.app = app
        self.frame = ttk.Frame(notebook)

        # Summary bar
        summary_frame = ttk.Frame(self.frame)
        summary_frame.pack(fill='x', padx=8, pady=(6, 2))
        self.summary_var = tk.StringVar()
        ttk.Label(summary_frame, textvariable=self.summary_var,
                  font=('Segoe UI', 10, 'bold')).pack(side='left')
        ttk.Button(summary_frame, text='Export Map',
                   command=self._export_map).pack(side='right')

        # Detail bar (shows info about clicked character)
        self.detail_var = tk.StringVar(value='Click a character for details')
        ttk.Label(self.frame, textvariable=self.detail_var,
                  font=('Segoe UI', 10)).pack(anchor='w', padx=8, pady=(0, 4))

        # Scrollable text widget for the character grid
        text_frame = ttk.Frame(self.frame)
        text_frame.pack(fill='both', expand=True, padx=4, pady=4)

        self.text = tk.Text(text_frame, wrap='word', cursor='arrow',
                            font=('Consolas', 13), state='disabled',
                            spacing1=2, spacing3=2)
        scrollbar = ttk.Scrollbar(text_frame, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.text.pack(side='left', fill='both', expand=True)

        # Tags for styling
        self.text.tag_configure('section_header', font=('Segoe UI', 11, 'bold'),
                                foreground='#1a5276')
        self.text.tag_configure('mapped', background='#abebc6', foreground='#1e8449',
                                font=('Consolas', 13, 'bold'))
        self.text.tag_configure('unmapped', background='#f2f3f4', foreground='#aab7b8',
                                font=('Consolas', 13))
        self.text.tag_configure('spacer', font=('Consolas', 6))

        # Bind click
        self.text.tag_bind('mapped', '<Button-1>', self._on_char_click)
        self.text.tag_bind('unmapped', '<Button-1>', self._on_char_click)

        self.char_positions = {}  # tag_name -> char

    def refresh(self):
        mappings = self.app.semantic_map.get('mappings', {})
        reverse_map = {c: topic for c, topic in mappings.items()}
        pool = build_character_pool()

        total = sum(len(chars) for _, chars in pool)
        mapped_count = len(mappings)
        unmapped_count = total - mapped_count

        self.summary_var.set(
            f'{mapped_count} mapped  /  {unmapped_count} unmapped  /  {total} total characters')

        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.char_positions.clear()

        for section_name, chars in pool:
            self.text.insert('end', f'\n{section_name}', 'section_header')
            self.text.insert('end', f'  ({len(chars)} chars)\n', 'section_header')

            for i, c in enumerate(chars):
                tag_id = f'c_{ord(c)}'
                if c in reverse_map:
                    self.text.insert('end', f' {c} ', ('mapped', tag_id))
                else:
                    self.text.insert('end', f' {c} ', ('unmapped', tag_id))
                self.char_positions[tag_id] = c

                if (i + 1) % self.CHARS_PER_ROW == 0:
                    self.text.insert('end', '\n')

                # Bind individual character tag
                self.text.tag_bind(tag_id, '<Button-1>', self._on_char_click)

            self.text.insert('end', '\n')

        self.text.configure(state='disabled')

    def _export_map(self):
        mappings = self.app.semantic_map.get('mappings', {})
        pool = build_character_pool()
        total = sum(len(chars) for _, chars in pool)

        lines = [f'Semantic Map Export — {len(mappings)} mapped / '
                 f'{total - len(mappings)} unmapped / {total} total\n']
        lines.append('MAPPED CHARACTERS:')
        for char, topic in sorted(mappings.items(), key=lambda x: x[1].lower()):
            lines.append(f'  {char}  (U+{ord(char):04X})  →  {topic}')
        lines.append(f'\nUNMAPPED ({total - len(mappings)} available)')
        for section_name, chars in pool:
            unmapped = [c for c in chars if c not in mappings]
            if unmapped:
                lines.append(f'  {section_name}: {"  ".join(unmapped)}')
        try:
            path = self.app.export_file('semantic_map_export', '\n'.join(lines))
            self.detail_var.set(f'Exported: {path.name}')
        except OSError as e:
            messagebox.showerror('Export Error', str(e))

    def _on_char_click(self, event):
        # Find which character tag was clicked
        idx = self.text.index(f'@{event.x},{event.y}')
        tags = self.text.tag_names(idx)
        for t in tags:
            if t.startswith('c_'):
                c = self.char_positions.get(t, '')
                if c:
                    mappings = self.app.semantic_map.get('mappings', {})
                    if c in mappings:
                        self.detail_var.set(
                            f'Character: {c}  (U+{ord(c):04X})    '
                            f'Topic: {mappings[c]}    Status: MAPPED')
                    else:
                        self.detail_var.set(
                            f'Character: {c}  (U+{ord(c):04X})    '
                            f'Status: unmapped — available for assignment')
                break


# ---------------------------------------------------------------------------
# Blacklist tab
# ---------------------------------------------------------------------------

class BlacklistTab:
    """View and edit the semantic_map.json blacklist."""

    def __init__(self, notebook, app):
        self.app = app
        self.frame = ttk.Frame(notebook)

        ttk.Label(self.frame, text='Blacklisted words are excluded from topic extraction',
                  font=('Segoe UI', 10)).pack(anchor='w', padx=8, pady=(8, 4))

        self.count_var = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.count_var,
                  font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=8, pady=(0, 4))

        # List + scrollbar
        list_frame = ttk.Frame(self.frame)
        list_frame.pack(fill='both', expand=True, padx=8, pady=4)

        self.listbox = tk.Listbox(list_frame, font=('Consolas', 11),
                                  selectmode='extended')
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.listbox.pack(side='left', fill='both', expand=True)

        # Add / Remove controls
        ctrl_frame = ttk.Frame(self.frame)
        ctrl_frame.pack(fill='x', padx=8, pady=(4, 8))

        ttk.Label(ctrl_frame, text='Add word:').pack(side='left')
        self.add_var = tk.StringVar()
        add_entry = ttk.Entry(ctrl_frame, textvariable=self.add_var, width=25)
        add_entry.pack(side='left', padx=4)
        add_entry.bind('<Return>', lambda e: self._add_word())

        ttk.Button(ctrl_frame, text='Add', command=self._add_word).pack(side='left', padx=2)
        ttk.Button(ctrl_frame, text='Remove Selected',
                   command=self._remove_selected).pack(side='left', padx=8)
        ttk.Button(ctrl_frame, text='Export List',
                   command=self._export_list).pack(side='right')

    def refresh(self):
        words = sorted(self.app.semantic_map.get('blacklist', []),
                       key=str.lower)
        self.listbox.delete(0, 'end')
        for w in words:
            self.listbox.insert('end', w)
        self.count_var.set(f'{len(words)} words blacklisted')

    def _add_word(self):
        word = self.add_var.get().strip().lower()
        if not word:
            return
        bl = self.app.semantic_map.setdefault('blacklist', [])
        if word not in bl:
            bl.append(word)
            bl.sort(key=str.lower)
            self.app.save_semantic_map()
            self.refresh()
        self.add_var.set('')

    def _remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        words_to_remove = [self.listbox.get(i) for i in sel]
        bl = self.app.semantic_map.get('blacklist', [])
        for w in words_to_remove:
            if w in bl:
                bl.remove(w)
        self.app.save_semantic_map()
        self.refresh()

    def _export_list(self):
        words = sorted(self.app.semantic_map.get('blacklist', []), key=str.lower)
        if not words:
            return
        content = f'Blacklist Export — {len(words)} words\n\n' + '\n'.join(words)
        try:
            path = self.app.export_file('blacklist_export', content)
            self.count_var.set(f'{len(words)} words blacklisted — exported: {path.name}')
        except OSError as e:
            messagebox.showerror('Export Error', str(e))


# ---------------------------------------------------------------------------
# Tools tab
# ---------------------------------------------------------------------------

class ToolsTab:
    """Run BCP tools and display output with color coding."""

    def __init__(self, notebook, app):
        self.app = app
        self.frame = ttk.Frame(notebook)
        self.running_proc = None

        # Tool selector
        top = ttk.Frame(self.frame)
        top.pack(fill='x', padx=8, pady=(8, 4))

        ttk.Label(top, text='Tool:').pack(side='left')
        self.tool_var = tk.StringVar()
        tool_names = [t['name'] for t in TOOLS]
        self.tool_combo = ttk.Combobox(top, textvariable=self.tool_var,
                                       values=tool_names, state='readonly', width=25)
        self.tool_combo.pack(side='left', padx=4)
        self.tool_combo.bind('<<ComboboxSelected>>', self._on_tool_select)

        self.desc_var = tk.StringVar()
        ttk.Label(top, textvariable=self.desc_var,
                  font=('Segoe UI', 9, 'italic')).pack(side='left', padx=8)

        # Arguments
        args_frame = ttk.Frame(self.frame)
        args_frame.pack(fill='x', padx=8, pady=4)

        ttk.Label(args_frame, text='Arguments:').pack(side='left')
        self.args_var = tk.StringVar()
        self.args_entry = ttk.Entry(args_frame, textvariable=self.args_var, width=80)
        self.args_entry.pack(side='left', padx=4, fill='x', expand=True)
        self.args_entry.bind('<Return>', lambda e: self._run_tool())

        # Buttons
        btn_frame = ttk.Frame(self.frame)
        btn_frame.pack(fill='x', padx=8, pady=4)

        self.run_btn = ttk.Button(btn_frame, text='Run', command=self._run_tool)
        self.run_btn.pack(side='left', padx=2)
        ttk.Button(btn_frame, text='Clear Output', command=self._clear_output).pack(
            side='left', padx=2)
        ttk.Button(btn_frame, text='Export Log', command=self._export_log).pack(
            side='left', padx=2)
        self.status_var = tk.StringVar()
        ttk.Label(btn_frame, textvariable=self.status_var,
                  font=('Segoe UI', 9)).pack(side='left', padx=12)

        # Output viewer
        out_frame = ttk.Frame(self.frame)
        out_frame.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        self.output = tk.Text(out_frame, wrap='word', font=('Consolas', 10),
                              state='disabled', background='#1e1e1e',
                              foreground='#d4d4d4', insertbackground='#d4d4d4')
        out_sb = ttk.Scrollbar(out_frame, orient='vertical', command=self.output.yview)
        self.output.configure(yscrollcommand=out_sb.set)
        out_sb.pack(side='right', fill='y')
        self.output.pack(side='left', fill='both', expand=True)

        # Color tags for output
        self.output.tag_configure('found', foreground='#4ec9b0')
        self.output.tag_configure('deep', foreground='#dcdcaa')
        self.output.tag_configure('missing', foreground='#f44747')
        self.output.tag_configure('mismatch', foreground='#ce9178')
        self.output.tag_configure('header', foreground='#569cd6', font=('Consolas', 10, 'bold'))
        self.output.tag_configure('critical', foreground='#f44747', font=('Consolas', 10, 'bold'))
        self.output.tag_configure('major', foreground='#ce9178', font=('Consolas', 10, 'bold'))
        self.output.tag_configure('info', foreground='#608b4e')
        self.output.tag_configure('separator', foreground='#569cd6')
        self.output.tag_configure('timestamp', foreground='#808080',
                                  font=('Consolas', 9, 'italic'))

        # Select first tool
        if tool_names:
            self.tool_combo.current(0)
            self._on_tool_select(None)

    def _on_tool_select(self, _event):
        idx = self.tool_combo.current()
        if idx < 0:
            return
        tool = TOOLS[idx]
        self.desc_var.set(tool['desc'])

        project = str(self.app.project_path)
        archive = str(self.app.project_path / 'context_archive')
        args = tool['default_args'].replace('{project}', project).replace('{archive}', archive)
        self.args_var.set(args)

    def _run_tool(self):
        if self.running_proc is not None:
            messagebox.showinfo('Busy', 'A tool is already running.')
            return

        idx = self.tool_combo.current()
        if idx < 0:
            return
        tool = TOOLS[idx]
        script = str(TOOLS_DIR / tool['script'])
        args_str = self.args_var.get().strip()

        cmd = [sys.executable, script] + args_str.split()

        # Add separator in output
        self.output.configure(state='normal')
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.output.insert('end', f'\n{"="*64}\n', 'separator')
        self.output.insert('end', f'  [{ts}] Running: {tool["name"]}\n', 'timestamp')
        self.output.insert('end', f'  {" ".join(cmd)}\n', 'timestamp')
        self.output.insert('end', f'{"="*64}\n', 'separator')
        self.output.configure(state='disabled')

        self.run_btn.configure(state='disabled')
        self.status_var.set('Running...')

        # Run in background thread
        thread = threading.Thread(target=self._execute, args=(cmd,), daemon=True)
        thread.start()

    def _execute(self, cmd):
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            self.running_proc = proc

            for line in proc.stdout:
                self.frame.after(0, self._append_line, line)

            proc.wait()
            exit_code = proc.returncode
            self.frame.after(0, self._on_finished, exit_code)

        except Exception as e:
            self.frame.after(0, self._append_line, f'ERROR: {e}\n')
            self.frame.after(0, self._on_finished, -1)

    def _append_line(self, line):
        self.output.configure(state='normal')
        tag = self._classify_line(line)
        self.output.insert('end', line, tag)
        self.output.see('end')
        self.output.configure(state='disabled')

    def _classify_line(self, line):
        stripped = line.strip()
        if stripped.startswith('===') or stripped.startswith('---'):
            return 'separator'
        if '[FOUND]' in line:
            return 'found'
        if '[DEEP]' in line:
            return 'deep'
        if '[MISSING]' in line:
            return 'missing'
        if '[MISMATCH]' in line:
            return 'mismatch'
        if 'CRITICAL' in line:
            return 'critical'
        if 'MAJOR' in line:
            return 'major'
        if re.match(r'\s*(Verification rate|Severity-weighted|TOTALS)', line):
            return 'header'
        return ''

    def _on_finished(self, exit_code):
        self.running_proc = None
        self.run_btn.configure(state='normal')
        if exit_code == 0:
            self.status_var.set('Done (exit 0)')
        else:
            self.status_var.set(f'Done (exit {exit_code})')

    def _export_log(self):
        content = self.output.get('1.0', 'end').strip()
        if not content:
            self.status_var.set('Nothing to export')
            return
        try:
            path = self.app.export_file('tool_log', content)
            self.status_var.set(f'Exported: {path.name}')
        except OSError as e:
            messagebox.showerror('Export Error', str(e))

    def _clear_output(self):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')


# ---------------------------------------------------------------------------
# Audit History tab
# ---------------------------------------------------------------------------

class AuditHistoryTab:
    """Displays audit_history.jsonl trend and per-run details."""

    def __init__(self, notebook, app):
        self.app = app
        self.frame = ttk.Frame(notebook)
        self.runs = []

        # Trend display
        trend_frame = ttk.LabelFrame(self.frame, text='Audit Accuracy Trend')
        trend_frame.pack(fill='x', padx=8, pady=(8, 4))

        trend_top = ttk.Frame(trend_frame)
        trend_top.pack(fill='x', padx=8, pady=6)
        self.trend_var = tk.StringVar()
        ttk.Label(trend_top, textvariable=self.trend_var,
                  font=('Consolas', 12, 'bold')).pack(side='left')
        ttk.Button(trend_top, text='Export Report',
                   command=self._export_report).pack(side='right')

        # Trend bar chart (Canvas)
        self.canvas = tk.Canvas(trend_frame, height=120, background='#f8f9fa')
        self.canvas.pack(fill='x', padx=8, pady=(0, 8))

        # Run details table
        table_frame = ttk.LabelFrame(self.frame, text='Run Details')
        table_frame.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        cols = ('run', 'date', 'rate', 'weighted', 'files', 'tools',
                'quotes', 'topics', 'turns', 'functions')
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings', height=12)

        col_config = [
            ('run', 'Run', 45), ('date', 'Date', 90), ('rate', 'Rate', 60),
            ('weighted', 'Weighted', 75), ('files', 'Files', 55),
            ('tools', 'Tools', 55), ('quotes', 'Quotes', 60),
            ('topics', 'Topics', 60), ('turns', 'Turns', 55),
            ('functions', 'Funcs', 55),
        ]
        for col_id, heading, width in col_config:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, anchor='center')

        tree_sb = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)

        # Detail panel
        self.detail_var = tk.StringVar()
        ttk.Label(self.frame, textvariable=self.detail_var,
                  font=('Consolas', 9), wraplength=900,
                  justify='left').pack(anchor='w', padx=8, pady=(0, 4))

        self.tree.bind('<<TreeviewSelect>>', self._on_select)

    def refresh(self):
        history_path = self.app.project_path / 'context_archive' / 'audit_history.jsonl'
        self.runs = []
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self.runs.append(json.loads(line))
            except (json.JSONDecodeError, OSError):
                pass

        # Update trend line
        rates = []
        for run in self.runs:
            summary = run.get('summary', {})
            rate = summary.get('rate', 0)
            if isinstance(rate, (int, float)):
                rates.append(round(rate * 100) if rate <= 1 else round(rate))
            else:
                rates.append(0)

        if rates:
            trend_str = ' \u2192 '.join(f'{r}%' for r in rates)
            self.trend_var.set(trend_str)
        else:
            self.trend_var.set('No audit history found')

        # Draw bar chart
        self._draw_bars(rates)

        # Populate table
        self.tree.delete(*self.tree.get_children())
        for run in self.runs:
            rn = run.get('run_number', '?')
            ts = run.get('timestamp', '')[:10]
            summary = run.get('summary', {})
            rate_val = summary.get('rate', 0)
            rate_pct = f'{rate_val*100:.0f}%' if isinstance(rate_val, float) and rate_val <= 1 else f'{rate_val}%'
            weighted = summary.get('severity_weighted_rate', '')
            if isinstance(weighted, float):
                weighted = f'{weighted*100:.0f}%'

            cats = run.get('categories', {})

            def cat_rate(name):
                c = cats.get(name, {})
                t = c.get('total', 0)
                if t == 0:
                    return 'n/a'
                return f'{c.get("found", 0)}/{t}'

            self.tree.insert('', 'end', values=(
                rn, ts, rate_pct, weighted,
                cat_rate('File Paths'), cat_rate('Tools Used'),
                cat_rate('User Quotes'), cat_rate('Topics'),
                cat_rate('Turn Counts'), cat_rate('Functions/Classes'),
            ))

    def _draw_bars(self, rates):
        self.canvas.delete('all')
        if not rates:
            return

        w = self.canvas.winfo_width() or 800
        h = 120
        n = len(rates)
        bar_w = max(20, min(60, (w - 40) // n))
        gap = max(4, bar_w // 4)
        total_w = n * (bar_w + gap) - gap
        x_start = max(10, (w - total_w) // 2)

        for i, rate in enumerate(rates):
            x = x_start + i * (bar_w + gap)
            bar_h = max(2, (rate / 100) * (h - 30))
            y_top = h - 15 - bar_h

            # Color by rate
            if rate >= 80:
                color = '#27ae60'
            elif rate >= 60:
                color = '#f39c12'
            else:
                color = '#e74c3c'

            self.canvas.create_rectangle(x, y_top, x + bar_w, h - 15,
                                         fill=color, outline='')
            self.canvas.create_text(x + bar_w // 2, h - 5, text=f'{rate}%',
                                    font=('Consolas', 8), fill='#2c3e50')
            self.canvas.create_text(x + bar_w // 2, y_top - 8,
                                    text=f'R{i+1}', font=('Consolas', 7),
                                    fill='#7f8c8d')

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx < len(self.runs):
            run = self.runs[idx]
            summary = run.get('summary', {})
            self.detail_var.set(
                f'Run {run.get("run_number", "?")}: '
                f'{summary.get("found", 0)} found / '
                f'{summary.get("missing", 0)} missing / '
                f'{summary.get("mismatched", 0)} mismatched   '
                f'Archive: {run.get("archive_file", "?")}')

    def _export_report(self):
        if not self.runs:
            return
        lines = ['Audit History Report', '=' * 60, '',
                 f'Trend: {self.trend_var.get()}', '']

        # Table header
        header = f'{"Run":>5} {"Date":>12} {"Rate":>7} {"Weighted":>9} ' \
                 f'{"Files":>7} {"Tools":>7} {"Quotes":>8} ' \
                 f'{"Topics":>8} {"Turns":>7} {"Funcs":>7}'
        lines.append(header)
        lines.append('-' * len(header))

        for item_id in self.tree.get_children():
            vals = self.tree.item(item_id, 'values')
            lines.append(f'{vals[0]:>5} {vals[1]:>12} {vals[2]:>7} {vals[3]:>9} '
                         f'{vals[4]:>7} {vals[5]:>7} {vals[6]:>8} '
                         f'{vals[7]:>8} {vals[8]:>7} {vals[9]:>7}')

        try:
            path = self.app.export_file('audit_report', '\n'.join(lines))
            self.detail_var.set(f'Exported: {path.name}')
        except OSError as e:
            messagebox.showerror('Export Error', str(e))


# ---------------------------------------------------------------------------
# Archive tab
# ---------------------------------------------------------------------------

class ArchiveTab:
    """Browse context_archive/ files with metadata."""

    def __init__(self, notebook, app):
        self.app = app
        self.frame = ttk.Frame(notebook)

        top_frame = ttk.Frame(self.frame)
        top_frame.pack(fill='x', padx=8, pady=(8, 4))
        self.count_var = tk.StringVar()
        ttk.Label(top_frame, textvariable=self.count_var,
                  font=('Segoe UI', 10, 'bold')).pack(side='left')
        ttk.Button(top_frame, text='Export Listing',
                   command=self._export_listing).pack(side='right')

        # File table
        cols = ('filename', 'date', 'session_id', 'tags', 'version')
        self.tree = ttk.Treeview(self.frame, columns=cols, show='headings', height=20)

        col_config = [
            ('filename', 'Filename', 420), ('date', 'Date', 90),
            ('session_id', 'Session ID', 100), ('tags', 'Semantic Tags', 180),
            ('version', 'Version', 80),
        ]
        for col_id, heading, width in col_config:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width)

        tree_sb = ttk.Scrollbar(self.frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        self.tree.bind('<Double-1>', self._on_double_click)
        self.files = []

    def refresh(self):
        archive_dir = self.app.project_path / 'context_archive'
        self.tree.delete(*self.tree.get_children())
        self.files = []

        if not archive_dir.is_dir():
            self.count_var.set('No context_archive/ found')
            return

        md_files = sorted(archive_dir.glob('*.md'), reverse=True)
        self.count_var.set(f'{len(md_files)} archive files')

        for fp in md_files:
            name = fp.name
            info = self._parse_filename(name)
            self.tree.insert('', 'end', values=(
                name, info['date'], info['session_id'],
                info['tags'], info['version'],
            ))
            self.files.append(fp)

    def _parse_filename(self, name):
        """Extract metadata from archive filename."""
        info = {'date': '', 'session_id': '', 'tags': '', 'version': 'base'}

        # Detect enrichment version
        if '.enriched' in name:
            m = re.search(r'\.enriched(\d*)\.md', name)
            if m:
                v = m.group(1)
                info['version'] = f'enriched{v}' if v else 'enriched'
        elif name.endswith('.md'):
            info['version'] = 'base'

        # Parse session_DATE_ID~TAGS.ext pattern
        m = re.match(r'session_(\d{4}-\d{2}-\d{2})_([a-f0-9]+)', name)
        if m:
            info['date'] = m.group(1)
            info['session_id'] = m.group(2)[:8]

        # Tags after ~
        tilde_idx = name.find('~')
        if tilde_idx >= 0:
            dot_idx = name.find('.', tilde_idx)
            if dot_idx >= 0:
                info['tags'] = name[tilde_idx + 1:dot_idx]
            else:
                info['tags'] = name[tilde_idx + 1:]

        return info

    def _on_double_click(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx < len(self.files):
            fp = self.files[idx]
            if sys.platform == 'win32':
                os.startfile(str(fp))
            else:
                subprocess.Popen(['xdg-open', str(fp)])

    def _export_listing(self):
        children = self.tree.get_children()
        if not children:
            return
        lines = ['Filename\tDate\tSession ID\tSemantic Tags\tVersion']
        for item_id in children:
            vals = self.tree.item(item_id, 'values')
            lines.append('\t'.join(str(v) for v in vals))
        try:
            path = self.app.export_file('archive_listing', '\n'.join(lines))
            self.count_var.set(f'{len(children)} archive files — exported: {path.name}')
        except OSError as e:
            messagebox.showerror('Export Error', str(e))


# ---------------------------------------------------------------------------
# Report Viewer tab
# ---------------------------------------------------------------------------

class ReportViewerTab:
    """Interactive viewer for compaction audit reports (bundled JSON + history)."""

    def __init__(self, notebook, app):
        self.app = app
        self.frame = ttk.Frame(notebook)
        self.reports = []  # list of (path_or_None, data_dict)

        # Top controls
        top = ttk.Frame(self.frame)
        top.pack(fill='x', padx=8, pady=(8, 4))
        self.count_var = tk.StringVar(value='No reports loaded')
        ttk.Label(top, textvariable=self.count_var,
                  font=('Segoe UI', 10, 'bold')).pack(side='left')
        ttk.Button(top, text='Export Report',
                   command=self._export_report).pack(side='right', padx=(4, 0))
        ttk.Button(top, text='Open JSON',
                   command=self._open_json).pack(side='right', padx=(4, 0))
        ttk.Button(top, text='Refresh',
                   command=self.refresh).pack(side='right')

        # PanedWindow: list (left) + detail (right)
        self.paned = ttk.PanedWindow(self.frame, orient='horizontal')
        self.paned.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        # Left panel: report list
        left = ttk.Frame(self.paned)
        cols = ('date', 'rate', 'weighted', 'session')
        self.tree = ttk.Treeview(left, columns=cols, show='headings', height=20)
        for col_id, heading, width in [
            ('date', 'Date', 130), ('rate', 'Rate', 60),
            ('weighted', 'Weighted', 75), ('session', 'Session ID', 100),
        ]:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width)

        tree_sb = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_sb.set)
        tree_sb.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        self.paned.add(left, weight=1)

        # Right panel: report detail viewer
        right = ttk.Frame(self.paned)
        self.detail = tk.Text(right, wrap='word', font=('Consolas', 10),
                              state='disabled', background='#1e1e1e',
                              foreground='#d4d4d4', insertbackground='#d4d4d4')
        det_sb = ttk.Scrollbar(right, orient='vertical', command=self.detail.yview)
        self.detail.configure(yscrollcommand=det_sb.set)
        det_sb.pack(side='right', fill='y')
        self.detail.pack(fill='both', expand=True)
        self.paned.add(right, weight=3)

        # Color tags (same scheme as ToolsTab)
        self.detail.tag_configure('found', foreground='#4ec9b0')
        self.detail.tag_configure('deep', foreground='#dcdcaa')
        self.detail.tag_configure('missing', foreground='#f44747')
        self.detail.tag_configure('mismatch', foreground='#ce9178')
        self.detail.tag_configure('header', foreground='#569cd6',
                                  font=('Consolas', 11, 'bold'))
        self.detail.tag_configure('subheader', foreground='#569cd6',
                                  font=('Consolas', 10, 'bold'))
        self.detail.tag_configure('critical', foreground='#f44747',
                                  font=('Consolas', 10, 'bold'))
        self.detail.tag_configure('major', foreground='#ce9178',
                                  font=('Consolas', 10, 'bold'))
        self.detail.tag_configure('info', foreground='#608b4e')
        self.detail.tag_configure('separator', foreground='#569cd6')
        self.detail.tag_configure('dim', foreground='#808080')
        self.detail.tag_configure('summary_bg', background='#252526')
        self.detail.tag_configure('regression', foreground='#f44747',
                                  font=('Consolas', 10, 'bold'))

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.reports = []

        reports_dir = self.app.project_path / 'context_archive' / 'compaction_reports'
        history_path = self.app.project_path / 'context_archive' / 'audit_history.jsonl'

        # Load bundled reports
        bundled_runs = set()
        if reports_dir.is_dir():
            for fp in sorted(reports_dir.glob('compaction_report_*.json'), reverse=True):
                try:
                    with open(fp, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    data['_source_path'] = str(fp)
                    self.reports.append(data)
                    rn = data.get('run_number')
                    if rn:
                        bundled_runs.add(rn)
                except (json.JSONDecodeError, OSError):
                    pass

        # Fallback: load from audit_history.jsonl for pre-bundler runs
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        entry = json.loads(line)
                        rn = entry.get('run_number', entry.get('run'))
                        if rn and rn not in bundled_runs:
                            # Build a simplified report-like dict from history
                            data = {
                                'report_version': 0,  # indicates legacy
                                'timestamp': entry.get('timestamp', ''),
                                'session_id': entry.get('session_id', '?'),
                                'run_number': rn,
                                'audit': {
                                    'rate': entry.get('summary', {}).get('rate', 0),
                                    'severity_weighted_rate': entry.get('summary', {}).get('severity_weighted_rate', 0),
                                    'categories': entry.get('categories', {}),
                                    'claims': entry.get('claims', []),
                                },
                                '_source_path': None,
                                '_legacy': True,
                            }
                            self.reports.append(data)
            except (json.JSONDecodeError, OSError):
                pass

        # Sort newest first (by run number descending)
        self.reports.sort(key=lambda d: d.get('run_number', 0), reverse=True)

        # Populate treeview
        for data in self.reports:
            ts = data.get('timestamp', '')[:16]  # YYYY-MM-DDTHH:MM
            audit = data.get('audit', {})
            rate = audit.get('rate', 0)
            rate_pct = f'{rate * 100:.0f}%' if isinstance(rate, float) and rate <= 1 else f'{rate}%'
            weighted = audit.get('severity_weighted_rate', '')
            if isinstance(weighted, float) and weighted <= 1:
                weighted = f'{weighted * 100:.0f}%'
            elif weighted:
                weighted = f'{weighted}%'
            sid = data.get('session_id', '?')[:8]

            iid = self.tree.insert('', 'end', values=(ts, rate_pct, weighted, sid))

            # Row coloring by accuracy
            rate_num = rate * 100 if isinstance(rate, float) and rate <= 1 else rate
            if rate_num >= 80:
                self.tree.item(iid, tags=('good',))
            elif rate_num >= 60:
                self.tree.item(iid, tags=('warn',))
            else:
                self.tree.item(iid, tags=('bad',))

        self.tree.tag_configure('good', foreground='#4ec9b0')
        self.tree.tag_configure('warn', foreground='#dcdcaa')
        self.tree.tag_configure('bad', foreground='#f44747')

        total = len(self.reports)
        bundled = len([r for r in self.reports if not r.get('_legacy')])
        if total == 0:
            self.count_var.set('No reports yet — reports are created on compaction')
        else:
            self.count_var.set(f'{total} reports ({bundled} bundled, {total - bundled} legacy)')

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx < len(self.reports):
            self._render_report(self.reports[idx])

    def _render_report(self, data):
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')

        run = data.get('run_number', '?')
        ts = data.get('timestamp', '?')
        sid = data.get('session_id', '?')
        audit = data.get('audit', {})
        rate = audit.get('rate', 0)
        rate_pct = rate * 100 if isinstance(rate, float) and rate <= 1 else rate
        weighted = audit.get('severity_weighted_rate', 0)
        weighted_pct = weighted * 100 if isinstance(weighted, float) and weighted <= 1 else weighted

        # 1. Header
        self._ins(f'  COMPACTION AUDIT REPORT  —  Run #{run}\n', 'header')
        self._ins(f'  Date: {ts}\n', 'dim')
        self._ins(f'  Session: {sid}\n', 'dim')
        self._ins(f'  Accuracy: {rate_pct:.0f}%', 'header')
        self._ins(f'  (severity-weighted: {weighted_pct:.0f}%)\n\n', 'dim')

        # 2. Trend
        trend = data.get('trend', [])
        if trend:
            self._ins('  TREND\n', 'subheader')
            parts = []
            for i, val in enumerate(trend):
                parts.append(f'{val}%')
            self._ins('  ' + ' \u2192 '.join(parts) + '\n\n', '')

        # 3. Regressions
        regressions = audit.get('regressions', [])
        if regressions:
            self._ins('  REGRESSIONS\n', 'regression')
            for reg in regressions:
                cat = reg.get('category', '?')
                prev = reg.get('previous', '?')
                curr = reg.get('current', '?')
                self._ins(f'  {cat}: {prev}% \u2192 {curr}%\n', 'regression')
            self._ins('\n', '')
        else:
            self._ins('  Regressions: None\n\n', 'info')

        # 4. Ground Truth (if available)
        gt = data.get('ground_truth')
        if gt:
            self._ins('  GROUND TRUTH (pre-compaction)\n', 'subheader')
            self._ins(f'  Turn count: {gt.get("turn_count", "?")}\n', '')
            dur = gt.get('duration', {})
            if dur:
                self._ins(f'  Duration: {dur.get("date", "?")} '
                          f'{dur.get("start", "?")} to {dur.get("end", "?")}\n', '')
            self._ins(f'  Archive: {gt.get("archive_file", "?")}\n', 'dim')
            topics = gt.get('topics', '')
            if topics:
                self._ins(f'  Topics: {topics}\n', '')
            files = gt.get('files_referenced', '')
            if files:
                self._ins(f'  Files: {files}\n', '')
            tools = gt.get('tools_used', '')
            if tools:
                self._ins(f'  Tools: {tools}\n', '')
            self._ins('\n', '')
        elif not data.get('_legacy'):
            self._ins('  Ground truth: not available (pre-phase did not run)\n\n', 'dim')

        # 5. Compaction Summary (if available)
        cs = data.get('compaction_summary')
        if cs:
            self._ins('  COMPACTION SUMMARY\n', 'subheader')
            self._ins(f'  Length: {cs.get("length", "?")} chars\n', 'dim')
            self._ins(f'  Timestamp: {cs.get("compaction_timestamp", "?")}\n\n', 'dim')
            text = cs.get('text', '')
            if text:
                # Show first 2000 chars with distinct background
                preview = text[:2000]
                if len(text) > 2000:
                    preview += f'\n... ({len(text) - 2000} more chars)'
                self._ins(preview + '\n\n', 'summary_bg')

        # 6. Audit Results by Category
        categories = audit.get('categories', {})
        claims = audit.get('claims', [])
        if categories:
            self._ins('  AUDIT RESULTS BY CATEGORY\n', 'subheader')
            self._ins('  ' + '-' * 50 + '\n', 'separator')
            for cat_name, cat_data in categories.items():
                cat_rate = cat_data.get('rate', 0)
                if isinstance(cat_rate, float) and cat_rate <= 1:
                    cat_rate = cat_rate * 100
                found = cat_data.get('found', 0)
                total = cat_data.get('total', 0)
                self._ins(f'  {cat_name}: {cat_rate:.0f}% ({found}/{total})\n', 'subheader')

                # Show claims for this category
                cat_claims = [c for c in claims if c.get('category') == cat_name]
                for claim in cat_claims:
                    status = claim.get('status', '?')
                    severity = claim.get('severity', '')
                    text = claim.get('claim', '?')
                    if 'FOUND' in status:
                        tag = 'found' if 'deep' not in status.lower() else 'deep'
                        marker = '[FOUND]' if tag == 'found' else '[DEEP]'
                    elif status == 'MISSING':
                        tag = 'missing'
                        marker = '[MISSING]'
                    else:
                        tag = 'mismatch'
                        marker = f'[{status}]'
                    sev_str = f' {severity}' if severity else ''
                    self._ins(f'    {marker}{sev_str} {text}\n', tag)
                self._ins('\n', '')

        # 7. Cross-Reference (ground truth vs audit)
        if gt and claims:
            self._ins('  CROSS-REFERENCE\n', 'subheader')
            gt_topics = gt.get('topics', '')
            if gt_topics:
                topic_claims = [c.get('claim', '') for c in claims
                                if c.get('category') == 'Topics']
                gt_list = [t.strip() for t in gt_topics.split(',') if t.strip()]
                matched = [t for t in gt_list if any(t.lower() in tc.lower()
                           for tc in topic_claims)]
                unmatched = [t for t in gt_list if t not in matched]
                if matched:
                    self._ins(f'  Topics in both ground truth and audit: {len(matched)}\n', 'info')
                if unmatched:
                    self._ins(f'  Topics in ground truth but not audited: {len(unmatched)}\n', 'dim')
                    for t in unmatched[:10]:
                        self._ins(f'    - {t}\n', 'dim')
            self._ins('\n', '')

        # Legacy indicator
        if data.get('_legacy'):
            self._ins('  (Legacy report — loaded from audit_history.jsonl, '
                      'no bundled data available)\n', 'dim')

        self.detail.configure(state='disabled')
        self.detail.see('1.0')

    def _ins(self, text, tag=''):
        """Insert text with optional tag into detail viewer."""
        if tag:
            self.detail.insert('end', text, tag)
        else:
            self.detail.insert('end', text)

    def _open_json(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('No Selection', 'Select a report first.')
            return
        idx = self.tree.index(sel[0])
        if idx < len(self.reports):
            path = self.reports[idx].get('_source_path')
            if path:
                if sys.platform == 'win32':
                    os.startfile(path)
                else:
                    subprocess.Popen(['xdg-open', path])
            else:
                messagebox.showinfo('Legacy Report',
                                    'This report was loaded from audit_history.jsonl.\n'
                                    'No JSON file available.')

    def _export_report(self):
        """Export the currently displayed report as a text file."""
        content = self.detail.get('1.0', 'end').strip()
        if not content:
            return
        try:
            path = self.app.export_file('report_export', content)
            self.count_var.set(f'Exported: {path.name}')
        except OSError as e:
            messagebox.showerror('Export Error', str(e))


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class BCPDashboard:
    """Main dashboard application."""

    def __init__(self, root, project_path=None):
        self.root = root
        self.root.title('BCP Dashboard')

        self.config_path = TOOLS_DIR / 'bcp_dashboard_config.json'
        self.config = self._load_config()

        # Set project path: CLI arg > config > default
        if project_path:
            self.project_path = Path(project_path)
        elif 'project_path' in self.config:
            self.project_path = Path(self.config['project_path'])
        else:
            self.project_path = DEFAULT_PROJECT

        # Restore window geometry
        geo = self.config.get('geometry', '1200x800')
        self.root.geometry(geo)

        self.semantic_map = {}
        self.log_var = tk.StringVar(value='No logs exported yet')

        self._build_ui()
        self._load_data()
        self._apply_theme()

        # Save config on close
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

    def _load_config(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save_config(self):
        self.config['project_path'] = str(self.project_path)
        self.config['geometry'] = self.root.geometry()
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except OSError:
            pass

    def save_semantic_map(self):
        map_path = TOOLS_DIR / 'semantic_map.json'
        try:
            with open(map_path, 'w', encoding='utf-8') as f:
                json.dump(self.semantic_map, f, indent=2, ensure_ascii=False)
        except OSError as e:
            messagebox.showerror('Save Error', f'Failed to save semantic_map.json:\n{e}')

    def get_log_dir(self):
        """Return (and create) the dashboard log directory."""
        log_dir = self.project_path / 'context_archive' / 'dashboard_logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def export_file(self, prefix, content):
        """Write content to a timestamped file in the log dir. Returns path."""
        log_dir = self.get_log_dir()
        ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        path = log_dir / f'{prefix}_{ts}.txt'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.log_var.set(f'Last export: {path}')
        return path

    def _build_ui(self):
        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label='File', menu=file_menu)
        file_menu.add_command(label='Browse Project...',
                              command=self._browse_project, accelerator='Ctrl+O')
        file_menu.add_command(label='Open Archive Folder',
                              command=self._open_archive_folder)
        file_menu.add_command(label='Open Log Folder',
                              command=self._open_log_folder)
        file_menu.add_command(label='Open Reports Folder',
                              command=self._open_reports_folder)
        file_menu.add_separator()
        file_menu.add_command(label='Export Current Tab',
                              command=self._export_current_tab, accelerator='Ctrl+E')
        file_menu.add_separator()
        file_menu.add_command(label='Exit',
                              command=self._on_close, accelerator='Ctrl+Q')

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label='View', menu=view_menu)
        self.dark_mode_var = tk.BooleanVar(value=self.config.get('dark_mode', False))
        view_menu.add_checkbutton(label='Dark Mode', variable=self.dark_mode_var,
                                  command=self._toggle_dark_mode, accelerator='Ctrl+D')
        view_menu.add_separator()
        view_menu.add_command(label='Refresh All Tabs',
                              command=self._load_data, accelerator='F5')

        # Keyboard shortcuts
        self.root.bind('<Control-o>', lambda e: self._browse_project())
        self.root.bind('<Control-e>', lambda e: self._export_current_tab())
        self.root.bind('<Control-q>', lambda e: self._on_close())
        self.root.bind('<Control-d>', lambda e: self._toggle_dark_mode())
        self.root.bind('<F5>', lambda e: self._load_data())

        # Top bar: project path
        top = ttk.Frame(self.root)
        top.pack(fill='x', padx=8, pady=6)

        ttk.Label(top, text='Project:', font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.project_var = tk.StringVar(value=str(self.project_path))
        proj_entry = ttk.Entry(top, textvariable=self.project_var, width=65)
        proj_entry.pack(side='left', padx=6)
        ttk.Button(top, text='Browse...', command=self._browse_project).pack(side='left')
        ttk.Button(top, text='Refresh All', command=self._load_data).pack(side='left', padx=8)

        # Tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        self.tools_tab = ToolsTab(self.notebook, self)
        self.semantic_tab = SemanticMapTab(self.notebook, self)
        self.blacklist_tab = BlacklistTab(self.notebook, self)
        self.audit_tab = AuditHistoryTab(self.notebook, self)
        self.archive_tab = ArchiveTab(self.notebook, self)
        self.report_tab = ReportViewerTab(self.notebook, self)

        # Tools first — most immediately useful
        self.notebook.add(self.tools_tab.frame, text=' Tools ')
        self.notebook.add(self.semantic_tab.frame, text=' Semantic Map ')
        self.notebook.add(self.blacklist_tab.frame, text=' Blacklist ')
        self.notebook.add(self.audit_tab.frame, text=' Audit History ')
        self.notebook.add(self.report_tab.frame, text=' Reports ')
        self.notebook.add(self.archive_tab.frame, text=' Archive ')

        # Log directory indicator (bottom bar)
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill='x', padx=8, pady=(0, 4))
        ttk.Label(log_frame, textvariable=self.log_var,
                  font=('Segoe UI', 8), foreground='gray').pack(side='left')
        ttk.Button(log_frame, text='Open Log Folder',
                   command=self._open_log_folder).pack(side='right')

    def _browse_project(self):
        path = filedialog.askdirectory(initialdir=str(self.project_path))
        if path:
            self.project_path = Path(path)
            self.project_var.set(str(self.project_path))
            self._save_config()
            self._load_data()

    def _load_data(self):
        self.project_path = Path(self.project_var.get())
        self._load_semantic_map_data()
        self.semantic_tab.refresh()
        self.blacklist_tab.refresh()
        self.audit_tab.refresh()
        self.report_tab.refresh()
        self.archive_tab.refresh()

    def _load_semantic_map_data(self):
        map_path = TOOLS_DIR / 'semantic_map.json'
        if map_path.exists():
            try:
                with open(map_path, 'r', encoding='utf-8') as f:
                    self.semantic_map = json.load(f)
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self.semantic_map = {'mappings': {}, 'blacklist': []}

    def _open_log_folder(self):
        log_dir = self.get_log_dir()
        if sys.platform == 'win32':
            os.startfile(str(log_dir))
        else:
            subprocess.Popen(['xdg-open', str(log_dir)])

    def _open_archive_folder(self):
        archive_dir = self.project_path / 'context_archive'
        archive_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(archive_dir))
        else:
            subprocess.Popen(['xdg-open', str(archive_dir)])

    def _open_reports_folder(self):
        reports_dir = self.project_path / 'context_archive' / 'compaction_reports'
        reports_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(str(reports_dir))
        else:
            subprocess.Popen(['xdg-open', str(reports_dir)])

    def _export_current_tab(self):
        """Export from whichever tab is currently active."""
        tab_idx = self.notebook.index(self.notebook.select())
        tab_map = {
            0: ('tools_tab', '_export_log'),
            1: ('semantic_tab', '_export_map'),
            2: ('blacklist_tab', '_export_list'),
            3: ('audit_tab', '_export_report'),
            4: ('report_tab', '_export_report'),
            5: ('archive_tab', '_export_listing'),
        }
        if tab_idx in tab_map:
            attr, method = tab_map[tab_idx]
            tab = getattr(self, attr, None)
            if tab:
                fn = getattr(tab, method, None)
                if fn:
                    fn()

    def _toggle_dark_mode(self):
        """Toggle dark mode and apply theme."""
        dark = self.dark_mode_var.get()
        self.config['dark_mode'] = dark
        self._save_config()
        self._apply_theme()

    def _apply_theme(self):
        """Apply light or dark theme to all widgets."""
        dark = self.config.get('dark_mode', False)

        if dark:
            bg = '#1e1e1e'
            fg = '#d4d4d4'
            bg2 = '#252526'
            bg3 = '#2d2d2d'
            sel_bg = '#264f78'
            border = '#3c3c3c'
        else:
            bg = '#ffffff'
            fg = '#1e1e1e'
            bg2 = '#f8f9fa'
            bg3 = '#e8e8e8'
            sel_bg = '#0078d4'
            border = '#cccccc'

        style = ttk.Style()

        # ttk widget styles
        style.configure('TFrame', background=bg)
        style.configure('TLabel', background=bg, foreground=fg)
        style.configure('TButton', background=bg3, foreground=fg)
        style.configure('TNotebook', background=bg)
        style.configure('TNotebook.Tab', background=bg2, foreground=fg,
                        padding=[8, 4])
        style.map('TNotebook.Tab',
                  background=[('selected', bg if dark else '#ffffff')],
                  foreground=[('selected', fg)])
        style.configure('Treeview', background=bg, foreground=fg,
                        fieldbackground=bg, borderwidth=0)
        style.map('Treeview', background=[('selected', sel_bg)],
                  foreground=[('selected', '#ffffff')])
        style.configure('Treeview.Heading', background=bg2, foreground=fg)
        style.configure('TEntry', fieldbackground=bg2, foreground=fg)
        style.configure('TCombobox', fieldbackground=bg2, foreground=fg)
        style.configure('TLabelframe', background=bg, foreground=fg)
        style.configure('TLabelframe.Label', background=bg, foreground=fg)
        style.configure('TPanedwindow', background=bg)
        style.configure('TSeparator', background=border)

        # Root window
        self.root.configure(bg=bg)

        # Apply to each tab's owned widgets
        for tab in [self.tools_tab, self.semantic_tab, self.blacklist_tab,
                     self.audit_tab, self.report_tab, self.archive_tab]:
            if hasattr(tab, '_apply_theme'):
                tab._apply_theme(dark)

        # Direct tk widgets that don't follow ttk themes
        self._apply_tk_text_theme(self.tools_tab, 'output', dark)
        self._apply_tk_text_theme(self.report_tab, 'detail', dark)

        # Canvas widgets
        for tab in [self.semantic_tab, self.audit_tab]:
            if hasattr(tab, 'canvas'):
                tab.canvas.configure(bg=bg2)

        # Listbox widgets
        if hasattr(self.blacklist_tab, 'listbox'):
            self.blacklist_tab.listbox.configure(
                bg=bg, fg=fg, selectbackground=sel_bg,
                selectforeground='#ffffff')

    def _apply_tk_text_theme(self, tab, attr, dark):
        """Apply theme to a tk.Text widget on a tab."""
        widget = getattr(tab, attr, None)
        if widget:
            if dark:
                widget.configure(background='#1e1e1e', foreground='#d4d4d4',
                                 insertbackground='#d4d4d4')
            else:
                widget.configure(background='#ffffff', foreground='#1e1e1e',
                                 insertbackground='#1e1e1e')

    def _on_close(self):
        self._save_config()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='BCP Dashboard')
    parser.add_argument('--project-path', type=str, default=None,
                        help='Project root directory')
    args = parser.parse_args()

    root = tk.Tk()

    # Set a modern-ish style
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    BCPDashboard(root, project_path=args.project_path)
    root.mainloop()


if __name__ == '__main__':
    main()
