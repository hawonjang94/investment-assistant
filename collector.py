import logging
import os
import re
from typing import Any

import requests
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


def fetch_news(stock_name: str, num: int = 5) -> list[dict[str, Any]]:
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
        "gl": "kr",
        "hl": "ko",
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


def collect_stock_data(code: str) -> dict[str, Any]:
    """종목코드를 받아 시세/투자정보, 연간실적, 뉴스까지 통합 수집 (부분 실패 시 errors에 기록)"""
    errors: list[str] = []

    # 1. 기본 시세 및 정식 종목명 파싱 (실패 시 뉴스 검색이 불가하므로 여기서 중단)
    basic = fetch_basic_info(code)
    stock_code = basic["code"]
    stock_name = basic["name"]
    snapshot = basic["snapshot"]

    # 2. 투자정보 (시총, PER, PBR 등)
    try:
        invest = fetch_integration_info(stock_code)
        snapshot.update(invest)
    except Exception as exc:
        logger.exception("[ERROR] 투자정보 수집 실패")
        errors.append(f"투자정보: {exc}")

    # 3. 연간 실적
    financials: list[dict[str, Any]] = []
    try:
        financials = fetch_financials(stock_code)
    except Exception as exc:
        logger.exception("[ERROR] 실적 정보 수집 실패")
        errors.append(f"실적정보: {exc}")

    # 4. 파싱된 정식 종목명으로 Serper 뉴스 수집
    news: list[dict[str, Any]] = []
    try:
        news = fetch_news(stock_name, num=5)
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
        "snapshot": snapshot,
        "financials": financials,
        "news": news,
        "errors": errors,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    result = collect_stock_data("000660")
    logger.info("[TEST] 4차 통합 수집 결과: name=%s, news=%d건, errors=%s", result["name"], len(result["news"]), result["errors"])
