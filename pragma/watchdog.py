"""Unified Multi-Project Watchdog & Heartbeat Monitor.



Continuously monitors data throughput, process health, and broker connectivity

across all trading systems:

- Pragma (Forex Shadow Trader)

- Trawma (Crypto Engine)

- Megalord (Multi-Engine Risk & State Daemon)

- Stigma (CLT Whitelist Watcher)

- CLT (Swing BOS Core)

- Begonya00 (SFP & Macro Engine)

- Begonya Classic (SMC & Macro Engine)

- Begonya Convexity Engine

- MetaTrader 5 Terminal



Detects both process crashes AND silent stalls ('zombie' processes where the PID

is alive but data stream / inner loop is frozen). Sends immediate Telegram alarms

on failure, sends recovery notifications on heal, and delivers periodic scheduled

Heartbeat reassurance reports.

"""

from __future__ import annotations



import argparse

from datetime import datetime, timezone, timedelta

import glob

import json

import logging

import os

from pathlib import Path

import sys

import time

from typing import Any

import urllib.parse

import urllib.request



# Ensure UTF-8 stdout on Windows console if stdout exists

if sys.platform == "win32":

    try:

        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):

            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):

            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    except Exception:

        pass



try:

    import psutil

except ImportError:

    psutil = None



from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID



logger = logging.getLogger("pragma.watchdog")



DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "reports" / "watchdog_state.json"





def safe_print(text: str) -> None:

    """Print text safely across different Windows console code pages and pythonw environments."""

    if sys.stdout is None:

        return

    try:

        print(text, flush=True)

    except Exception:

        pass





def is_forex_market_open(dt: datetime | None = None) -> bool:

    """Check if the global Forex market is open.

    

    Forex closes Friday at 21:00 UTC and reopens Sunday at 21:00 UTC.

    Saturday is entirely closed.

    """

    if dt is None:

        dt = datetime.now(timezone.utc)

    weekday = dt.weekday()  # Monday is 0, Sunday is 6

    hour = dt.hour

    

    # Saturday (5): completely closed

    if weekday == 5:

        return False

    # Friday (4): closes at 21:00 UTC (safe conservative bound)

    if weekday == 4 and hour >= 21:

        return False

    # Sunday (6): opens at 22:00 UTC (conservative Sydney/Asia open)

    if weekday == 6 and hour < 22:

        return False

    return True





def send_telegram(text: str, bot_token: str | None = None, chat_id: str | None = None, timeout: float = 10.0) -> bool:
    """Deliver a Telegram message via standard HTTP POST to the configured Telegram bot."""
    token = bot_token or TELEGRAM_BOT_TOKEN
    cid = chat_id or TELEGRAM_CHAT_ID
    if not token or not cid:
        logger.warning("Telegram token or chat_id missing. Message printed to console:\n%s", text)
        safe_print(text)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": cid, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "PragmaWatchdog/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok", False))
    except Exception as exc:
        logger.error("Failed to deliver Telegram watchdog message: %s", exc)
        return False





def find_matching_process(exe_substr: str, patterns: list[str]) -> tuple[int | None, str | None]:

    """Find a running process whose executable name and commandline/cwd match patterns."""

    if psutil is None:

        return None, None

    my_pid = os.getpid()

    for proc in psutil.process_iter(["pid", "name"]):

        if proc.info["pid"] == my_pid:

            continue

        try:

            p_name = (proc.info.get("name") or "").lower()

            if exe_substr.lower() not in p_name:

                continue

            cmd = " ".join(proc.cmdline()).lower()

            cwd = ""

            try:

                cwd = proc.cwd().lower()

            except Exception:

                pass

            combined = f"{p_name} {cmd} {cwd}".replace("\u0307", "").replace("ı", "i")

            if all(pat.lower() in combined for pat in patterns):

                return proc.info["pid"], proc.info["name"]

        except (psutil.NoSuchProcess, psutil.AccessDenied):

            continue

    return None, None





def get_latest_file_mtime(target_cfg: dict[str, Any]) -> float | None:

    """Retrieve the most recent modification timestamp for the configured target."""

    t_type = target_cfg.get("type", "file")

    if t_type == "file":

        p = Path(target_cfg["path"])

        if p.exists():

            return p.stat().st_mtime

        return None

    elif t_type == "dir_latest":

        base_dir = Path(target_cfg["path"])

        pattern = target_cfg.get("pattern", "*")

        if not base_dir.exists():

            return None

        matches = glob.glob(str(base_dir / pattern))

        if not matches:

            return None

        return max(os.path.getmtime(m) for m in matches)

    return None





