#!/usr/bin/env python3
"""Collect Korean stock price and annual consensus data from Naver/FnGuide."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FALLBACK_STOCKS = [
    {"code": "005930", "name": "삼성전자", "defaultMetric": "PER"},
    {"code": "000660", "name": "SK하이닉스", "defaultMetric": "PBR"},
    {"code": "012330", "name": "현대모비스", "defaultMetric": "PER"},
    {"code": "005380", "name": "현대차", "defaultMetric": "PER"},
    {"code": "009150", "name": "삼성전기", "defaultMetric": "PER"},
    {"code": "011070", "name": "LG이노텍", "defaultMetric": "PER"},
    {"code": "329180", "name": "HD현대중공업", "defaultMetric": "PER"},
    {"code": "010120", "name": "LS ELECTRIC", "defaultMetric": "PER"},
    {"code": "062040", "name": "산일전기", "defaultMetric": "PER"},
    {"code": "278470", "name": "에이피알", "defaultMetric": "PER"},
    {"code": "483650", "name": "달바글로벌", "defaultMetric": "PER"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Korean-Valuation-Board/1.0)",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
    "Connection": "close",
}


def fetch_text(url: str, *, referer: str | None = None, attempts: int = 3) -> str:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=15) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = 3 * attempt
            print(f"RETRY {attempt}/{attempts - 1} {url} ({exc})", file=sys.stderr)
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def number(value: str | int | float | None) -> int | None:
    if value in (None, "", "N/A"):
        return None
    cleaned = re.sub(r"[^0-9.-]", "", str(value))
    return int(round(float(cleaned))) if cleaned else None


def load_stock_config(path: Path) -> list[dict[str, str]]:
    """Load and validate the shared stock list."""
    if not path.exists():
        print(f"WARN {path} not found; using built-in fallback list", file=sys.stderr)
        return FALLBACK_STOCKS
    parsed = json.loads(path.read_text(encoding="utf-8"))
    items = parsed.get("stocks", []) if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        raise ValueError("종목 설정은 JSON 배열이어야 합니다")
    stocks: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"종목 설정 {index}번 항목이 객체가 아닙니다")
        code = str(item.get("code", "")).strip()
        name = str(item.get("name", code)).strip() or code
        metric = str(item.get("defaultMetric", "PER")).upper()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"잘못된 종목코드: {code!r}")
        if metric not in ("PER", "PBR"):
            raise ValueError(f"{code}의 defaultMetric은 PER 또는 PBR이어야 합니다")
        if code in seen:
            raise ValueError(f"중복 종목코드: {code}")
        seen.add(code)
        stocks.append({"code": code, "name": name, "defaultMetric": metric})
    if not stocks:
        raise ValueError("종목 설정이 비어 있습니다")
    return stocks


def parse_price(html: str) -> tuple[str, int, str | None]:
    name_match = re.search(r"<dd>\s*종목명\s*([^\r\n<]+)</dd>", html, re.I)
    if not name_match:
        name_match = re.search(r"종목명\s*([^\r\n<]+)", html)
    price_match = re.search(r"현재가\s*([0-9,]+)", html)
    date_match = re.search(r"(20\d{2})년\s*(\d{2})월\s*(\d{2})일", html)
    if not price_match:
        # Stable fallback used by the legacy Naver quote page.
        price_match = re.search(r'<p class="no_today">.*?<span class="blind">([0-9,]+)</span>', html, re.S)
    if not price_match:
        raise ValueError("현재가를 찾지 못했습니다")
    name = re.sub(r"\s+", " ", name_match.group(1)).strip() if name_match else ""
    quoted_at = "-".join(date_match.groups()) if date_match else None
    return name, number(price_match.group(1)) or 0, quoted_at


def discover_snapshot_date(consensus_html: str) -> str:
    match = re.search(r'id="hidDT"\s+name="hidDT"\s+value="(\d{8})"', consensus_html)
    if not match:
        match = re.search(r"sDT:\s*'(\d{8})'", consensus_html)
    if not match:
        raise ValueError("컨센서스 기준일을 찾지 못했습니다")
    return match.group(1)


def parse_consensus(payload: str) -> dict[str, dict[str, int | None]]:
    parsed = json.loads(payload)
    rows = parsed.get("JsonData", [])
    annual: dict[str, dict[str, int | None]] = {}
    for row in rows:
        label = str(row.get("YYMM", ""))
        match = re.match(r"(20\d{2})\.\d{2}\(E\)", label)
        if not match:
            continue
        annual[match.group(1)] = {"eps": number(row.get("EPS")), "bps": number(row.get("BPS"))}
    if not annual:
        raise ValueError("연간 예상 EPS/BPS를 찾지 못했습니다")
    return annual


class InvestorTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_target = False
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table" and "순매매 거래량" in (attributes.get("summary") or ""):
            self.in_target = True
            self.table_depth = 1
        elif self.in_target and tag == "table":
            self.table_depth += 1
        elif self.in_target and tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag in ("td", "th"):
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell_parts)).strip())
            self.in_cell = False
        elif self.in_row and tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
        elif self.in_target and tag == "table":
            self.table_depth -= 1
            if self.table_depth == 0:
                self.in_target = False


def parse_investor_trading(html: str) -> dict[str, int | str]:
    parser = InvestorTableParser()
    parser.feed(html)
    for row in parser.rows:
        if len(row) >= 7 and re.fullmatch(r"20\d{2}\.\d{2}\.\d{2}", row[0]):
            return {
                "date": row[0].replace(".", "-"),
                "institution": number(row[5]) or 0,
                "foreign": number(row[6]) or 0,
            }
    raise ValueError("기관·외국인 순매매 수량을 찾지 못했습니다")


def collect_stock(
    stock: dict[str, str],
    *,
    mode: str = "all",
    previous: dict | None = None,
    run_at: str | None = None,
) -> dict:
    code = stock["code"]
    naver_url = f"https://finance.naver.com/item/coinfo.naver?code={code}"
    investor_url = f"https://finance.naver.com/item/frgn.naver?code={code}"
    consensus_url = f"https://navercomp.wisereport.co.kr/v2/company/c1050001.aspx?cmp_cd={code}"
    result = json.loads(json.dumps(previous)) if previous else {
        "code": code,
        "name": stock["name"],
        "price": None,
        "quotedAt": None,
        "defaultMetric": stock.get("defaultMetric", "PER"),
        "annual": {},
        "source": {"price": naver_url, "investor": investor_url, "consensus": consensus_url},
    }
    result["defaultMetric"] = stock.get("defaultMetric", "PER")
    result["source"] = {"price": naver_url, "investor": investor_url, "consensus": consensus_url}
    collect_price = mode in ("all", "price") or result.get("price") is None
    collect_consensus = mode in ("all", "consensus") or not result.get("annual")

    if collect_price:
        page_name, price, quoted_at = parse_price(fetch_text(naver_url))
        result.update({"name": page_name or stock["name"], "price": price, "quotedAt": quoted_at})
        result["priceUpdatedAt"] = run_at
        try:
            time.sleep(0.5)
            result["investorTrading"] = parse_investor_trading(fetch_text(investor_url))
            result["investorTradingUpdatedAt"] = run_at
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"WARN {code} investor trading preserved ({exc})", file=sys.stderr)

    if collect_consensus:
        if collect_price:
            time.sleep(0.8)
        consensus_html = fetch_text(consensus_url, referer=naver_url)
        snapshot = discover_snapshot_date(consensus_html)
        query = urlencode({
            "flag": "2", "cmp_cd": code, "finGubun": "MAIN", "frq": "0",
            "sDT": snapshot, "chartType": "svg",
        })
        api_url = f"https://navercomp.wisereport.co.kr/v2/company/ajax/c1050001_data.aspx?{query}"
        time.sleep(0.8)
        annual = parse_consensus(fetch_text(api_url, referer=consensus_url))
        wanted = {year: annual[year] for year in ("2026", "2027", "2028") if year in annual}
        if not wanted:
            wanted = dict(sorted(annual.items())[-3:])
        if previous and previous.get("annual"):
            result["previousAnnual"] = previous["annual"]
        result["annual"] = wanted
        result["consensusUpdatedAt"] = run_at

    result["collectionStatus"] = {"state": "fresh", "mode": mode}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", action="append", help="Collect only this six-digit code (repeatable)")
    parser.add_argument("--config", default="config/stocks.json", help="Shared stock-list JSON")
    parser.add_argument("--output", default="data/stocks.json")
    parser.add_argument("--strict", action="store_true", help="Fail when any stock cannot be collected")
    parser.add_argument("--mode", choices=("all", "price", "consensus"), default="all")
    parser.add_argument("--batch-count", type=int, default=1, help="Number of rotating batches")
    parser.add_argument("--batch-index", type=int, default=0, help="Zero-based batch to collect")
    args = parser.parse_args()
    if args.batch_count < 1 or not 0 <= args.batch_index < args.batch_count:
        parser.error("--batch-index must be between 0 and --batch-count minus one")
    configured = load_stock_config(Path(args.config))
    selected = configured
    if args.code:
        wanted = set(args.code)
        selected = [stock for stock in selected if stock["code"] in wanted]
        known = {stock["code"] for stock in selected}
        selected += [{"code": code, "name": code, "defaultMetric": "PER"} for code in wanted - known]
    elif args.batch_count > 1:
        selected = [stock for index, stock in enumerate(configured) if index % args.batch_count == args.batch_index]
        print(f"BATCH {args.batch_index + 1}/{args.batch_count}: {len(selected)} stocks")

    output = Path(args.output)
    previous_by_code: dict[str, dict] = {}
    previous_failures: list[dict] = []
    previous_document: dict = {}
    if output.exists():
        try:
            previous_document = json.loads(output.read_text(encoding="utf-8"))
            previous_by_code = {item["code"]: item for item in previous_document.get("stocks", [])}
            previous_failures = previous_document.get("failures", [])
        except (OSError, KeyError, json.JSONDecodeError):
            print("WARN previous data could not be read; stale fallback is unavailable", file=sys.stderr)

    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stocks, failures = [], []
    for index, stock in enumerate(selected):
        try:
            stocks.append(collect_stock(
                stock,
                mode=args.mode,
                previous=previous_by_code.get(stock["code"]),
                run_at=run_at,
            ))
            print(f"OK {stock['code']} {stocks[-1]['name']}")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            failure = {"code": stock["code"], "name": stock["name"], "error": str(exc), "preserved": False}
            previous_stock = previous_by_code.get(stock["code"])
            if previous_stock:
                preserved = json.loads(json.dumps(previous_stock))
                preserved["collectionStatus"] = {
                    "state": "stale",
                    "failedAt": run_at,
                    "error": str(exc),
                }
                stocks.append(preserved)
                failure["preserved"] = True
                print(f"STALE {stock['code']} previous data preserved ({exc})", file=sys.stderr)
            else:
                print(f"FAIL {stock['code']} {exc}", file=sys.stderr)
            failures.append(failure)
        if index + 1 < len(selected):
            time.sleep(2)

    if args.batch_count > 1 and not args.code:
        updated_by_code = {item["code"]: item for item in stocks}
        stocks = [
            updated_by_code.get(stock["code"]) or previous_by_code.get(stock["code"])
            for stock in configured
        ]
        stocks = [stock for stock in stocks if stock is not None]
        processed_codes = {stock["code"] for stock in selected}
        failures = [
            failure for failure in previous_failures
            if failure.get("code") not in processed_codes
        ] + failures

    result = {
        "schemaVersion": 2,
        "generatedAt": run_at,
        "priceUpdatedAt": run_at if args.mode in ("all", "price") else previous_document.get("priceUpdatedAt"),
        "consensusUpdatedAt": run_at if args.mode in ("all", "consensus") else previous_document.get("consensusUpdatedAt"),
        "stocks": stocks,
        "failures": failures,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(stocks)} stocks to {output}")
    return 1 if args.strict and failures else (0 if stocks else 1)


if __name__ == "__main__":
    raise SystemExit(main())
