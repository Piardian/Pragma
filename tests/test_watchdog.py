import json
import urllib.error
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pragma.watchdog import (
    is_forex_market_open,
    format_heartbeat_report,
    evaluate_target,
    check_begonya_binance_ip_status,
    WatchdogRunner,
)


def test_is_forex_market_open():
    # Tuesday 14:00 UTC -> Open
    tuesday = datetime(2026, 11, 3, 14, 0, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(tuesday) is True

    # Friday 20:00 UTC -> Open
    friday_open = datetime(2026, 11, 6, 20, 0, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(friday_open) is True

    # Friday 22:00 UTC -> Closed
    friday_closed = datetime(2026, 11, 6, 22, 0, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(friday_closed) is False

    # Saturday 12:00 UTC -> Closed
    saturday = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(saturday) is False

    # Sunday 15:00 UTC -> Closed
    sunday_closed = datetime(2026, 11, 8, 15, 0, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(sunday_closed) is False

    # Sunday 22:00 UTC -> Open
    sunday_open = datetime(2026, 11, 8, 22, 0, 0, tzinfo=timezone.utc)
    assert is_forex_market_open(sunday_open) is True


def test_format_heartbeat_report():
    evals = [
        {"name": "Engine A", "status": "OK", "stale_sec": 12.0, "pid": 100, "detail": ""},
        {"name": "Engine B", "status": "STALLED", "stale_sec": 1200.0, "pid": 200, "detail": "1200s stale"},
        {"name": "Engine C", "status": "CRASHED", "stale_sec": None, "pid": None, "detail": "not running"},
    ]
    report = format_heartbeat_report(evals, datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc))
    assert "Engine A: Canlı (12 sn önce | PID 100)" in report
    assert "Engine B: KİLİTLENDİ" in report
    assert "Engine C: ÇÖKTÜ / KAPALI" in report
    assert "Genel Durum: 2 sistemde aksaklık var!" in report


def test_evaluate_target_stalled(tmp_path):
    dummy_file = tmp_path / "state.json"
    dummy_file.write_text("{}", encoding="utf-8")
    
    cfg = {
        "name": "Test Engine",
        "patterns": ["test_pattern"],
        "type": "file",
        "path": str(dummy_file),
        "is_forex": False,
        "max_stale_sec": 100,
    }
    
    with patch("pragma.watchdog.find_matching_process", return_value=(999, "python.exe")):
        # File mtime is now - 500s -> should be STALLED
        now = dummy_file.stat().st_mtime + 500
        res = evaluate_target("test_eng", cfg, now)
        assert res["status"] == "STALLED"
        assert res["pid"] == 999
        assert "Zombi Süreç" in res["detail"]


def test_watchdog_runner_alert_and_recovery(tmp_path):
    state_file = tmp_path / "watchdog_state.json"
    runner = WatchdogRunner(
        state_file=state_file,
        interval_sec=10,
        heartbeat_hours=1.0,
        stale_threshold_sec=60,
        dry_run=True,
    )
    
    sent_messages = []
    
    def fake_send(text, bot_token=None, chat_id=None):
        sent_messages.append(text)
        return True

    with patch("pragma.watchdog.send_telegram", side_effect=fake_send), \
         patch.object(runner, "targets", {
             "dummy": {
                 "name": "Dummy App",
                 "patterns": ["dummy"],
                 "type": "process_only",
                 "is_forex": False,
                 "max_stale_sec": 60,
             }
         }):
        runner.dry_run = False
        runner.state["last_heartbeat"] = 2_000_000_000.0  # Prevent scheduled heartbeat during test
        
        # 1. First cycle: process is crashed -> should send alert
        with patch("pragma.watchdog.find_matching_process", return_value=(None, None)):
            runner.run_cycle(force_heartbeat=False)
            assert len(sent_messages) == 1
            assert "KRİTİK ALARM" in sent_messages[0]
            assert "CRASHED" in sent_messages[0]
            
        # 2. Second cycle: process still crashed -> should NOT repeat alert immediately (throttled)
        with patch("pragma.watchdog.find_matching_process", return_value=(None, None)):
            runner.run_cycle(force_heartbeat=False)
            assert len(sent_messages) == 1

        # 3. Third cycle: process recovers -> should send recovery message
        with patch("pragma.watchdog.find_matching_process", return_value=(1234, "python.exe")):
            runner.run_cycle(force_heartbeat=False)
            assert len(sent_messages) == 2
            assert "DÜZELDİ" in sent_messages[1]


def test_heartbeat_report_and_begonya_binance_ip_check(tmp_path):
    evals = [
        {"name": "Begonya00 (SFP & Macro)", "status": "OK", "stale_sec": 5.0, "pid": 13712, "detail": ""},
    ]
    now_dt = datetime(2026, 11, 21, 13, 0, tzinfo=timezone.utc)

    rep_ok = format_heartbeat_report(
        evals,
        now_dt,
        begonya_ip_status={"status": "OK", "needs_ip_update": False, "ip": "212.125.10.152"},
    )
    assert "Begonya00 Binance IP: Değişim gerekmiyor" in rep_ok
    assert "212.125.10.152" in rep_ok

    rep_bad = format_heartbeat_report(
        evals,
        now_dt,
        begonya_ip_status={"status": "IP_CHANGE_REQUIRED", "needs_ip_update": True, "ip": "88.99.1.2"},
    )
    assert "DEĞİŞİM GEREKİYOR!" in rep_bad
    assert "88.99.1.2" in rep_bad

    beg_dir = tmp_path / "Begonya00"
    beg_dir.mkdir()
    (beg_dir / ".env").write_text("BINANCE_API_KEY=k123\nBINANCE_API_SECRET=s456\n", encoding="utf-8")

    class _Resp:
        def __init__(self, payload: dict):
            self._raw = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen_ok(req, timeout=4.0):
        if "/fapi/v1/time" in req.full_url:
            return _Resp({"serverTime": 1795000000000})
        return _Resp([{"asset": "USDT", "balance": "107.30"}])

    with patch("urllib.request.urlopen", side_effect=fake_urlopen_ok), \
         patch("pragma.watchdog.get_public_ip", return_value="212.125.10.152"):
        res_ok = check_begonya_binance_ip_status(beg_dir)
        assert res_ok["status"] == "OK"
        assert res_ok["needs_ip_update"] is False
        assert res_ok["ip"] == "212.125.10.152"

    def fake_urlopen_2015(req, timeout=4.0):
        if "/fapi/v1/time" in req.full_url:
            return _Resp({"serverTime": 1795000000000})
        err_body = json.dumps({
            "code": -2015,
            "msg": "Invalid API-key, IP, or permissions for action, request ip: 95.10.20.30",
        }).encode("utf-8")
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, BytesIO(err_body))

    with patch("urllib.request.urlopen", side_effect=fake_urlopen_2015):
        res_bad = check_begonya_binance_ip_status(beg_dir)
        assert res_bad["status"] == "IP_CHANGE_REQUIRED"
        assert res_bad["needs_ip_update"] is True
        assert res_bad["ip"] == "95.10.20.30"