def _find_reading_status_path(user_home: Path) -> Path:
    """Locate reading/runtime/status.json dynamically across Codex outputs."""
    try:
        candidates = list((user_home / "Documents" / "Codex").glob("*/*/outputs/*/reading/runtime/status.json"))
        if candidates and candidates[0].exists():
            return candidates[0]
    except Exception:
        pass
    return user_home / "Documents" / "Codex" / "2026-11-07" / "https-youtu-be-j-6bhln-d70" / "outputs" / "READİNG" / "reading" / "runtime" / "status.json"


def get_default_targets() -> dict[str, dict[str, Any]]:

    """Return all standard targets across the machine."""

    user_home = Path.home()

    app_data = os.environ.get("LOCALAPPDATA", str(user_home / "AppData" / "Local"))

    desktop = user_home / "Desktop"

    scratch = user_home / ".gemini" / "antigravity" / "scratch"



    return {

        "pragma": {

            "name": "Pragma (Forex Shadow)",

            "exe": "python",

            "patterns": ["pragma.shadow_trader"],

            "type": "file",

            "path": str(Path(app_data) / "Pragma" / "shadow_trading" / "state.json"),

            "is_forex": True,

            "max_stale_sec": 900,

        },

        "trawma": {

            "name": "Trawma (Crypto Engine)",

            "exe": "python",

            "patterns": ["trawma", "run_pipeline"],

            "type": "dir_latest",

            "path": str(desktop / "TrawmaProject" / "data_cache"),

            "pattern": "binance_*.csv",

            "is_forex": False,

            "max_stale_sec": 900,

        },

        "megalord": {

            "name": "Megalord (Risk & State)",

            "exe": "python",

            "patterns": ["megalord_daemon"],

            "type": "file",

            "path": str(desktop / "MegalordProject" / "megalord_live_state.json"),

            "is_forex": False,

            "max_stale_sec": 900,

        },

        "stigma": {

            "name": "Stigma (CLT Whitelist)",

            "exe": "python",

            "patterns": ["stigma", "run_pipeline"],

            "type": "file",

            "path": str(desktop / "StigmaProject" / "reports" / "watcher.log"),

            "is_forex": False,

            "max_stale_sec": 900,

        },

        "clt": {

            "name": "CLT (Swing BOS Core)",

            "exe": "node",

            "patterns": ["swing-bos-core"],

            "type": "file",

            "path": str(scratch / "swing-bos-core" / "telemetry" / "polling.jsonl"),

            "is_forex": False,

            "max_stale_sec": 1800,  # 15m timeframe bar scanner + multi-symbol scan latency

        },

        "begonya00": {

            "name": "Begonya00 (SFP & Macro)",

            "exe": "python",

            "patterns": ["begonya00", "start_begonya.py"],

            "type": "file",

            "path": str(desktop / "Begonya00" / "telemetry" / "engine_telemetry.jsonl"),

            "is_forex": True,

            "max_stale_sec": 900,

        },

        "begonya_classic": {

            "name": "Begonya Classic (SMC & Macro)",

            "exe": "node",

            "patterns": ["begonya", "smc_engine"],

            "type": "file",

            "path": str(scratch / "Begonya" / "smc_engine" / "telemetry" / "polling.jsonl"),

            "is_forex": True,

            "max_stale_sec": 1800,  # 15m timeframe bar scanner + multi-symbol scan latency

        },

        "reading": {
            "name": "Reading (Tape & Shadow)",
            "exe": "python",
            "patterns": ["reading", "service.py"],
            "type": "file",
            "path": str(_find_reading_status_path(user_home)),
            "is_forex": False,
            "max_stale_sec": 900,
        },
        "begonya_convexity": {

            "name": "Begonya Convexity",

            "exe": "python",

            "patterns": ["begonya_convexity_engine", "lifecycle_daemon.py"],

            "type": "process_only",

            "is_forex": True,

            "max_stale_sec": 900,

        },

        "mt5": {

            "name": "MetaTrader 5 Terminal",

            "exe": "terminal64",

            "patterns": ["terminal64"],

            "type": "process_only",

            "is_forex": True,

            "max_stale_sec": 900,

        },

    }





