"""System Diagnoser — unified health and state inspector for BunnyTweets.

Inspects every subsystem (browser profiles, GoLogin API, task queue,
scheduler, disk usage, threads) and returns a structured diagnostic
report.  Designed to answer "why isn't it working?" in one call.

Usage:
    from src.core.diagnoser import SystemDiagnoser
    diag = SystemDiagnoser(app)       # pass the Application instance
    report = diag.run_full_diagnosis()  # returns a DiagnosticReport
    print(report.render_text())         # human-readable output
    data = report.to_dict()             # JSON-serializable dict
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------

@dataclass
class Check:
    """A single diagnostic check result."""
    name: str
    status: str  # "ok", "warn", "error"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubsystemReport:
    """All checks for one subsystem (e.g. 'Browser Profiles')."""
    subsystem: str
    checks: list[Check] = field(default_factory=list)

    @property
    def worst_status(self) -> str:
        if any(c.status == "error" for c in self.checks):
            return "error"
        if any(c.status == "warn" for c in self.checks):
            return "warn"
        return "ok"


@dataclass
class DiagnosticReport:
    """Complete diagnostic report across all subsystems."""
    timestamp: str = ""
    subsystems: list[SubsystemReport] = field(default_factory=list)
    duration_ms: float = 0

    @property
    def overall_status(self) -> str:
        if any(s.worst_status == "error" for s in self.subsystems):
            return "error"
        if any(s.worst_status == "warn" for s in self.subsystems):
            return "warn"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "overall_status": self.overall_status,
            "duration_ms": round(self.duration_ms, 1),
            "subsystems": [
                {
                    "name": s.subsystem,
                    "status": s.worst_status,
                    "checks": [
                        {
                            "name": c.name,
                            "status": c.status,
                            "message": c.message,
                            "details": c.details,
                        }
                        for c in s.checks
                    ],
                }
                for s in self.subsystems
            ],
        }

    def render_text(self) -> str:
        """Render a human-readable diagnostic report."""
        icons = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERR]"}
        lines = [
            "",
            "=" * 70,
            f"  SYSTEM DIAGNOSIS  {self.timestamp}",
            f"  Overall: {icons.get(self.overall_status, '?')} {self.overall_status.upper()}  "
            f"({self.duration_ms:.0f}ms)",
            "=" * 70,
        ]

        for sub in self.subsystems:
            icon = icons.get(sub.worst_status, "?")
            lines.append(f"\n  {icon} {sub.subsystem}")
            lines.append("  " + "-" * (len(sub.subsystem) + 6))
            for chk in sub.checks:
                ci = icons.get(chk.status, "?")
                lines.append(f"    {ci} {chk.name}: {chk.message}")
                if chk.details:
                    for k, v in chk.details.items():
                        lines.append(f"         {k}: {v}")

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Diagnoser
# ---------------------------------------------------------------------------

class SystemDiagnoser:
    """Runs diagnostic checks against a live Application instance.

    Can also run a subset of checks when the engine is stopped (disk,
    processes, GoLogin API reachability).
    """

    # Cache size thresholds (bytes)
    CACHE_WARN_MB = 500
    CACHE_ERROR_MB = 2000

    def __init__(self, app=None, config=None, db=None):
        """
        Args:
            app: A live Application instance (may be None if engine is stopped).
            config: A ConfigLoader instance (used when app is None).
            db: A Database instance (used when app is None for account checks).
        """
        self._app = app
        self._config = config or (app.config if app else None)
        self._db = db or (app.db if app else None)

    def run_full_diagnosis(self) -> DiagnosticReport:
        """Run every diagnostic check and return a complete report."""
        start = time.monotonic()
        report = DiagnosticReport(
            timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        report.subsystems.append(self._check_browser_provider())
        report.subsystems.append(self._check_browser_profiles())
        report.subsystems.append(self._check_zombie_processes())
        report.subsystems.append(self._check_queue_and_scheduler())
        report.subsystems.append(self._check_threads())
        report.subsystems.append(self._check_disk_and_cache())
        report.subsystems.append(self._check_account_states())

        report.duration_ms = (time.monotonic() - start) * 1000
        return report

    # ------------------------------------------------------------------
    # 1. Browser Provider (GoLogin / Dolphin Anty) API reachability
    # ------------------------------------------------------------------
    def _check_browser_provider(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Browser Provider API")

        if not self._app and not self._config:
            sub.checks.append(Check(
                name="Configuration",
                status="warn",
                message="No app or config available — cannot check provider",
            ))
            return sub

        config = self._config
        provider = config.browser_provider if config else "unknown"
        sub.checks.append(Check(
            name="Provider Type",
            status="ok",
            message=provider,
        ))

        # Try to reach the local API
        if self._app and hasattr(self._app, "browser_client"):
            client = self._app.browser_client
            base_url = getattr(client, "base_url", "unknown")
            sub.checks.append(Check(
                name="Local API URL",
                status="ok",
                message=base_url,
            ))

            # Ping the local API
            try:
                import requests
                resp = requests.get(base_url, timeout=5)
                sub.checks.append(Check(
                    name="Local API Reachable",
                    status="ok",
                    message=f"HTTP {resp.status_code}",
                ))
            except Exception as exc:
                sub.checks.append(Check(
                    name="Local API Reachable",
                    status="error",
                    message=f"Unreachable: {exc}",
                    details={"hint": (
                        "Is the GoLogin/Dolphin Anty desktop app running? "
                        "The local API must be available for profile management."
                    )},
                ))

            # Check authentication
            authenticated = getattr(client, "_authenticated", False) or getattr(client, "is_authenticated", False)
            has_token = bool(getattr(client, "api_token", ""))
            if has_token:
                sub.checks.append(Check(
                    name="API Token",
                    status="ok" if authenticated else "warn",
                    message="Configured" + (" and authenticated" if authenticated else " but not yet authenticated"),
                ))
            else:
                sub.checks.append(Check(
                    name="API Token",
                    status="warn",
                    message="No API token configured",
                ))
        else:
            sub.checks.append(Check(
                name="Client",
                status="warn",
                message="Engine not running — cannot inspect browser client",
            ))

        return sub

    # ------------------------------------------------------------------
    # 2. Browser Profiles — driver liveness
    # ------------------------------------------------------------------
    def _check_browser_profiles(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Browser Profiles")

        if not self._app:
            sub.checks.append(Check(
                name="Engine State",
                status="warn",
                message="Engine not running — no profiles to inspect",
            ))
            return sub

        pm = getattr(self._app, "profile_manager", None)
        if not pm:
            sub.checks.append(Check(
                name="ProfileManager",
                status="error",
                message="ProfileManager not found on Application",
            ))
            return sub

        drivers = getattr(pm, "_drivers", {})
        sub.checks.append(Check(
            name="Active Drivers",
            status="ok",
            message=f"{len(drivers)} driver(s) tracked by ProfileManager",
        ))

        # Check each driver for liveness
        stale_count = 0
        for profile_id, driver in list(drivers.items()):
            try:
                _ = driver.title  # quick liveness check
                sub.checks.append(Check(
                    name=f"Profile {profile_id}",
                    status="ok",
                    message="Browser responsive",
                    details={"current_url": _safe_url(driver)},
                ))
            except Exception as exc:
                stale_count += 1
                sub.checks.append(Check(
                    name=f"Profile {profile_id}",
                    status="error",
                    message=f"STALE DRIVER — browser unresponsive: {_short(exc)}",
                    details={"action": "Will be auto-recovered on next health check"},
                ))

        if stale_count:
            sub.checks.append(Check(
                name="Stale Driver Summary",
                status="error",
                message=f"{stale_count} stale driver(s) detected — possible deadlock or crash",
            ))

        return sub

    # ------------------------------------------------------------------
    # 3. Zombie Processes — orphaned chrome/chromedriver processes
    # ------------------------------------------------------------------
    def _check_zombie_processes(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Process Health")

        chrome_procs = _find_processes("chrome")
        chromedriver_procs = _find_processes("chromedriver")

        # Count tracked profiles
        tracked = 0
        if self._app and hasattr(self._app, "profile_manager"):
            tracked = len(getattr(self._app.profile_manager, "_drivers", {}))

        sub.checks.append(Check(
            name="Chrome Processes",
            status="ok" if chrome_procs is not None else "warn",
            message=f"{chrome_procs if chrome_procs is not None else '?'} chrome process(es) found"
                    + (f" ({tracked} tracked by ProfileManager)" if tracked else ""),
        ))

        sub.checks.append(Check(
            name="ChromeDriver Processes",
            status="ok" if chromedriver_procs is not None else "warn",
            message=f"{chromedriver_procs if chromedriver_procs is not None else '?'} chromedriver process(es) found",
        ))

        # Zombie detection heuristic: if we track N profiles but have
        # significantly more chrome processes, something is likely orphaned.
        if chrome_procs is not None and tracked > 0:
            # Each profile spawns multiple chrome subprocess, so we use a
            # generous multiplier.  5 chrome PIDs per profile is normal.
            expected_max = tracked * 8
            if chrome_procs > expected_max:
                sub.checks.append(Check(
                    name="Zombie Detection",
                    status="warn",
                    message=(
                        f"Possible zombie processes: {chrome_procs} chrome PIDs "
                        f"for {tracked} tracked profile(s) "
                        f"(expected <{expected_max})"
                    ),
                    details={"hint": "Run pre-flight cleanup or restart the engine"},
                ))
            else:
                sub.checks.append(Check(
                    name="Zombie Detection",
                    status="ok",
                    message="Process count within expected range",
                ))

        # Detect actual zombie (Z state) processes
        zombies = _count_zombie_state_processes()
        if zombies > 0:
            sub.checks.append(Check(
                name="Zombie State Processes",
                status="warn",
                message=f"{zombies} process(es) in zombie (Z) state on this system",
                details={"hint": "Zombie processes are harmless but indicate unreaped children"},
            ))
        else:
            sub.checks.append(Check(
                name="Zombie State Processes",
                status="ok",
                message="No zombie-state processes found",
            ))

        return sub

    # ------------------------------------------------------------------
    # 4. Task Queue & Scheduler
    # ------------------------------------------------------------------
    def _check_queue_and_scheduler(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Task Queue & Scheduler")

        if not self._app:
            sub.checks.append(Check(
                name="Engine State",
                status="warn",
                message="Engine not running — cannot inspect queue/scheduler",
            ))
            return sub

        # Queue
        queue = getattr(self._app, "queue", None)
        if queue:
            q_size = queue.queue_size
            active = queue.active_tasks

            sub.checks.append(Check(
                name="Queue Size",
                status="warn" if q_size > 20 else "ok",
                message=f"{q_size} task(s) queued",
                details={"hint": "Large queue may indicate stuck tasks"} if q_size > 20 else {},
            ))
            sub.checks.append(Check(
                name="Active Tasks",
                status="ok",
                message=f"{active} task(s) running",
            ))

            # Check for deadlocked queue: worker thread alive?
            worker = getattr(queue, "_worker_thread", None)
            if worker and not worker.is_alive():
                sub.checks.append(Check(
                    name="Worker Thread",
                    status="error",
                    message="Queue worker thread is DEAD — tasks will not be processed",
                    details={"action": "Restart the engine to recover"},
                ))
            elif worker:
                sub.checks.append(Check(
                    name="Worker Thread",
                    status="ok",
                    message="Queue worker thread is alive",
                ))

            # Paused accounts
            paused = getattr(queue, "_paused_accounts", {})
            if paused:
                paused_names = list(paused.keys())
                sub.checks.append(Check(
                    name="Paused Accounts",
                    status="warn",
                    message=f"{len(paused)} account(s) paused after max retries",
                    details={"accounts": paused_names},
                ))

            # Running futures — detect stuck tasks
            running = getattr(queue, "_running", {})
            for acct_name, future in list(running.items()):
                if future.done():
                    # Future is done but not yet cleaned up — that's fine
                    continue
                sub.checks.append(Check(
                    name=f"Running Task: {acct_name}",
                    status="ok",
                    message="Task in progress",
                ))

        # Scheduler
        jm = getattr(self._app, "job_manager", None)
        if jm:
            scheduler = getattr(jm, "scheduler", None)
            if scheduler:
                running = getattr(scheduler, "running", False)
                sub.checks.append(Check(
                    name="Scheduler",
                    status="ok" if running else "error",
                    message="Running" if running else "STOPPED — no jobs will fire",
                ))
                try:
                    jobs = jm.get_jobs_summary()
                    sub.checks.append(Check(
                        name="Scheduled Jobs",
                        status="ok",
                        message=f"{len(jobs)} job(s) registered",
                    ))

                    # Check for jobs with no next_run (misfired or broken)
                    broken = [j for j in jobs if not j.get("next_run")]
                    if broken:
                        sub.checks.append(Check(
                            name="Broken Jobs",
                            status="warn",
                            message=f"{len(broken)} job(s) have no next_run time",
                            details={"jobs": [j["id"] for j in broken]},
                        ))
                except Exception as exc:
                    sub.checks.append(Check(
                        name="Job Query",
                        status="error",
                        message=f"Failed to query jobs: {_short(exc)}",
                    ))

        return sub

    # ------------------------------------------------------------------
    # 5. Thread Inspection
    # ------------------------------------------------------------------
    def _check_threads(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Thread Health")

        all_threads = threading.enumerate()
        alive = [t for t in all_threads if t.is_alive()]
        daemon_count = sum(1 for t in alive if t.daemon)

        sub.checks.append(Check(
            name="Thread Count",
            status="warn" if len(alive) > 50 else "ok",
            message=f"{len(alive)} alive ({daemon_count} daemon, {len(alive) - daemon_count} non-daemon)",
        ))

        # List notable threads
        notable = [t.name for t in alive if not t.name.startswith("Thread-")]
        if notable:
            sub.checks.append(Check(
                name="Named Threads",
                status="ok",
                message=", ".join(notable[:15]) + ("..." if len(notable) > 15 else ""),
            ))

        # Check for expected threads when engine is running
        if self._app:
            expected_names = ["automation-engine", "engine-ready-watcher"]
            thread_names = {t.name for t in alive}
            for name in expected_names:
                if name in thread_names:
                    sub.checks.append(Check(
                        name=f"Thread: {name}",
                        status="ok",
                        message="Alive",
                    ))

        return sub

    # ------------------------------------------------------------------
    # 6. Disk & Cache
    # ------------------------------------------------------------------
    def _check_disk_and_cache(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Disk & Cache")

        config = self._config
        if not config:
            sub.checks.append(Check(
                name="Config",
                status="warn",
                message="No config available — cannot inspect paths",
            ))
            return sub

        base = config.base_dir

        # Data directory size
        data_dir = base / "data"
        if data_dir.exists():
            data_size = _dir_size_mb(data_dir)
            sub.checks.append(Check(
                name="Data Directory",
                status="ok",
                message=f"{data_size:.1f} MB",
                details={"path": str(data_dir)},
            ))

        # Log directory size
        log_dir = base / "data" / "logs"
        if log_dir.exists():
            log_size = _dir_size_mb(log_dir)
            log_count = sum(1 for f in log_dir.iterdir() if f.is_file())
            status = "warn" if log_size > 500 else "ok"
            sub.checks.append(Check(
                name="Log Directory",
                status=status,
                message=f"{log_size:.1f} MB across {log_count} file(s)",
                details={"path": str(log_dir)},
            ))

        # Downloads (stale media)
        gd_cfg = config.google_drive
        download_dir = base / gd_cfg.get("download_dir", "data/downloads")
        if download_dir.exists():
            dl_size = _dir_size_mb(download_dir)
            dl_count = sum(1 for f in download_dir.iterdir() if f.is_file())
            sub.checks.append(Check(
                name="Downloads (stale media)",
                status="warn" if dl_count > 50 else "ok",
                message=f"{dl_count} file(s), {dl_size:.1f} MB",
                details={"path": str(download_dir)},
            ))

        # Database size
        db_path = base / config.database_path
        if db_path.exists():
            db_mb = db_path.stat().st_size / (1024 * 1024)
            sub.checks.append(Check(
                name="Database",
                status="warn" if db_mb > 100 else "ok",
                message=f"{db_mb:.1f} MB",
                details={"path": str(db_path)},
            ))

        # GoLogin profile cache (~/.gologin/browser-profiles/)
        gl_cache = Path.home() / ".gologin" / "browser-profiles"
        if gl_cache.exists():
            cache_mb = _dir_size_mb(gl_cache)
            status = "error" if cache_mb > self.CACHE_ERROR_MB else (
                "warn" if cache_mb > self.CACHE_WARN_MB else "ok"
            )
            sub.checks.append(Check(
                name="GoLogin Profile Cache",
                status=status,
                message=f"{cache_mb:.0f} MB",
                details={
                    "path": str(gl_cache),
                    "hint": "Large cache can slow down profile starts. "
                            "Delete unused profile folders to reclaim space."
                            if status != "ok" else "",
                },
            ))

        # Disk free space
        try:
            usage = shutil.disk_usage(str(base))
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            pct = (usage.used / usage.total) * 100
            status = "error" if free_gb < 1 else ("warn" if free_gb < 5 else "ok")
            sub.checks.append(Check(
                name="Disk Free Space",
                status=status,
                message=f"{free_gb:.1f} GB free of {total_gb:.1f} GB ({pct:.0f}% used)",
            ))
        except Exception:
            pass

        return sub

    # ------------------------------------------------------------------
    # 7. Account States
    # ------------------------------------------------------------------
    def _check_account_states(self) -> SubsystemReport:
        sub = SubsystemReport(subsystem="Account States")

        if not self._app and not self._config:
            sub.checks.append(Check(
                name="Configuration",
                status="warn",
                message="No config available",
            ))
            return sub

        config = self._config
        db = self._db

        if not db:
            sub.checks.append(Check(
                name="Database",
                status="warn",
                message="No database connection — cannot inspect account states",
            ))
            return sub

        accounts = config.enabled_accounts if config else []
        error_count = 0
        paused_count = 0
        stuck_count = 0

        for acct in accounts:
            name = acct.get("name", "unknown")
            status_obj = db.get_account_status(name)
            if not status_obj:
                sub.checks.append(Check(
                    name=f"Account: {name}",
                    status="warn",
                    message="No status record in database",
                ))
                continue

            s = status_obj.status
            if s == "error":
                error_count += 1
                sub.checks.append(Check(
                    name=f"Account: {name}",
                    status="error",
                    message=f"ERROR — {status_obj.error_message or 'no details'}",
                ))
            elif s == "paused":
                paused_count += 1
                sub.checks.append(Check(
                    name=f"Account: {name}",
                    status="warn",
                    message=f"PAUSED — {status_obj.error_message or 'max retries exhausted'}",
                ))
            elif s in ("running", "browsing"):
                # Check if stuck — these are transient states that should
                # clear within a few minutes.  If the engine just started,
                # this is normal; if it's been >15 min, something is wrong.
                stuck_count += 1
                sub.checks.append(Check(
                    name=f"Account: {name}",
                    status="warn",
                    message=f"Stuck in transient state '{s}' — may indicate a hung task",
                ))
            else:
                sub.checks.append(Check(
                    name=f"Account: {name}",
                    status="ok",
                    message=s,
                    details=_account_details(status_obj),
                ))

        # Summary
        total = len(accounts)
        healthy = total - error_count - paused_count - stuck_count
        overall = "ok"
        if error_count > 0:
            overall = "error"
        elif paused_count > 0 or stuck_count > 0:
            overall = "warn"

        sub.checks.insert(0, Check(
            name="Summary",
            status=overall,
            message=(
                f"{total} configured, {healthy} healthy, "
                f"{error_count} error, {paused_count} paused, "
                f"{stuck_count} stuck"
            ),
        ))

        return sub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short(exc: Exception, max_len: int = 120) -> str:
    """Truncate an exception message to a readable length."""
    s = str(exc).split("\n")[0]
    return s[:max_len] + "..." if len(s) > max_len else s


def _safe_url(driver) -> str:
    """Get the current URL from a driver, safely."""
    try:
        return driver.current_url or "(blank)"
    except Exception:
        return "(unavailable)"


def _find_processes(name: str) -> int | None:
    """Count running processes whose command matches `name`.

    Returns None if we can't enumerate processes (e.g. no /proc or pgrep).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-c", "-f", name],
            capture_output=True, text=True, timeout=5,
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None


