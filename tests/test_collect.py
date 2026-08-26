import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.collect import collect_stock, load_stock_config, parse_consensus, parse_investor_trading, parse_price


class ParserTests(unittest.TestCase):
    def test_parse_price(self):
        name, price, quoted_at = parse_price("2026년 08월 21일 <dd>종목명 SK하이닉스</dd>\n<dd>현재가 1,730,000 전일대비</dd>")
        self.assertEqual((name, price, quoted_at), ("SK하이닉스", 1730000, "2026-08-21"))

    def test_parse_consensus(self):
        payload = json.dumps({"JsonData": [
            {"YYMM": "2025.12(A)", "EPS": "58,955", "BPS": "171,751"},
            {"YYMM": "2026.12(E)", "EPS": "349,566", "BPS": "518,236"},
            {"YYMM": "2027.12(E)", "EPS": "436,187", "BPS": "944,539"},
        ]})
        self.assertEqual(parse_consensus(payload)["2027"], {"eps": 436187, "bps": 944539})

    def test_parse_investor_trading(self):
        html = """
        <table summary="외국인 기관 순매매 거래량">
          <tr><th>날짜</th><th>종가</th><th>전일비</th><th>등락률</th><th>거래량</th><th>기관</th><th>외국인</th></tr>
          <tr><td>2026.08.21</td><td>281,500</td><td>+10,500</td><td>+3.87%</td><td>27,672,192</td><td>+1,306,652</td><td>-1,567,349</td></tr>
        </table>
        """
        self.assertEqual(parse_investor_trading(html), {
            "date": "2026-08-21", "institution": 1306652, "foreign": -1567349
        })

    def test_load_stock_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stocks.json"
            path.write_text('[{"code":"035420","name":"NAVER","defaultMetric":"per"}]', encoding="utf-8")
            self.assertEqual(load_stock_config(path), [{"code": "035420", "name": "NAVER", "defaultMetric": "PER"}])

    @patch("scripts.collect.fetch_text")
    def test_price_only_preserves_consensus(self, fetch_text):
        fetch_text.return_value = (
            "2026년 08월 21일 <dd>종목명 삼성전자</dd>"
            "<dd>현재가 281,500 전일대비</dd>"
        )
        previous = {
            "code": "005930", "name": "삼성전자", "price": 270000, "quotedAt": "2026-08-20",
            "defaultMetric": "PER", "annual": {"2027": {"eps": 12000, "bps": 150000}},
            "source": {},
        }
        result = collect_stock(
            {"code": "005930", "name": "삼성전자", "defaultMetric": "PER"},
            mode="price", previous=previous, run_at="2026-08-21T01:00:00+00:00",
        )
        self.assertEqual(result["price"], 281500)
        self.assertEqual(result["annual"], previous["annual"])
        self.assertNotIn("investorTrading", result)
        self.assertNotIn("previousAnnual", result)
        self.assertEqual(fetch_text.call_count, 1)

    @patch("scripts.collect.fetch_text")
    def test_investors_only_preserves_price_and_consensus(self, fetch_text):
        fetch_text.return_value = (
            '<table summary="외국인 기관 순매매 거래량">'
            '<tr><td>2026.08.21</td><td>281,500</td><td>상승</td><td>3.87%</td>'
            '<td>100</td><td>+20</td><td>-10</td></tr></table>'
        )
        previous = {
            "code": "005930", "name": "삼성전자", "price": 281500,
            "quotedAt": "2026-08-21", "defaultMetric": "PER",
            "annual": {"2027": {"eps": 12000, "bps": 150000}}, "source": {},
        }
        result = collect_stock(
            {"code": "005930", "name": "삼성전자", "defaultMetric": "PER"},
            mode="investors", previous=previous, run_at="2026-08-21T10:10:00+00:00",
        )
        self.assertEqual(result["price"], previous["price"])
        self.assertEqual(result["annual"], previous["annual"])
        self.assertEqual(result["investorTrading"]["institution"], 20)
        self.assertEqual(result["investorTrading"]["foreign"], -10)
        self.assertEqual(fetch_text.call_count, 1)

    @patch("scripts.collect.fetch_text")
    def test_consensus_keeps_previous_snapshot(self, fetch_text):
        fetch_text.side_effect = [
            '<input id="hidDT" name="hidDT" value="20260821">',
            json.dumps({"JsonData": [{"YYMM": "2027.12(E)", "EPS": "12,600", "BPS": "153,000"}]}),
        ]
        previous = {
            "code": "005930", "name": "삼성전자", "price": 281500, "quotedAt": "2026-08-21",
            "defaultMetric": "PER", "annual": {"2027": {"eps": 12000, "bps": 150000}},
            "source": {},
        }
        result = collect_stock(
            {"code": "005930", "name": "삼성전자", "defaultMetric": "PER"},
            mode="consensus", previous=previous, run_at="2026-08-22T00:00:00+00:00",
        )
        self.assertEqual(result["previousAnnual"], previous["annual"])
        self.assertEqual(result["annual"]["2027"]["eps"], 12600)
        self.assertEqual(result["price"], 281500)


if __name__ == "__main__":
    unittest.main()