def evaluate_target(key: str, cfg: dict[str, Any], now: float) -> dict[str, Any]:

    """Audit single target health by process check and file latency."""

    pid, proc_name = find_matching_process(cfg.get("exe", "python"), cfg["patterns"])

    # Fallback: check status file for active PID if available
    if pid is None and cfg.get("path") and psutil:
        try:
            p_check = Path(cfg["path"])
            if p_check.exists() and p_check.suffix == ".json":
                data_st = json.loads(p_check.read_text(encoding="utf-8"))
                cand_pid = data_st.get("pid")
                if cand_pid and psutil.pid_exists(cand_pid):
                    p_cand = psutil.Process(cand_pid)
                    if cfg.get("exe", "python").lower() in (p_cand.name() or "").lower():
                        pid = cand_pid
                        proc_name = p_cand.name()
        except Exception:
            pass

    is_forex = cfg.get("is_forex", False)

    forex_open = is_forex_market_open(datetime.now(timezone.utc))



    res: dict[str, Any] = {

        "key": key,

        "name": cfg["name"],

        "pid": pid,

        "proc_name": proc_name,

        "is_forex": is_forex,

        "stale_sec": None,

        "status": "OK",

        "detail": "",

    }



    if cfg.get("type") == "process_only":

        if pid is None:

            if is_forex and not forex_open:

                res["status"] = "WEEKEND_PAUSE"

                res["detail"] = "Piyasa kapalı (Hafta sonu)"

            else:

                res["status"] = "CRASHED"

                res["detail"] = "Süreç çalışmıyor (PID bulunamadı)!"

        else:

            res["status"] = "OK"

            res["detail"] = f"PID {pid} aktif"

        return res



    # File / data based check

    mtime = get_latest_file_mtime(cfg)

    if mtime is not None:

        stale_sec = max(0.0, now - mtime)

        res["stale_sec"] = stale_sec

    else:

        stale_sec = None



    max_stale = float(cfg.get("max_stale_sec", 900))



    if pid is None:

        if is_forex and not forex_open:

            res["status"] = "WEEKEND_PAUSE"

            res["detail"] = "Piyasa kapalı (Hafta sonu)"

        else:

            res["status"] = "CRASHED"

            res["detail"] = "Süreç çalışmıyor (PID bulunamadı)!"

    else:

        # Process is alive. Now check data freshness.

        if stale_sec is None:

            res["status"] = "NO_DATA"

            res["detail"] = f"PID {pid} ayakta fakat veri dosyası bulunamadı"

        elif stale_sec > max_stale:

            if is_forex and not forex_open:

                res["status"] = "WEEKEND_PAUSE"

                res["detail"] = f"Piyasa kapalı (Son veri: {stale_sec/60:.0f} dk önce)"

            else:

                res["status"] = "STALLED"

                res["detail"] = f"Zombi Süreç! PID {pid} açık ama {stale_sec/60:.1f} dakikadır veri yazmıyor!"

        else:

            res["status"] = "OK"

            res["detail"] = f"PID {pid} | Son veri: {stale_sec:.0f} sn önce"

            if key == "pragma":

                try:

                    p_state = Path(cfg["path"])

                    if p_state.exists():

                        d_st = json.loads(p_state.read_text(encoding="utf-8"))

                        if d_st.get("macro_status") == "DEFENSIVE_HOLD":

                            res["detail"] += " | Makro: DEFENSIVE_HOLD"

                except Exception:

                    pass



    return res





