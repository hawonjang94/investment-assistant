import logging
from datetime import datetime, timedelta
from typing import Any

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

from collector import fetch_basic_info, resolve_market_and_symbol

logger = logging.getLogger(__name__)


def _to_clean_list(series: pd.Series, decimals: int = 2) -> list[float | int | None]:
    """Pandas Series의 NaN을 JSON 호환 None으로 변환하며 반올림"""
    result: list[float | int | None] = []
    for val in series:
        if pd.isna(val) or not np.isfinite(val):
            result.append(None)
        elif decimals == 0:
            result.append(int(round(float(val))))
        else:
            result.append(round(float(val), decimals))
    return result


def _to_clean_scalar(val: Any, decimals: int = 2) -> float | int | None:
    """단일 수치의 NaN을 None으로 안전 변환"""
    if val is None or pd.isna(val) or not np.isfinite(val):
        return None
    return int(round(float(val))) if decimals == 0 else round(float(val), decimals)


def calculate_technical_indicators(
    code_or_name: Any,
    lookback_days: int = 300,
    chart_bars: int = 90,
) -> dict[str, Any]:
    """FinanceDataReader로 주가를 수집하고 MA, RSI, MACD, 볼린저밴드를 계산"""
    market, code = resolve_market_and_symbol(code_or_name)

    # 종목명 확인
    stock_name = code
    if market == "KR":
        try:
            stock_name = fetch_basic_info(code)["name"]
        except Exception:
            stock_name = code

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=lookback_days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    logger.info("[FDR] 기술지표용 주가 조회 시작 (code=%s, %s ~ %s)", code, start_str, end_str)

    try:
        df = fdr.DataReader(code, start_str, end_str)
    except Exception as exc:
        raise RuntimeError(f"종목({code}) 주가 데이터를 불러오지 못했습니다: {exc}") from exc

    if df is None or df.empty or "Close" not in df.columns:
        raise ValueError(f"종목({code})의 주가 데이터가 비어 있습니다.")

    df = df.sort_index().copy()
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()

    if len(close) < 30:
        raise ValueError("기술지표 계산을 위한 거래일 데이터(최소 30일)가 부족합니다.")

    # 1. 이동평균선 (MA 5, 20, 60)
    ma5 = close.rolling(window=5).mean()
    ma20 = close.rolling(window=20).mean()
    ma60 = close.rolling(window=60).mean()

    # 2. 볼린저밴드 (20, 2)
    std20 = close.rolling(window=20).std()
    bb_upper = ma20 + (2 * std20)
    bb_mid = ma20
    bb_lower = ma20 - (2 * std20)

    # 3. RSI (14) - Wilder 방식 지수이동평균
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi14 = 100 - (100 / (1 + rs))
    rsi14 = rsi14.where(avg_loss != 0, 100.0)

    # 4. MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    # 최근 차트 표시 구간만 슬라이싱
    recent_idx = close.index[-chart_bars:]
    dates = [dt.strftime("%Y-%m-%d") for dt in recent_idx]

    latest = {
        "date": dates[-1],
        "close": _to_clean_scalar(close.iloc[-1], decimals=0),
        "ma5": _to_clean_scalar(ma5.iloc[-1], decimals=0),
        "ma20": _to_clean_scalar(ma20.iloc[-1], decimals=0),
        "ma60": _to_clean_scalar(ma60.iloc[-1], decimals=0),
        "rsi14": _to_clean_scalar(rsi14.iloc[-1], decimals=2),
        "macd": _to_clean_scalar(macd.iloc[-1], decimals=2),
        "macd_signal": _to_clean_scalar(macd_signal.iloc[-1], decimals=2),
        "macd_hist": _to_clean_scalar(macd_hist.iloc[-1], decimals=2),
        "bb_upper": _to_clean_scalar(bb_upper.iloc[-1], decimals=0),
        "bb_mid": _to_clean_scalar(bb_mid.iloc[-1], decimals=0),
        "bb_lower": _to_clean_scalar(bb_lower.iloc[-1], decimals=0),
    }

    series = {
        "dates": dates,
        "close": _to_clean_list(close.iloc[-chart_bars:], decimals=0),
        "ma5": _to_clean_list(ma5.iloc[-chart_bars:], decimals=0),
        "ma20": _to_clean_list(ma20.iloc[-chart_bars:], decimals=0),
        "ma60": _to_clean_list(ma60.iloc[-chart_bars:], decimals=0),
        "bb_upper": _to_clean_list(bb_upper.iloc[-chart_bars:], decimals=0),
        "bb_lower": _to_clean_list(bb_lower.iloc[-chart_bars:], decimals=0),
        "rsi14": _to_clean_list(rsi14.iloc[-chart_bars:], decimals=2),
        "macd": _to_clean_list(macd.iloc[-chart_bars:], decimals=2),
        "macd_signal": _to_clean_list(macd_signal.iloc[-chart_bars:], decimals=2),
        "macd_hist": _to_clean_list(macd_hist.iloc[-chart_bars:], decimals=2),
    }

    logger.info(
        "[CALC] 기술지표 계산 완료 (name=%s, date=%s, close=%s, rsi14=%s, macd=%s)",
        stock_name,
        latest["date"],
        latest["close"],
        latest["rsi14"],
        latest["macd"],
    )

    return {
        "code": code,
        "name": stock_name,
        "latest": latest,
        "series": series,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    res = calculate_technical_indicators("000660")
    logger.info("[TEST] 최신 기술지표 요약: %s", res["latest"])
