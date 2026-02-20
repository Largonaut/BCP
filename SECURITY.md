# Security Policy — Better Compaction Protocol (BCP)

**Version**: 1.0 | **Last reviewed**: February 2026 | **Reviewed by**: David Berlekamp (DoubleThink Solutions) with Claude (Anthropic)

---

## Why This Document Exists

BCP is being shared with people who work in environments where security is not theoretical. The author works in anti-misinformation and pro-citizen software development — a context where adversaries are real, persistent, and technically capable. This document is written for that audience, not for a marketing brochure.

If you work in journalism, human rights, research, counter-disinformation, or any field that attracts state-level or well-resourced adversarial interest, please read the [For High-Risk Users](#for-high-risk-users) section.

---

## What BCP Protects Against (Structural Properties)

These are architectural decisions — not configurations — that eliminate entire classes of attack.

| Property | What It Prevents |
|----------|-----------------|
| **No network listener** | No server, no ports, no WebSocket. Cross-site WebSocket hijacking, SSRF, and CSRF attacks are architecturally impossible. The class of vulnerabilities that affected OpenClaw ([CVE-2026-25253](https://thehackernews.com/2026/02/openclaw-bug-enables-one-click-remote.html), CVSS 8.8) cannot exist in BCP. |
| **No plugin/extension system** | No third-party skill marketplace. The ClawHavoc supply chain attack (1,184 malicious skills injected into OpenClaw's marketplace) has no equivalent attack surface here. |
| **Pure Python stdlib** | No pip or npm dependencies. Dependency confusion attacks, malicious package substitution, and transitive dependency vulnerabilities are not possible. |
| **No execution of archive content** | Session transcripts are stored as plain Markdown text. There is no `eval()`, `exec()`, or dynamic code loading anywhere in the codebase. A maliciously crafted archive file cannot run code. |
| **Append-only archive design** | Existing archive data is never deleted or modified in place. An attacker with write access to archives cannot silently alter historical records without leaving a detectable trace (timestamp gaps, turn count mismatches). |

---

## Known Vulnerabilities (Code-Verified, February 2026)

All findings require **local machine access** as a precondition. None allow remote code execution.

| Severity | File | Line | Finding | Status |
|----------|------|------|---------|--------|
| MEDIUM | `bcp_dashboard.py` | 436 | Argument field previously used `str.split()` without respecting quoted paths; user could pass unexpected flags to tools | **Fixed in this release** — replaced with `shlex.split()` |
| MEDIUM | `context_preserver.py` | 608 | Semantic tag written to filename now re-validated at write time (defense against tampered `semantic_map.json`) | **Fixed in this release** — stripped at generation |
| MEDIUM | `context_autoarchive.py` | 38–39 | Imports sibling tools from `TOOLS_DIR` via `sys.path.insert`. On a shared machine, a write-access attacker could substitute malicious tools that run when Claude Code hooks fire. | **Mitigated by docs** — keep `TOOLS_DIR` owner-writable only (see below) |
| LOW | `context_autoarchive.py` | 50 | `sys.stdin.read()` previously had no size limit; memory exhaustion possible via crafted hook payload | **Fixed in this release** — 100KB read limit added |

The full audit methodology and scope are noted in the [Audit History](#audit-history-and-scope) section.

---

## What BCP Cannot Protect Against

This section is not a disclaimer — it is actionable information.

### Compromised host machine

If your machine has kernel-mode malware (persistent drivers, rootkits), BCP cannot protect the integrity of its operations or the confidentiality of your archives. A process running at SYSTEM privilege can read any file on the disk regardless of application-level controls.

**The archive is a concentrated intelligence target.** Your `context_archive/` directory is a timestamped, structured log of your AI-assisted work — your research directions, prompting techniques, ongoing projects, and reasoning chains. This is more valuable to a persistent adversary than most individual files on your machine. Treat it accordingly.

Signs of potential compromise that warrant immediate action before trusting your BCP installation:
- Kernel drivers that survive uninstalls (check with [Sysinternals Autoruns](https://learn.microsoft.com/en-us/sysinternals/downloads/autoruns) + VirusTotal integration)
- Intermittent brief network connections with no user action (possible C2 beacon traffic)
- Files in `TOOLS_DIR` that differ from the GitHub repo without an explanation

### Distribution chain tampering

Like the [Notepad++ hosting attack](https://notepad-plus-plus.org/news/hijacked-incident-info-update/) (China's Lotus Blossom APT, active June–December 2025), a compromise of GitHub's infrastructure — not this code — could redirect downloads to malicious versions. The attack was selective: only targeted users received the malicious payload.

**Verify file integrity before running any release.** SHA-256 checksums are published with each GitHub release. Compare them before running:

```powershell
# Windows PowerShell
Get-FileHash context_preserver.py -Algorithm SHA256
```

Or, if you cloned from source, verify against the known-good commit hash.

### Malicious `semantic_map.json`

This file is loaded and trusted by all BCP tools. It maps single Unicode characters to topic names. If an attacker with local file access replaces it, they can affect filename generation and topic extraction behavior. Keep your `TOOLS_DIR` permissions restricted.

### Unencrypted archives

The `context_archive/` directory is **not encrypted**. If BitLocker (Windows) or VeraCrypt is not enabled on the drive containing your archives, they are readable by anyone with physical access or remote filesystem access.

---

## For High-Risk Users

*Journalists, researchers, activists, counter-disinformation workers, and anyone who has reason to believe they are a target of persistent adversarial interest.*

**Enable disk encryption first.** BitLocker (Windows Pro/Enterprise) or VeraCrypt (free, open source) on any drive containing archives or the tools directory. This is the single most impactful step. Without it, every other precaution is weakened.

**Protect `TOOLS_DIR` permissions.** The tools directory is trusted for automatic code import. It should be writable only by your user account. On Windows:
```powershell
# Check who has write access to F:\claude_tools
icacls "F:\claude_tools"
```
Remove write access for any account that is not yours.

**Verify tool integrity periodically.** Compare your local files against the GitHub repo. Any file that differs without an update commit is a tamper indicator:
```powershell
# Compare local file hash against known-good release hash
Get-FileHash F:\claude_tools\context_preserver.py -Algorithm SHA256
```

**Use Windows Defender Attack Surface Reduction.** Enable the rule that blocks untrusted process creation from Office applications, and the rule that blocks credential theft from Windows Local Security Authority. These are not BCP-specific but reduce the blast radius of a compromise.

**Audit startup entries before trusting the installation.** If you suspect your machine has been compromised, run [Sysinternals Autoruns](https://learn.microsoft.com/en-us/sysinternals/downloads/autoruns) with VirusTotal integration enabled before running any BCP tool. A modified Python interpreter or substituted tool file in `TOOLS_DIR` will defeat all BCP security properties.

**Do not run Claude Code on a machine you believe is currently compromised.** Your session transcripts are the product of your work. Archive them only after you have reason to believe the machine is clean.

**The append-only archive is a tamper indicator.** If you notice gaps in session timestamps, turn counts that don't match your memory of a session, or files that appear modified (check modification dates against when you last ran the preserver), those are signals worth investigating.

---

## Reporting Vulnerabilities

If you find a security issue in BCP:

1. **Do not open a public GitHub issue** for vulnerabilities that could be exploited before a fix is available.
2. Open a [GitHub Security Advisory](https://github.com/Largonaut/BCP/security/advisories/new) (private disclosure).
3. Alternatively, describe the issue in detail in a private message.

Response commitment: acknowledgment within 7 days, patch or mitigation within 90 days for confirmed vulnerabilities. Credit given in release notes unless you prefer anonymity.

---

## Audit History and Scope

| Date | Reviewer | Scope | Method |
|------|----------|-------|--------|
| February 2026 | David Berlekamp + Claude (Anthropic) | All 6 tool files (bcp_dashboard.py, context_preserver.py, context_auditor.py, context_autoarchive.py, context_searcher.py, context_rerunner.py) | Manual code review + grep for known vulnerability patterns |

**What was checked**: subprocess calls, path construction, file I/O, regex patterns, dynamic imports, stdin handling, JSON parsing, filename generation.

**What was not checked**: formal verification, automated fuzzing, penetration testing, dependency analysis (not applicable — stdlib only), cryptographic review (not applicable — no crypto).

This is a manual review by the development team, not an independent third-party audit. Users with high-stakes deployments should conduct their own review.

---

*This document was last updated February 2026. Security is a process, not a state — if you find something we missed, please tell us.*