def format_heartbeat_report(evaluations: list[dict[str, Any]], now_dt: datetime) -> str:

    """Format an informative, compact Telegram Heartbeat report."""

    time_str = now_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [

        "💓 SİSTEM SAĞLIK RAPORU (HEARTBEAT)",

        f"Zaman: {time_str}",

        "",

    ]

    healthy_count = 0

    total_count = len(evaluations)



    for ev in evaluations:

        status = ev["status"]

        name = ev["name"]

        stale_sec = ev["stale_sec"]

        pid = ev["pid"]



        if status == "OK":

            healthy_count += 1

            if stale_sec is not None:

                if stale_sec < 60:

                    ago = f"{stale_sec:.0f} sn önce"

                elif stale_sec < 3600:

                    ago = f"{stale_sec/60:.1f} dk önce"

                else:

                    ago = f"{stale_sec/3600:.1f} saat önce"

                lines.append(f"🟢 {name}: Canlı ({ago} | PID {pid})")

            else:

                lines.append(f"🟢 {name}: Canlı (PID {pid})")

        elif status == "WEEKEND_PAUSE":

            healthy_count += 1

            lines.append(f"🟡 {name}: Hafta Sonu Uykusu")

        elif status == "STALLED":

            lines.append(f"🔴 {name}: KİLİTLENDİ ({ev['detail']})")

        elif status == "CRASHED":

            lines.append(f"🔴 {name}: ÇÖKTÜ / KAPALI")

        else:

            lines.append(f"🟠 {name}: {status} ({ev['detail']})")



    lines.append("")

    if healthy_count == total_count:

        lines.append(f"✨ Genel Durum: Tüm {total_count} sistem kesintisiz veri işliyor.")

    else:

        lines.append(f"⚠️ Genel Durum: {total_count - healthy_count} sistemde aksaklık var!")



    return "\n".join(lines)





class WatchdogRunner:

    def __init__(self,

                 state_file: str | Path = DEFAULT_STATE_FILE,

                 interval_sec: int = 60,

                 heartbeat_hours: float = 1.0,

                 stale_threshold_sec: int = 900,

                 bot_token: str | None = None,

                 chat_id: str | None = None,

                 dry_run: bool = False,

                 consecutive_failures_threshold: int = 1):

        self.state_file = Path(state_file)

        self.interval_sec = interval_sec

        self.heartbeat_hours = heartbeat_hours

        self.stale_threshold_sec = stale_threshold_sec

        self.bot_token = bot_token

        self.chat_id = chat_id

        self.dry_run = dry_run

        self.consecutive_failures_threshold = consecutive_failures_threshold



        self.targets = get_default_targets()

        # Only override per-target default limits if explicit non-standard threshold was supplied

        if stale_threshold_sec != 900:

            for t in self.targets.values():

                t["max_stale_sec"] = stale_threshold_sec



        self.state: dict[str, Any] = self._load_state()



    def _load_state(self) -> dict[str, Any]:

        if self.state_file.exists():

            try:

                return json.loads(self.state_file.read_text(encoding="utf-8"))

            except Exception:

                pass

        return {

            "last_heartbeat": 0.0,

            "target_states": {},

            "alert_history": {},

        }



    def _save_state(self) -> None:

        try:

            self.state_file.parent.mkdir(parents=True, exist_ok=True)

            tmp = self.state_file.with_suffix(".tmp")

            tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

            os.replace(tmp, self.state_file)

        except Exception as exc:

            logger.warning("Could not save watchdog state: %s", exc)



    def run_cycle(self, force_heartbeat: bool = False) -> list[dict[str, Any]]:

        now = time.time()

        now_dt = datetime.now(timezone.utc)

        evaluations = [evaluate_target(k, v, now) for k, v in self.targets.items()]



        target_states = self.state.setdefault("target_states", {})

        alert_history = self.state.setdefault("alert_history", {})

        failure_counts = self.state.setdefault("failure_counts", {})



        # Process status transitions

        for ev in evaluations:

            k = ev["key"]

            curr_status = ev["status"]

            prev_status = target_states.get(k, "OK")

            last_alert_time = alert_history.get(k, 0.0)



            # Failure transition (OK/WEEKEND_PAUSE -> CRASHED/STALLED)

            if curr_status in ("CRASHED", "STALLED", "NO_DATA"):

                failure_counts[k] = failure_counts.get(k, 0) + 1

                should_alert = False

                thresh = getattr(self, "consecutive_failures_threshold", 1)

                if failure_counts[k] >= thresh:

                    if prev_status not in ("CRASHED", "STALLED", "NO_DATA") or (failure_counts[k] == thresh):

                        should_alert = True  # Verified failure

                    elif (now - last_alert_time) > 7200:  # Repeat alert every 2 hours if still broken

                        should_alert = True



                if should_alert:

                    alert_msg = (

                        f"🚨 PRAGMA WATCHDOG — KRİTİK ALARM\n"

                        f"Sistem: {ev['name']}\n"

                        f"Durum: {curr_status}\n"

                        f"Detay: {ev['detail']}\n"

                        f"Zaman: {now_dt.strftime('%H:%M:%S UTC')}\n"

                        f"Müdahale gerekebilir!"

                    )

                    if not self.dry_run:

                        send_telegram(alert_msg, self.bot_token, self.chat_id)

                    alert_history[k] = now

                    safe_print(f"[WATCHDOG ALARM] {ev['name']}: {ev['detail']}")



            # Recovery transition (CRASHED/STALLED -> OK)

            elif curr_status == "OK":

                thresh = getattr(self, "consecutive_failures_threshold", 1)

                had_alarm = prev_status in ("CRASHED", "STALLED", "NO_DATA") and failure_counts.get(k, 0) >= thresh

                failure_counts[k] = 0

                if had_alarm:

                    recovery_msg = (

                        f"✅ PRAGMA WATCHDOG — DÜZELDİ\n"

                        f"Sistem: {ev['name']}\n"

                        f"Durum: Yeniden sağlıklı veri akışı başladı.\n"

                        f"Detay: {ev['detail']}\n"

                        f"Zaman: {now_dt.strftime('%H:%M:%S UTC')}"

                    )

                    if not self.dry_run:

                        send_telegram(recovery_msg, self.bot_token, self.chat_id)

                    safe_print(f"[WATCHDOG RECOVERY] {ev['name']} recovered.")



            target_states[k] = curr_status



        # Scheduled Heartbeat check

        last_hb = float(self.state.get("last_heartbeat", 0.0))

        hb_interval = self.heartbeat_hours * 3600.0



        if force_heartbeat or (now - last_hb >= hb_interval):

            hb_text = format_heartbeat_report(evaluations, now_dt)

            if not self.dry_run:

                send_telegram(hb_text, self.bot_token, self.chat_id)

            self.state["last_heartbeat"] = now

            safe_print(f"[WATCHDOG HEARTBEAT] Sent scheduled report.\n{hb_text}")



        self._save_state()

        return evaluations



    def watch(self) -> None:

        safe_print(f"🛰️ Pragma Unified Watchdog started | poll={self.interval_sec}s | heartbeat={self.heartbeat_hours}h | stale_threshold={self.stale_threshold_sec}s")

        # Send initial heartbeat immediately to reassure user upon activation

        self.run_cycle(force_heartbeat=True)



        try:

            while True:

                time.sleep(self.interval_sec)

                self.run_cycle(force_heartbeat=False)

        except KeyboardInterrupt:

            safe_print("\n[WATCHDOG] Stopped by user.")