def _count_zombie_state_processes() -> int:
    """Count processes in zombie (Z) state by reading /proc."""
    count = 0
    proc = Path("/proc")
    if not proc.exists():
        return 0
    try:
        for entry in proc.iterdir():
            if entry.name.isdigit():
                try:
                    stat = (entry / "status").read_text()
                    for line in stat.splitlines():
                        if line.startswith("State:") and "Z" in line:
                            count += 1
                            break
                except (PermissionError, FileNotFoundError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    return count


def _dir_size_mb(path: Path) -> float:
    """Calculate total size of a directory in MB.  Non-recursive for speed
    on deep trees — only counts top-level files and one level of subdirs."""
    total = 0
    try:
        for entry in os.scandir(str(path)):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                try:
                    for sub in os.scandir(entry.path):
                        if sub.is_file(follow_symlinks=False):
                            total += sub.stat().st_size
                except (PermissionError, OSError):
                    pass
    except (PermissionError, OSError):
        pass
    return total / (1024 * 1024)


def _account_details(status_obj) -> dict:
    """Extract useful details from an AccountStatus for display."""
    details = {}
    if status_obj.last_post:
        details["last_post"] = str(status_obj.last_post)
    if status_obj.last_retweet:
        details["last_retweet"] = str(status_obj.last_retweet)
    if getattr(status_obj, "retweets_today", None):
        details["retweets_today"] = status_obj.retweets_today
    return details
