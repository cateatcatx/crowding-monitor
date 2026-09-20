"""Naver's September 2026 schema: venue objects and opaque pagination cursors."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import build_static
import fetch_sk_hynix_foreign_flow as flow


def record(day="2026-09-18"):
    return {"localTradedAt":day,"foreignHoldingRatio":"50.20",
            "krx":{"foreignNetVolume":"723470","organizationNetVolume":"160742",
                   "individualNetVolume":"-1500981","closingPrice":"1849000","tradingVolume":"4444839"},
            "nxt":{"foreignNetVolume":"188389","organizationNetVolume":"78105",
                   "individualNetVolume":"-268388","closingPrice":"1849000","tradingVolume":"1714125"}}


def page(rows,more=False,cursor=None):
    return {"isSuccess":True,"result":{"items":rows,"hasNext":more,"cursor":cursor}}


class CurrentFlowTests(unittest.TestCase):
    def test_nested_venues_and_total(self):
        raw=record()
        all_row=flow.normalize_record(raw,"ALL")
        self.assertEqual(all_row["foreign_net_shares"],911859)
        self.assertEqual(all_row["institution_net_shares"],238847)
        self.assertEqual(all_row["individual_net_shares"],-1769369)
        self.assertEqual(all_row["volume_shares"],6158964)
        self.assertEqual(all_row["foreign_holding_ratio_pct"],50.2)
        self.assertEqual(all_row["close_krw"],1849000)
        self.assertEqual(flow.normalize_record(raw,"KRX")["foreign_net_shares"],723470)
        self.assertEqual(flow.normalize_record(raw,"NXT")["foreign_net_shares"],188389)

    def test_missing_venue_is_not_silently_zero_or_krx_as_all(self):
        raw=record();raw["nxt"]=None
        self.assertEqual(flow.normalize_record(raw,"KRX")["foreign_net_shares"],723470)
        with self.assertRaisesRegex(ValueError,"缺少NXT"):
            flow.normalize_record(raw,"ALL")
        with self.assertRaisesRegex(ValueError,"缺少NXT"):
            flow.normalize_record(raw,"NXT")
        raw["localTradedAt"]="2025-03-21"
        self.assertEqual(flow.normalize_record(raw,"ALL")["foreign_net_shares"],723470)
        raw=record();raw["nxt"]["organizationNetVolume"]=None
        self.assertIsNone(flow.normalize_record(raw,"ALL")["institution_net_shares"])

    def test_current_pagination_uses_exchange_size_and_opaque_cursor(self):
        pages=[page([record()],True,"opaque-next-page"),page([record("2026-09-17")])]
        with patch.object(flow.requests,"Session") as session_factory:
            session=session_factory.return_value.__enter__.return_value
            session.get.side_effect=[MagicMock(json=MagicMock(return_value=p)) for p in pages]
            result=flow.fetch_since(date(2026,9,1),market="ALL",sleep_seconds=0)
        self.assertEqual(len(result),2)
        self.assertEqual(result.iloc[-1]["foreign_net_shares"],911859)
        first,second=session.get.call_args_list
        self.assertEqual(first.kwargs["params"]["exchangeType"],"ALL")
        self.assertEqual(first.kwargs["params"]["size"],50)
        self.assertEqual(second.kwargs["params"]["cursor"],"opaque-next-page")
        self.assertNotIn("bizdate",second.kwargs["params"])

    def test_legacy_pagination_still_uses_bizdate(self):
        pages=[{"isSuccess":True,"result":[{"bizdate":d,"foreignerPureBuyQuant":"3"}]}
               for d in ["20260918","20260917"]]
        with patch.object(flow.requests,"Session") as factory:
            session=factory.return_value.__enter__.return_value
            session.get.side_effect=[MagicMock(json=MagicMock(return_value=p)) for p in pages]
            result=flow.fetch_since(date(2026,9,17),market="KRX",sleep_seconds=0)
        self.assertEqual(len(result),2)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["bizdate"],"20260918")
        self.assertNotIn("cursor",session.get.call_args_list[1].kwargs["params"])

    def test_unknown_payload_and_broken_cursors_fail_closed(self):
        invalid=[{"isSuccess":True,"result":{}},page([],True,"x"),page([record()],True,None),
                 page(["not a row"]),{"isSuccess":False,"result":[]}]
        for payload in invalid:
            with self.assertRaises((ValueError,RuntimeError)):
                flow.unpack_page(payload)
        pages=[page([record()],True,"same"),page([record("2026-09-17")],True,"same")]
        with patch.object(flow.requests,"Session") as factory:
            session=factory.return_value.__enter__.return_value
            session.get.side_effect=[MagicMock(json=MagicMock(return_value=p)) for p in pages]
            with self.assertRaisesRegex(RuntimeError,"游标没有前进"):
                flow.fetch_since(date(2026,9,1),market="ALL",sleep_seconds=0)

    def test_failed_validation_does_not_replace_existing_file(self):
        with TemporaryDirectory() as directory:
            output=Path(directory)/"flow.csv"
            original=b"existing cache must survive"
            output.write_bytes(original)
            with patch('sys.argv',['fetch','--output',str(output),'--skip-freshness-check']), \
                 patch.object(flow,'fetch_since',side_effect=ValueError('missing NXT')):
                with self.assertRaisesRegex(ValueError,'missing NXT'):
                    flow.main()
            self.assertEqual(output.read_bytes(),original)

    def test_dashboard_error_keeps_final_exception_instead_of_traceback(self):
        result=MagicMock(returncode=1,stderr='Traceback\n'+('frame detail\n'*30)+'ValueError: missing NXT',stdout='')
        with patch.object(build_static.subprocess,'run',return_value=result):
            message=build_static.run('fetch_sk_hynix_foreign_flow.py')
        self.assertEqual(message,'fetch_sk_hynix_foreign_flow.py: ValueError: missing NXT')


if __name__ == '__main__':
    unittest.main()