def main() -> None:

    parser = argparse.ArgumentParser(description="Pragma Unified Multi-Project Watchdog & Heartbeat")

    parser.add_argument("--watch", action="store_true", help="Run continuously in background polling loop")

    parser.add_argument("--interval-sec", type=int, default=60, help="Polling interval in seconds (default: 60)")

    parser.add_argument("--heartbeat-hours", type=float, default=1.0, help="Interval for scheduled heartbeat in hours (default: 1)")

    parser.add_argument("--stale-threshold-sec", type=int, default=900, help="Seconds before process is declared stalled (default: 900 = 15m)")

    parser.add_argument("--heartbeat-now", action="store_true", help="Send a heartbeat status report to Telegram immediately and exit")

    parser.add_argument("--dry-run", action="store_true", help="Execute evaluation without sending actual Telegram alerts")

    parser.add_argument("--consecutive-failures", type=int, default=2, help="Consecutive failed cycles before Telegram alarm (default: 2)")



    args = parser.parse_args()



    runner = WatchdogRunner(

        interval_sec=args.interval_sec,

        heartbeat_hours=args.heartbeat_hours,

        stale_threshold_sec=args.stale_threshold_sec,

        dry_run=args.dry_run,

        consecutive_failures_threshold=args.consecutive_failures,

    )



    if args.heartbeat_now:

        evals = runner.run_cycle(force_heartbeat=True)

        safe_print("Heartbeat sent.")

        return



    if args.watch:

        runner.watch()

    else:

        evals = runner.run_cycle(force_heartbeat=False)

        report = format_heartbeat_report(evals, datetime.now(timezone.utc))

        safe_print(report)





if __name__ == "__main__":

    main()

