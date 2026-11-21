from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from pragma.measurement import ExecutionCosts
from scripts import observe_fx_entry_study as observer


class ForwardEntryObserverTests(unittest.TestCase):
    def test_backdated_stale_late_and_infinite_quotes_rejected(self):
        event=pd.Timestamp('2026-10-26T08:00Z')
        self.assertTrue(observer.timely_quote(100,101,event+pd.Timedelta(seconds=1),event+pd.Timedelta(seconds=2),event))
        self.assertFalse(observer.timely_quote(100,101,event-pd.Timedelta(seconds=1),event+pd.Timedelta(seconds=2),event))
        self.assertFalse(observer.timely_quote(100,101,event,event+pd.Timedelta(seconds=6),event))
        self.assertFalse(observer.timely_quote(100,101,event+pd.Timedelta(seconds=31),event+pd.Timedelta(seconds=31),event))
        self.assertFalse(observer.timely_quote(float('inf'),float('inf'),event,event,event))

    def test_restart_during_market_closure_expires_outcomes_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);baseline=root/'baseline';baseline.mkdir();study=root/'study';study.mkdir();out=root/'out';out.mkdir()
            (baseline/'protocol_frozen.json').write_text(json.dumps({'symbols':['EURUSD'],'captured':{'EURUSD':{'half_spread_assumed':0}}}),encoding='utf-8')
            (baseline/'EURUSD_baseline.json').write_text(json.dumps({'measurement':{'costs':asdict(ExecutionCosts())}}),encoding='utf-8')
            (study/'completion.json').write_text(json.dumps({'status':'COMPLETE','protocol_sha256':'test'}),encoding='utf-8')
            old='2026-01-01T08:00:00+00:00'
            (out/'state.json').write_text(json.dumps({'contract_fingerprint':'test','processed':{},'pending':[{'symbol':'EURUSD','due':old}],
                'open_observations':[{'symbol':'EURUSD','entry_observed_at':old,'horizon_minutes':15}]}),encoding='utf-8')
            client=SimpleNamespace(mt5=SimpleNamespace(symbol_info_tick=lambda s:SimpleNamespace(time_msc=0,bid=1.,ask=1.01)))
            context=MagicMock();context.__enter__.return_value=client
            argv=['observer','--baseline',str(baseline),'--cost-study',str(study),'--output',str(out),'--terminal-path','test','--cycles','1']
            with patch('sys.argv',argv),patch.object(observer,'state_fingerprint',return_value='test'),patch.object(observer,'research_client',return_value=context),patch.object(observer,'observed_offset_seconds',return_value=0),patch('builtins.print'):
                observer.main()
            state=json.loads((out/'state.json').read_text(encoding='utf-8'))
            self.assertEqual(state['pending'],[]);self.assertEqual(state['open_observations'],[])
            status=json.loads((out/'status.json').read_text(encoding='utf-8'))
            self.assertEqual(status['status'],'WAITING_FOR_FRESH_MARKET')
            outcome=json.loads((out/'outcomes.jsonl').read_text(encoding='utf-8'))
            self.assertIsNone(outcome['observation'])
            self.assertEqual(outcome['status'],'MISSED_EXIT_NO_FRESH_DATA')

    def test_fingerprint_changes_with_code_or_protocol(self):
        manifest={k:'a' for k in ('script_sha256','decision_code_sha256','study_protocol_sha256','baseline_protocol_sha256','entry_deadline_seconds','quote_max_age_seconds')}
        first=observer.state_fingerprint(manifest)
        manifest['study_protocol_sha256']='b'
        self.assertNotEqual(first,observer.state_fingerprint(manifest))


if __name__=='__main__':unittest.main()
