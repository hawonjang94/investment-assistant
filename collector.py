import logging
import os
import re
from typing import Any

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 네이버 금융 서버 차단을 막기 위한 매너 명찰(User-Agent)
NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://stock.naver.com/",
}

REQUEST_TIMEOUT = 10


def validate_stock_code(code: Any) -> str:
    """종목코드를 문자열로 검증 (6자리 숫자, 앞자리 0 보존)"""
    if code is None:
        raise ValueError("종목코드가 입력되지 않았습니다.")

    code_str = str(code).strip()
    if not code_str:
        raise ValueError("종목코드가 입력되지 않았습니다.")

    if not re.fullmatch(r"\d{6}", code_str):
        raise ValueError("종목코드는 6자리 숫자여야 합니다. (예: 000660)")

    return code_str


def resolve_stock_code(code_or_name: Any) -> str:
    """6자리 종목코드 또는 종목명(예: 'SK하이닉스')을 받아 6자리 종목코드 문자열로 변환"""
    if code_or_name is None:
        raise ValueError("종목코드 또는 종목명을 입력해 주세요.")

    text = str(code_or_name).strip()
    if not text:
        raise ValueError("종목코드 또는 종목명을 입력해 주세요.")

    # 이미 6자리 숫자(예: '000660')면 그대로 반환
    if re.fullmatch(r"\d{6}", text):
        return text

    url = "https://ac.stock.naver.com/ac"
    params = {"q": text, "target": "stock"}
    logger.info("[NAVER] 종목명 -> 종목코드 검색 시작 (query=%s)", text)

    try:
        resp = requests.get(url, params=params, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("종목명 검색 응답 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"종목명 검색 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"종목명 검색 실패 (HTTP {resp.status_code})")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("종목명 검색 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    items = [
        item for item in (data.get("items") or [])
        if item.get("nationCode") == "KOR" and re.fullmatch(r"\d{6}", str(item.get("code", "")))
    ]

    if not items:
        raise ValueError(f"'{text}'에 해당하는 국내 상장 종목을 찾을 수 없습니다.")

    # 정확히 이름이 일치하는 종목 우선 선택, 없으면 가장 상단 결과 선택
    exact = next((item for item in items if str(item.get("name", "")).strip().lower() == text.lower()), None)
    matched = exact or items[0]
    found_code = str(matched["code"])

    logger.info("[PARSE] 종목명 매핑 완료 ('%s' -> %s %s)", text, matched.get("name"), found_code)
    return found_code


def clean_number(value: Any) -> int | float | None:
    """콤마와 단위가 섞인 문자열에서 순수 숫자(int/float)만 추출 (결측치는 None)"""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return value

    text = str(value).strip()
    if not text or text in {"N/A", "-", "--", "null", "None"}:
        return None

    # 콤마 제거 후 숫자(부호, 소수점 포함) 패턴 추출
    cleaned = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    num_str = match.group(0)
    return float(num_str) if "." in num_str else int(num_str)


def parse_korean_amount(value: Any) -> int | None:
    """'894조 1,227억', '5,432억' 같은 한글 금액 단위를 순수 원(KRW) 단위 정수로 변환"""
    if value is None:
        return None

    text = str(value).strip().replace(",", "")
    if not text or text in {"N/A", "-", "--", "null", "None"}:
        return None

    total = 0
    jo_match = re.search(r"(\d+(?:\.\d+)?)\s*조", text)
    eok_match = re.search(r"(\d+(?:\.\d+)?)\s*억", text)
    man_match = re.search(r"(\d+(?:\.\d+)?)\s*만", text)

    if jo_match:
        total += int(float(jo_match.group(1)) * 1_0000_0000_0000)
    if eok_match:
        total += int(float(eok_match.group(1)) * 1_0000_0000)
    if man_match:
        total += int(float(man_match.group(1)) * 1_0000)

    if total > 0:
        return total

    # 단위가 없는 순수 숫자 문자열인 경우 그대로 반환
    num = clean_number(text)
    return int(num) if num is not None else None


def fetch_basic_info(code: str) -> dict[str, Any]:
    """네이버 금융 basic API에서 정식 종목명과 상단 시세를 수집"""
    code = validate_stock_code(code)
    url = f"https://m.stock.naver.com/api/stock/{code}/basic"

    logger.info("[NAVER] 네이버 금융 basic API 접근 시작 (code=%s, User-Agent 적용)", code)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("네이버 금융 서버 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"네이버 금융 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code == 404:
        raise ValueError(f"존재하지 않거나 상장폐지된 종목코드입니다. (code={code})")
    if resp.status_code != 200:
        raise RuntimeError(f"네이버 금융 페이지 접근 실패 (HTTP {resp.status_code})")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("네이버 금융 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    stock_name = data.get("stockName")
    if not stock_name:
        raise ValueError(f"존재하지 않거나 상장폐지된 종목코드입니다. (종목명 파싱 실패: {code})")

    current_price = clean_number(data.get("closePrice"))
    change_rate = clean_number(data.get("fluctuationsRatio"))

    # 하락(code 4: 하한, 5: 하락)인데 부호가 양수로 오는 경우 음수로 보정
    price_state = (data.get("compareToPreviousPrice") or {}).get("code")
    if change_rate is not None and price_state in {"4", "5"} and change_rate > 0:
        change_rate = -change_rate

    logger.info("[PARSE] 기본 시세 파싱 완료 (name=%s, current_price=%s)", stock_name, current_price)

    return {
        "code": code,
        "name": stock_name,
        "snapshot": {
            "current_price": current_price,
            "change_rate": change_rate,
        },
    }


def fetch_integration_info(code: str) -> dict[str, Any]:
    """네이버 금융 integration API에서 투자정보(시총, PER, PBR 등)를 수집하고 순수 숫자로 정제"""
    code = validate_stock_code(code)
    url = f"https://m.stock.naver.com/api/stock/{code}/integration"

    logger.info("[NAVER] 네이버 금융 integration API 접근 시작 (code=%s)", code)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("네이버 금융 투자정보 응답 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"네이버 금융 투자정보 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code == 404:
        raise ValueError(f"종목 투자정보를 찾을 수 없습니다. (code={code})")
    if resp.status_code != 200:
        raise RuntimeError(f"네이버 금융 투자정보 접근 실패 (HTTP {resp.status_code})")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("네이버 금융 투자정보 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    total_infos = data.get("totalInfos")
    if not isinstance(total_infos, list):
        raise RuntimeError("네이버 금융 투자정보 데이터 구조가 예상과 다릅니다.")

    info_map = {item.get("code"): item.get("value") for item in total_infos if item.get("code")}

    investment_snapshot = {
        "market_cap": parse_korean_amount(info_map.get("marketValue")),
        "per": clean_number(info_map.get("per")),
        "pbr": clean_number(info_map.get("pbr")),
        "eps": clean_number(info_map.get("eps")),
        "bps": clean_number(info_map.get("bps")),
        "estimated_per": clean_number(info_map.get("cnsPer")),
        "estimated_eps": clean_number(info_map.get("cnsEps")),
        "foreign_rate": clean_number(info_map.get("foreignRate")),
        "dividend_yield": clean_number(info_map.get("dividendYieldRatio")),
        "high_52w": clean_number(info_map.get("highPriceOf52Weeks")),
        "low_52w": clean_number(info_map.get("lowPriceOf52Weeks")),
    }

    logger.info(
        "[PARSE] 투자정보 파싱 완료 (market_cap=%s, per=%s, pbr=%s)",
        investment_snapshot["market_cap"],
        investment_snapshot["per"],
        investment_snapshot["pbr"],
    )
    return investment_snapshot


def fetch_financials(code: str) -> list[dict[str, Any]]:
    """네이버 금융 finance/annual API에서 연간 실적을 수집하고 (E) 추정치 신호등(is_consensus)을 구분"""
    code = validate_stock_code(code)
    url = f"https://m.stock.naver.com/api/stock/{code}/finance/annual"

    logger.info("[NAVER] 네이버 금융 연간 실적 API 접근 시작 (code=%s)", code)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("네이버 금융 실적 정보 응답 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"네이버 금융 실적 정보 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code == 404:
        raise ValueError(f"종목 실적 정보를 찾을 수 없습니다. (code={code})")
    if resp.status_code != 200:
        raise RuntimeError(f"네이버 금융 실적 정보 접근 실패 (HTTP {resp.status_code})")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("네이버 금융 실적 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    finance_info = data.get("financeInfo") or {}
    tr_titles = finance_info.get("trTitleList")
    row_list = finance_info.get("rowList")

    if not isinstance(tr_titles, list) or not isinstance(row_list, list):
        raise RuntimeError("네이버 금융 실적 데이터 구조가 예상과 다릅니다.")

    # 항목명 -> {컬럼키: 값} 매핑 생성
    row_map = {
        row.get("title"): row.get("columns", {})
        for row in row_list
        if row.get("title")
    }

    def to_won_from_eok(val: Any) -> int | None:
        num = clean_number(val)
        return int(round(num * 1_0000_0000)) if num is not None else None

    financials: list[dict[str, Any]] = []
    for col in tr_titles:
        col_key = col.get("key")
        if not col_key:
            continue

        raw_title = str(col.get("title", "")).strip().rstrip(".")
        is_consensus = col.get("isConsensus") == "Y"

        def get_cell(row_name: str) -> Any:
            return (row_map.get(row_name, {}).get(col_key) or {}).get("value")

        financials.append(
            {
                "period": raw_title,
                "period_type": "annual",
                "is_consensus": is_consensus,
                "revenue": to_won_from_eok(get_cell("매출액")),
                "operating_income": to_won_from_eok(get_cell("영업이익")),
                "net_income": to_won_from_eok(get_cell("당기순이익")),
                "operating_margin": clean_number(get_cell("영업이익률")),
                "roe": clean_number(get_cell("ROE")),
                "debt_ratio": clean_number(get_cell("부채비율")),
            }
        )

    logger.info("[PARSE] 연간 실적 파싱 완료 (총 %d개 기간)", len(financials))
    return financials


def resolve_market_and_symbol(code_or_name: Any, market_hint: str | None = None) -> tuple[str, str]:
    """입력값(예: '삼성전자', '엔비디아', 'Apple', '000660', 'NVDA')을 보고 자동으로 ('KR'|'US', 코드/티커) 반환"""
    text = str(code_or_name or "").strip()
    if not text:
        raise ValueError("종목명 또는 종목코드를 입력해 주세요. (예: 삼성전자, 엔비디아, Apple, 000660)")

    # 1. 6자리 숫자는 무조건 국내 종목
    if re.fullmatch(r"\d{6}", text):
        return ("KR", text)

    # 2. 명시적으로 US 힌트가 주어진 경우 미국 우선 검색
    if market_hint == "US":
        return ("US", resolve_us_ticker(text))

    # 3. 국내 자동완성(stock) 검색
    kr_items: list[dict[str, Any]] = []
    try:
        r_kr = requests.get(
            "https://ac.stock.naver.com/ac",
            params={"q": text, "target": "stock"},
            headers=NAVER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r_kr.status_code == 200:
            kr_items = [
                item for item in (r_kr.json().get("items") or [])
                if item.get("nationCode") == "KOR" and re.fullmatch(r"\d{6}", str(item.get("code", "")))
            ]
    except Exception:
        pass

    # 국내에 이름이 정확히 일치하는 종목(예: 'NAVER', '삼성전자', 'KODEX 200')이 있으면 국내 확정
    kr_exact = next((i for i in kr_items if str(i.get("name", "")).strip().lower() == text.lower()), None)
    if kr_exact:
        return ("KR", str(kr_exact["code"]))

    # 국내 후보가 있으면 국내 우선 (단, 영문 1~5자 티커는 미국 검색도 함께 확인)
    if kr_items and not re.fullmatch(r"[A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?", text):
        return ("KR", str(kr_items[0]["code"]))

    # 4. 미국(해외) 자동완성(worldstock) 검색 ('엔비디아', 'Apple', 'NVIDIA', 'SCHD' 등)
    try:
        r_us = requests.get(
            "https://ac.stock.naver.com/ac",
            params={"q": text, "target": "worldstock"},
            headers=NAVER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r_us.status_code == 200:
            us_items = [
                item for item in (r_us.json().get("items") or [])
                if item.get("nationCode") == "USA" and item.get("code")
            ]
            if us_items:
                us_exact = next(
                    (
                        i for i in us_items
                        if str(i.get("code", "")).strip().lower() == text.lower()
                        or str(i.get("name", "")).strip().lower() == text.lower()
                    ),
                    None,
                )
                matched = us_exact or us_items[0]
                ticker = str(matched["code"]).strip().upper()
                logger.info("[PARSE] 해외 종목 자동 인식 ('%s' -> US %s)", text, ticker)
                return ("US", ticker)
    except Exception:
        pass

    # 5. 국내 부분 일치 결과가 있었다면 반환
    if kr_items:
        return ("KR", str(kr_items[0]["code"]))

    # 6. 영문 티커 형식이면 미국 티커로 시도
    if re.fullmatch(r"[A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?", text):
        return ("US", text.upper())

    raise ValueError(f"'{text}'에 해당하는 국내/미국 종목을 찾을 수 없습니다.")


def is_us_ticker(code_or_name: Any, market: str | None = None) -> bool:
    """입력값과 시장 선택을 보고 미국 주식/ETF 티커인지 판별"""
    try:
        detected_market, _ = resolve_market_and_symbol(code_or_name, market_hint=market)
        return detected_market == "US"
    except Exception:
        return market == "US"


def resolve_us_ticker(code_or_name: Any) -> str:
    """영문 티커 또는 한글 미국 종목명('엔비디아', '테슬라' 등)을 미국 티커('NVDA')로 변환"""
    text = str(code_or_name or "").strip()
    if not text:
        raise ValueError("미국 종목 티커 또는 종목명을 입력해 주세요. (예: NVDA, 엔비디아)")

    if re.fullmatch(r"[A-Za-z]{1,5}(?:[.-][A-Za-z]{1,2})?", text):
        return text.upper()

    logger.info("[NAVER] 한글 미국 종목명 -> 티커 검색 시작 (query=%s)", text)
    try:
        resp = requests.get(
            "https://ac.stock.naver.com/ac",
            params={"q": text, "target": "worldstock"},
            headers=NAVER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            items = [
                item for item in (resp.json().get("items") or [])
                if item.get("nationCode") == "USA" and item.get("code")
            ]
            if items:
                exact = next((i for i in items if str(i.get("name", "")).strip().lower() == text.lower()), None)
                matched = exact or items[0]
                ticker = str(matched["code"]).strip().upper()
                logger.info("[PARSE] 미국 종목명 매핑 완료 ('%s' -> %s)", text, ticker)
                return ticker
    except Exception as exc:
        logger.warning("[NAVER] 미국 종목명 검색 실패 (%s): %s", text, exc)

    raise ValueError(f"'{text}'에 해당하는 미국 종목을 찾을 수 없습니다. 영문 티커(예: NVDA, AAPL)로 입력해 주세요.")


def fetch_kr_stock_type(code: str) -> str:
    """네이버 basic API에서 국내 종목 유형('etf' | 'stock') 확인"""
    try:
        r = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/basic",
            headers=NAVER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return str(r.json().get("stockEndType") or "stock").lower()
    except Exception:
        pass
    return "stock"


def fetch_kr_etf_info(code: str) -> dict[str, Any]:
    """네이버 금융 ETF 전용 API(api/etf/{code}/basic)에서 ETF 핵심정보 및 구성종목 TOP 10 수집"""
    url = f"https://m.stock.naver.com/api/etf/{code}/basic"
    logger.info("[NAVER] 국내 ETF 전용 API 접근 시작 (code=%s)", code)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("네이버 ETF 정보 응답 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"네이버 ETF 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"네이버 ETF 정보를 불러오지 못했습니다. (HTTP {resp.status_code})")

    d = resp.json()
    current_price = clean_number(d.get("closePrice"))
    change_rate = clean_number(d.get("fluctuationsRatio"))
    price_state = (d.get("compareToPreviousPrice") or {}).get("code")
    if change_rate is not None and price_state in {"4", "5"} and change_rate > 0:
        change_rate = -change_rate

    snapshot = {
        "current_price": current_price,
        "change_rate": change_rate,
        "market_cap": parse_korean_amount(d.get("totalNav") or d.get("marketValue")),
        "per": None,
        "pbr": None,
        "estimated_per": None,
        "foreign_rate": clean_number(d.get("foreignRate")),
        "dividend_yield": clean_number(d.get("dividendYieldTtm")),
        "high_52w": clean_number(d.get("highPriceOf52Weeks")),
        "low_52w": clean_number(d.get("lowPriceOf52Weeks")),
    }

    holdings: list[dict[str, Any]] = []
    for item in (d.get("constituentList") or [])[:10]:
        holdings.append(
            {
                "code": item.get("itemCode") or "",
                "name": item.get("itemName") or "-",
                "weight": round(float(item.get("constituentWeight") or 0), 2),
            }
        )

    summary = str(d.get("etfSummary") or "").strip()
    descriptions = [summary] if summary else []

    etf_info = {
        "issuer": d.get("issuerName") or "-",
        "base_index": d.get("etfBaseIndex") or "-",
        "total_nav": d.get("totalNav") or d.get("marketValue") or "-",
        "total_fee": d.get("totalFee"),
        "nav": clean_number(d.get("nav")),
        "deviation_rate": d.get("deviationRate"),
        "dividend_yield": d.get("dividendYieldTtm"),
        "dividend_per_share": d.get("dividendPerShareTtm"),
        "return_1m": d.get("returnRate1m"),
        "return_3m": d.get("returnRate3m"),
        "return_1y": d.get("returnRate1y"),
        "holdings": holdings,
    }

    logger.info("[PARSE] 국내 ETF 파싱 완료 (name=%s, holdings=%d개)", d.get("stockName"), len(holdings))
    return {
        "code": code,
        "name": d.get("stockName") or code,
        "market": "KR",
        "currency": "KRW",
        "is_etf": True,
        "descriptions": descriptions,
        "snapshot": snapshot,
        "etf_info": etf_info,
    }


def _extract_yf_statement(df: pd.DataFrame, row_mapping: list[tuple[str, list[str]]]) -> dict[str, Any]:
    """yfinance 재무제표 DataFrame을 억원/백만달러($M) 기준 표 구조로 변환"""
    if df is None or df.empty:
        return {"periods": [], "rows": []}

    cols = list(df.columns)[:4]
    cols_sorted = sorted(cols)  # 과거 -> 최신 순 정렬
    periods = [c.strftime("%Y/%m") if hasattr(c, "strftime") else str(c)[:7] for c in cols_sorted]

    rows: list[dict[str, Any]] = []
    for kor_label, candidates in row_mapping:
        matched_key = next((k for k in candidates if k in df.index), None)
        if not matched_key:
            continue

        values: list[float | None] = []
        has_any = False
        for col in cols_sorted:
            val = df.loc[matched_key, col]
            if pd.isna(val):
                values.append(None)
            else:
                # 백만 달러($M) 단위로 반올림
                values.append(round(float(val) / 1_000_000, 1))
                has_any = True

        if has_any:
            rows.append({"name": kor_label, "values": values})

    return {"periods": periods, "rows": rows}


def fetch_us_asset_data(ticker_input: Any) -> dict[str, Any]:
    """yfinance로 미국 주식(EQUITY) 또는 미국 ETF(ETF)의 시세, 설명, 재무/구성종목 수집"""
    ticker = resolve_us_ticker(ticker_input)

    logger.info("[YFINANCE] 미국 종목 조회 시작 (ticker=%s)", ticker)
    t = yf.Ticker(ticker)

    try:
        info = t.info or {}
    except Exception as exc:
        raise RuntimeError(f"미국 종목({ticker}) 정보를 불러오는 중 오류가 발생했습니다: {exc}") from exc

    quote_type = str(info.get("quoteType") or "").upper()
    name = info.get("shortName") or info.get("longName") or ticker
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")

    if current_price is None and not info.get("marketCap") and not info.get("totalAssets"):
        raise ValueError(f"미국 종목 티커 '{ticker}'를 찾을 수 없습니다. 철자를 확인해 주세요.")

    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    change_rate = None
    if current_price is not None and prev_close:
        try:
            change_rate = round(((float(current_price) - float(prev_close)) / float(prev_close)) * 100, 2)
        except Exception:
            change_rate = None

    is_etf = quote_type in {"ETF", "MUTUALFUND"}
    raw_div = info.get("dividendYield")
    # yfinance는 2.95처럼 % 단위 또는 0.0295처럼 소수 단위로 줄 수 있음
    div_pct = None
    if raw_div is not None:
        div_val = float(raw_div)
        div_pct = round(div_val * 100, 2) if div_val < 0.25 else round(div_val, 2)

    snapshot = {
        "current_price": round(float(current_price), 2) if current_price is not None else None,
        "change_rate": change_rate,
        "market_cap": info.get("totalAssets") if is_etf else info.get("marketCap"),
        "per": round(float(info["trailingPE"]), 2) if info.get("trailingPE") else None,
        "estimated_per": round(float(info["forwardPE"]), 2) if info.get("forwardPE") else None,
        "pbr": round(float(info["priceToBook"]), 2) if info.get("priceToBook") else None,
        "foreign_rate": None,
        "dividend_yield": div_pct,
        "high_52w": round(float(info["fiftyTwoWeekHigh"]), 2) if info.get("fiftyTwoWeekHigh") else None,
        "low_52w": round(float(info["fiftyTwoWeekLow"]), 2) if info.get("fiftyTwoWeekLow") else None,
    }

    summary = str(info.get("longBusinessSummary") or "").strip()
    descriptions = [summary[:450] + ("..." if len(summary) > 450 else "")] if summary else []

    result: dict[str, Any] = {
        "code": ticker,
        "name": name,
        "market": "US",
        "currency": "USD",
        "is_etf": is_etf,
        "descriptions": descriptions,
        "description_sources": [
            {"label": "Yahoo Finance 기업 개요", "url": f"https://finance.yahoo.com/quote/{ticker}/profile"},
            {"label": "SEC EDGAR 공식 공시", "url": f"https://www.sec.gov/edgar/searchedgar/companysearch?q={ticker}"},
        ],
        "snapshot": snapshot,
    }

    if is_etf:
        holdings: list[dict[str, Any]] = []
        try:
            top_h = t.funds_data.top_holdings
            if top_h is not None and not top_h.empty:
                for sym, row in top_h.head(10).iterrows():
                    holdings.append(
                        {
                            "code": str(sym),
                            "name": str(row.get("Name") or sym),
                            "weight": round(float(row.get("Holding Percent") or 0) * 100, 2),
                        }
                    )
        except Exception as exc:
            logger.warning("[YFINANCE] 미국 ETF 구성종목 생략 (%s): %s", ticker, exc)

        total_assets = info.get("totalAssets")
        total_nav_str = f"${round(total_assets / 1_000_000_000, 2)}B" if total_assets else "-"
        fee_raw = info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")
        fee_pct = round(float(fee_raw), 2) if fee_raw is not None and float(fee_raw) > 0.05 else (round(float(fee_raw) * 100, 2) if fee_raw is not None else None)

        result["etf_info"] = {
            "issuer": info.get("fundFamily") or "-",
            "base_index": info.get("category") or "US ETF",
            "total_nav": total_nav_str,
            "total_fee": fee_pct,
            "nav": round(float(info["navPrice"]), 2) if info.get("navPrice") else snapshot["current_price"],
            "deviation_rate": None,
            "dividend_yield": div_pct,
            "dividend_per_share": None,
            "return_1m": None,
            "return_3m": None,
            "return_1y": round(float(info["fiftyTwoWeekChangePercent"]), 2) if info.get("fiftyTwoWeekChangePercent") else None,
            "holdings": holdings,
        }
    else:
        income_map = [
            ("매출액(Revenue)", ["Total Revenue", "Operating Revenue"]),
            ("매출총이익(Gross Profit)", ["Gross Profit"]),
            ("영업이익(Operating Income)", ["Operating Income", "Total Operating Income As Reported"]),
            ("당기순이익(Net Income)", ["Net Income", "Net Income Common Stockholders"]),
        ]
        balance_map = [
            ("자산총계(Total Assets)", ["Total Assets"]),
            ("유동자산(Current Assets)", ["Current Assets"]),
            ("부채총계(Total Liabilities)", ["Total Liabilities Net Minority Interest"]),
            ("자본총계(Stockholders Equity)", ["Stockholders Equity", "Total Equity Gross Minority Interest"]),
        ]
        cashflow_map = [
            ("영업활동현금흐름(Operating CF)", ["Operating Cash Flow"]),
            ("투자활동현금흐름(Investing CF)", ["Investing Cash Flow"]),
            ("재무활동현금흐름(Financing CF)", ["Financing Cash Flow"]),
            ("잉여현금흐름(Free Cash Flow)", ["Free Cash Flow"]),
        ]
        result["statements"] = {
            "income": _extract_yf_statement(t.income_stmt, income_map),
            "balance": _extract_yf_statement(t.balance_sheet, balance_map),
            "cashflow": _extract_yf_statement(t.cashflow, cashflow_map),
            "unit": "백만 달러 ($M)",
        }

    logger.info("[PARSE] 미국 종목 파싱 완료 (ticker=%s, is_etf=%s)", ticker, is_etf)
    return result


def fetch_news(stock_name: str, num: int = 5, gl: str = "kr") -> list[dict[str, Any]]:
    """파싱된 정식 종목명으로 Serper News API를 호출하여 최신 뉴스 5건 수집"""
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Serper API Key가 설정되지 않았습니다. (.env 파일을 확인해 주세요)")

    url = "https://google.serper.dev/news"
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": stock_name,
        "gl": gl,
        "hl": "ko" if gl == "kr" else "en",
        "num": num,
    }

    logger.info("[SERPER] Serper News API 호출 시작 (query=%s)", stock_name)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("Serper 뉴스 검색 응답 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Serper 뉴스 검색 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code in {401, 403}:
        raise RuntimeError("Serper API Key가 유효하지 않거나 권한이 없습니다.")
    if resp.status_code != 200:
        raise RuntimeError(f"Serper API 호출 실패 (HTTP {resp.status_code})")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("Serper API 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    raw_news = data.get("news") or []
    news_list: list[dict[str, Any]] = []
    for item in raw_news[:num]:
        news_list.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "date": item.get("date", ""),
            }
        )

    logger.info("[SERPER] 뉴스 수집 완료 (수집=%d건)", len(news_list))
    return news_list


def collect_stock_data(code_or_ticker: str, market: str | None = None) -> dict[str, Any]:
    """국내/미국 주식·ETF를 자동 판별하여 시세/투자정보/실적(또는 ETF 정보)/뉴스를 통합 수집"""
    errors: list[str] = []
    detected_market, resolved_symbol = resolve_market_and_symbol(code_or_ticker, market_hint=market)

    # 0. 미국 주식/ETF
    if detected_market == "US":
        us_data = fetch_us_asset_data(resolved_symbol)
        stock_code = us_data["code"]
        stock_name = us_data["name"]
        news: list[dict[str, Any]] = []
        try:
            news = fetch_news(f"{stock_code} stock", num=5, gl="us")
        except Exception as exc:
            logger.exception("[ERROR] 미국 뉴스 수집 실패")
            errors.append(f"뉴스: {exc}")

        return {
            "code": stock_code,
            "name": stock_name,
            "market": "US",
            "currency": "USD",
            "is_etf": us_data["is_etf"],
            "snapshot": us_data["snapshot"],
            "financials": [],
            "etf_info": us_data.get("etf_info"),
            "news": news,
            "errors": errors,
        }

    # 1. 국내 종목 코드 확정 및 ETF 여부 판별
    resolved_code = resolved_symbol
    stock_type = fetch_kr_stock_type(resolved_code)

    if stock_type == "etf":
        etf_data = fetch_kr_etf_info(resolved_code)
        news = []
        try:
            news = fetch_news(etf_data["name"], num=5, gl="kr")
        except Exception as exc:
            logger.exception("[ERROR] ETF 뉴스 수집 실패")
            errors.append(f"뉴스: {exc}")

        return {
            "code": etf_data["code"],
            "name": etf_data["name"],
            "market": "KR",
            "currency": "KRW",
            "is_etf": True,
            "snapshot": etf_data["snapshot"],
            "financials": [],
            "etf_info": etf_data["etf_info"],
            "news": news,
            "errors": errors,
        }

    # 2. 국내 일반 기업
    basic = fetch_basic_info(resolved_code)
    stock_code = basic["code"]
    stock_name = basic["name"]
    snapshot = basic["snapshot"]

    try:
        invest = fetch_integration_info(stock_code)
        snapshot.update(invest)
    except Exception as exc:
        logger.exception("[ERROR] 투자정보 수집 실패")
        errors.append(f"투자정보: {exc}")

    financials: list[dict[str, Any]] = []
    try:
        financials = fetch_financials(stock_code)
    except Exception as exc:
        logger.exception("[ERROR] 실적 정보 수집 실패")
        errors.append(f"실적정보: {exc}")

    news = []
    try:
        news = fetch_news(stock_name, num=5, gl="kr")
    except Exception as exc:
        logger.exception("[ERROR] 뉴스 수집 실패")
        errors.append(f"뉴스: {exc}")

    logger.info(
        "[RESPONSE] 수집 완료 (name=%s, financials=%d, news=%d, errors=%d)",
        stock_name,
        len(financials),
        len(news),
        len(errors),
    )

    return {
        "code": stock_code,
        "name": stock_name,
        "market": "KR",
        "currency": "KRW",
        "is_etf": False,
        "snapshot": snapshot,
        "financials": financials,
        "etf_info": None,
        "news": news,
        "errors": errors,
    }


def _clean_yymm_label(raw: str) -> str:
    """'2025/12<br /><span>(IFRS연결)</span>' -> '2025/12' 형태로 정제"""
    no_tags = re.sub(r"<[^>]+>", " ", str(raw or ""))
    first_token = no_tags.strip().split()[0] if no_tags.strip() else ""
    return first_token


def fetch_financial_statements(code_or_name: Any, market: str | None = None) -> dict[str, Any]:
    """종목 설명, 현재 주가 및 (기업이면 3대 재무제표, ETF면 ETF 전용 정보) 수집"""
    detected_market, resolved_symbol = resolve_market_and_symbol(code_or_name, market_hint=market)
    if detected_market == "US":
        return fetch_us_asset_data(resolved_symbol)

    code = resolved_symbol
    if fetch_kr_stock_type(code) == "etf":
        return fetch_kr_etf_info(code)

    basic = fetch_basic_info(code)
    stock_name = basic["name"]
    snapshot = dict(basic["snapshot"])

    try:
        snapshot.update(fetch_integration_info(code))
    except Exception as exc:
        logger.warning("[NAVER] 재무분석 탭 투자정보 일부 생략 (%s): %s", code, exc)

    # 1. 기업 개요 설명 (comment1~3)
    descriptions: list[str] = []
    try:
        r_ann = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/finance/annual",
            headers=NAVER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r_ann.status_code == 200:
            corp_summary = r_ann.json().get("corporationSummary") or {}
            for key in ("comment1", "comment2", "comment3"):
                val = str(corp_summary.get(key) or "").strip()
                if val:
                    descriptions.append(val)
    except Exception as exc:
        logger.warning("[NAVER] 기업개요 수집 생략 (%s): %s", code, exc)

    # 2. WiseReport cF3002.aspx (포괄손익계산서=0, 재무상태표=1, 현금흐름표=2)
    session = requests.Session()
    ref_url = f"https://navercomp.wisereport.co.kr/v3/company/c1030001.aspx?cmp_cd={code}"
    wise_headers = {
        "User-Agent": NAVER_HEADERS["User-Agent"],
        "Referer": ref_url,
    }

    logger.info("[NAVER] WiseReport 상세 재무제표 조회 시작 (code=%s)", code)
    try:
        r_page = session.get(ref_url, headers=wise_headers, timeout=REQUEST_TIMEOUT)
        enc_match = re.search(r"encparam\s*:\s*['\"]([A-Za-z0-9=]+)['\"]", r_page.text)
        if not enc_match:
            raise RuntimeError("재무제표 인증 토큰(encparam)을 찾지 못했습니다.")
        encparam = enc_match.group(1)
    except requests.RequestException as exc:
        raise RuntimeError(f"재무제표 페이지 연결에 실패했습니다: {exc}") from exc

    statements: dict[str, Any] = {}
    rpt_map = {
        "income": 0,    # 포괄손익계산서
        "balance": 1,   # 재무상태표
        "cashflow": 2,  # 현금흐름표
    }

    for key, rpt_code in rpt_map.items():
        try:
            r_rpt = session.get(
                "https://navercomp.wisereport.co.kr/v3/company/cF3002.aspx",
                params={
                    "cmp_cd": code,
                    "frq": 0,
                    "rpt": rpt_code,
                    "finGubun": "MAIN",
                    "frqTyp": 0,
                    "encparam": encparam,
                },
                headers=wise_headers,
                timeout=REQUEST_TIMEOUT,
            )
            payload = r_rpt.json()
        except Exception as exc:
            logger.warning("[ERROR] %s 표 파싱 실패: %s", key, exc)
            statements[key] = {"periods": [], "rows": []}
            continue

        raw_yymm = payload.get("YYMM") or []
        # 앞 6개 연도 컬럼만 추출 (전년대비 YoY 컬럼 제외)
        periods = [_clean_yymm_label(lbl) for lbl in raw_yymm[:6] if "전년대비" not in str(lbl)]
        col_count = len(periods)

        rows: list[dict[str, Any]] = []
        for row in payload.get("DATA") or []:
            acc_name = str(row.get("ACC_NM") or "").strip()
            if row.get("LVL") != 1 or not acc_name or acc_name.startswith("*"):
                continue

            values: list[float | None] = []
            has_any = False
            for idx in range(1, col_count + 1):
                raw_val = row.get(f"DATA{idx}")
                if raw_val is None:
                    values.append(None)
                else:
                    try:
                        num = round(float(raw_val), 1)
                        values.append(num)
                        has_any = True
                    except (TypeError, ValueError):
                        values.append(None)

            if has_any:
                rows.append({"name": acc_name, "values": values})

            if len(rows) >= 12:
                break

        statements[key] = {
            "periods": periods,
            "rows": rows,
        }

    logger.info(
        "[PARSE] 상세 재무제표 파싱 완료 (name=%s, 손익=%d행, 재무상태=%d행, 현금흐름=%d행)",
        stock_name,
        len(statements["income"]["rows"]),
        len(statements["balance"]["rows"]),
        len(statements["cashflow"]["rows"]),
    )

    from urllib.parse import quote

    return {
        "code": code,
        "name": stock_name,
        "descriptions": descriptions,
        "description_sources": [
            {"label": "네이버 금융 기업개요", "url": f"https://finance.naver.com/item/main.naver?code={code}"},
            {"label": "DART 전자공시", "url": f"https://dart.fss.or.kr/dsab001/main.do?textCrpNm={quote(stock_name)}"},
        ],
        "snapshot": snapshot,
        "statements": statements,
    }


def _classify_disclosure(title: str) -> str:
    """공시 제목을 기반으로 초보자용 6대 카테고리로 분류"""
    t = title.replace(" ", "")
    if any(k in t for k in ("자기주식처분", "자사주처분", "주식소각", "자기주식소각")):
        return "자사주 처분"
    if any(k in t for k in ("자기주식취득", "자사주취득", "자기주식신탁")):
        return "자사주 취득"
    if any(k in t for k in ("배당", "주주총회", "주주환원")):
        return "주주환원"
    if any(k in t for k in ("사업보고서", "반기보고서", "분기보고서", "감사보고서")):
        return "정기보고서"
    if any(k in t for k in ("잠정실적", "영업실적", "매출액또는손익구조", "실적")):
        return "실적"
    if any(k in t for k in ("임원", "주요주주", "최대주주", "대량보유", "특수관계인", "소유상황")):
        return "임원/주요주주"
    return "기타 공시"


_SEC_HEADERS = {
    "User-Agent": "InvestmentAssistant/1.0 (contact@example.com)",
}
_SEC_CIK_CACHE: dict[str, tuple[str, str]] = {}


def _get_sec_company_info(ticker: str) -> tuple[str | None, str | None]:
    """SEC EDGAR company_tickers.json에서 미국 종목의 10자리 CIK와 공식 회사명을 조회"""
    sym = ticker.upper().strip()
    if sym in _SEC_CIK_CACHE:
        return _SEC_CIK_CACHE[sym]

    try:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=_SEC_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            for entry in data.values() if isinstance(data, dict) else []:
                t = str(entry.get("ticker") or "").upper().strip()
                cik = str(entry.get("cik_str") or "").zfill(10)
                title = str(entry.get("title") or "").strip()
                if t and cik:
                    _SEC_CIK_CACHE[t] = (cik, title)
            if sym in _SEC_CIK_CACHE:
                return _SEC_CIK_CACHE[sym]
    except Exception as exc:
        logger.warning("[SEC] company_tickers 조회 실패 (ticker=%s): %s", sym, exc)

    return None, None


def _classify_sec_form(form: str, desc: str) -> str:
    """SEC EDGAR 공시 양식(Form)을 초보자용 카테고리로 분류"""
    f = form.upper().strip()
    d = desc.lower()
    if f in {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "40-F", "6-K"}:
        return "정기보고서"
    if f.startswith("8-K") and any(k in d for k in ("result", "earning", "financial", "quarter")):
        return "실적"
    if f in {"4", "3", "5", "144", "SC 13D", "SC 13G", "SC 13D/A", "SC 13G/A"}:
        return "임원/주요주주"
    if "14A" in f or "dividend" in d:
        return "주주환원"
    if "repurchase" in d or "buyback" in d:
        return "자사주 취득"
    return "기타 공시"


def _format_sec_title(form: str, desc: str) -> str:
    """SEC 공시 양식 코드를 한국어 설명과 함께 읽기 쉽게 표기"""
    f = form.upper().strip()
    label_map = {
        "10-K": "연간 사업보고서 (Annual Report)",
        "10-Q": "분기 보고서 (Quarterly Report)",
        "8-K": "수시 공시 · 주요 경영사항 (Current Report)",
        "4": "임원·주요주주 지분 변동 신고 (Insider Trading)",
        "3": "최초 임원·주요주주 지분 신고",
        "5": "연간 임원 지분 변동 신고",
        "144": "임원·특수관계인 주식 매도 예정 신고",
        "DEF 14A": "정기 주주총회 위임장 권유서 (Proxy Statement)",
        "20-F": "외국기업 연간 사업보고서",
        "6-K": "외국기업 수시 보고서",
        "S-3": "유가증권 일괄신고서",
        "25-NSE": "거래소 상장/변경 통지",
    }
    ko_desc = label_map.get(f)
    if ko_desc:
        return f"[Form {f}] {ko_desc}"
    if desc and desc != f:
        return f"[Form {f}] {desc}"
    return f"[Form {f}] SEC 전자공시"


def _fetch_sec_disclosures(ticker: str) -> dict[str, Any]:
    """미국 종목의 SEC EDGAR 최근 공시 최대 20건을 조회"""
    from urllib.parse import quote

    sec_search_url = f"https://www.sec.gov/edgar/searchedgar/companysearch?q={quote(ticker)}"
    cik, sec_company_name = _get_sec_company_info(ticker)
    display_name = sec_company_name or ticker
    sec_browse_url = f"https://www.sec.gov/edgar/browse/?CIK={cik}" if cik else sec_search_url

    disclosures: list[dict[str, Any]] = []
    if cik:
        try:
            sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            logger.info("[SEC] 최근 공시 API 접근 시작 (ticker=%s, cik=%s)", ticker, cik)
            resp = requests.get(sub_url, headers=_SEC_HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                payload = resp.json()
                display_name = payload.get("name") or display_name
                recent = (payload.get("filings") or {}).get("recent") or {}
                forms = recent.get("form") or []
                dates = recent.get("filingDate") or []
                accs = recent.get("accessionNumber") or []
                docs = recent.get("primaryDocument") or []
                descs = recent.get("primaryDocDescription") or []

                cik_int = str(int(cik))
                limit = min(20, len(forms))
                for idx in range(limit):
                    form = str(forms[idx] or "").strip()
                    filing_date = str(dates[idx] if idx < len(dates) else "").strip()
                    acc_no = str(accs[idx] if idx < len(accs) else "").strip()
                    primary_doc = str(docs[idx] if idx < len(docs) else "").strip()
                    desc = str(descs[idx] if idx < len(descs) else "").strip()

                    acc_clean = acc_no.replace("-", "")
                    if acc_clean and primary_doc:
                        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{primary_doc}"
                    else:
                        doc_url = sec_browse_url

                    disclosures.append(
                        {
                            "id": acc_no or f"{ticker}-{idx}",
                            "category": _classify_sec_form(form, desc),
                            "title": _format_sec_title(form, desc),
                            "datetime": filing_date,
                            "author": "SEC EDGAR",
                            "source": "SEC",
                            "url": doc_url,
                            "dart_url": sec_browse_url,
                        }
                    )
                logger.info("[PARSE] SEC 공시 파싱 완료 (ticker=%s, 총 %d건)", ticker, len(disclosures))
        except Exception as exc:
            logger.warning("[SEC] submissions 조회 실패 (ticker=%s): %s", ticker, exc)

    return {
        "code": ticker,
        "name": display_name,
        "market": "US (SEC EDGAR)",
        "is_us": True,
        "source_type": "SEC",
        "dart_links": {
            "home": "https://www.sec.gov/edgar/searchedgar/companysearch",
            "browse": sec_browse_url,
            "corp_search": sec_browse_url,
        },
        "disclosures": disclosures,
    }


def fetch_disclosures(code_or_name: Any, market: str | None = None) -> dict[str, Any]:
    """종목의 최근 공시 20건을 카테고리별로 분류하고 DART(미국은 SEC) 바로가기 링크와 함께 반환"""
    from urllib.parse import quote

    detected_market, resolved_symbol = resolve_market_and_symbol(code_or_name, market_hint=market)
    if detected_market == "US":
        return _fetch_sec_disclosures(resolved_symbol)

    code = resolved_symbol
    basic = fetch_basic_info(code)
    stock_name = basic["name"]

    # 시장 구분(KOSPI / KOSDAQ) 확인
    market = "KOSPI"
    try:
        r_basic = requests.get(
            f"https://m.stock.naver.com/api/stock/{code}/basic",
            headers=NAVER_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r_basic.status_code == 200:
            market = r_basic.json().get("stockExchangeName") or "KOSPI"
    except Exception:
        pass

    url = f"https://m.stock.naver.com/api/stock/{code}/disclosure"
    logger.info("[NAVER] 최근 공시 API 접근 시작 (code=%s)", code)

    try:
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise RuntimeError("네이버 금융 공시 응답 시간이 초과되었습니다.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"네이버 금융 공시 네트워크 연결에 실패했습니다: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"공시 정보를 불러오지 못했습니다. (HTTP {resp.status_code})")

    try:
        raw_list = resp.json()
    except ValueError as exc:
        raise RuntimeError("공시 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    dart_corp_search = f"https://dart.fss.or.kr/dsab001/main.do?textCrpNm={quote(stock_name)}"
    disclosures: list[dict[str, Any]] = []
    for item in raw_list if isinstance(raw_list, list) else []:
        title = str(item.get("title") or "").strip()
        disc_id = item.get("disclosureId")
        dt_str = str(item.get("datetime") or "").replace("T", " ")[:16]
        disclosures.append(
            {
                "id": disc_id,
                "category": _classify_disclosure(title),
                "title": title,
                "datetime": dt_str,
                "author": item.get("author") or "DART/거래소",
                "url": f"https://m.stock.naver.com/domestic/stock/{code}/disclosure/{disc_id}" if disc_id else dart_corp_search,
                "dart_url": dart_corp_search,
            }
        )

    logger.info("[PARSE] 최근 공시 파싱 완료 (name=%s, 총 %d건)", stock_name, len(disclosures))

    return {
        "code": code,
        "name": stock_name,
        "market": market,
        "is_us": False,
        "source_type": "DART",
        "dart_links": {
            "home": "https://dart.fss.or.kr/",
            "kospi": "https://dart.fss.or.kr/dsac001/mainY.do",
            "kosdaq": "https://dart.fss.or.kr/dsac001/mainK.do?selectDate=&sort=&series=&mdayCnt=0",
            "corp_search": dart_corp_search,
        },
        "disclosures": disclosures,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    result = collect_stock_data("000660")
    logger.info("[TEST] 4차 통합 수집 결과: name=%s, news=%d건, errors=%s", result["name"], len(result["news"]), result["errors"])
