import logging
from datetime import datetime, timedelta
from typing import Any

import FinanceDataReader as fdr
import numpy as np
import pandas as pd

from collector import fetch_basic_info, resolve_stock_code

logger = logging.getLogger(__name__)


def parse_stock_list(raw_codes: Any) -> list[str]:
    """문자열('000660, 005930') 또는 리스트 입력을 중복 없는 6자리 종목코드 리스트로 정규화"""
    if isinstance(raw_codes, str):
        tokens = [t.strip() for t in re_split_codes(raw_codes) if t.strip()]
    elif isinstance(raw_codes, list):
        tokens = [str(t).strip() for t in raw_codes if str(t).strip()]
    else:
        raise ValueError("종목 목록 형식이 올바르지 않습니다.")

    resolved: list[str] = []
    for token in tokens:
        code = resolve_stock_code(token)
        if code not in resolved:
            resolved.append(code)

    if len(resolved) < 2:
        raise ValueError("리밸런싱 계산을 위해 최소 2개 이상의 서로 다른 종목을 입력해 주세요.")
    if len(resolved) > 10:
        raise ValueError("한 번에 최대 10개 종목까지만 분석할 수 있습니다.")

    return resolved


def re_split_codes(text: str) -> list[str]:
    """쉼표, 줄바꿈, 슬래시 등으로 구분된 종목 입력 분리"""
    import re
    return re.split(r"[,/\n;]+", text)


def fetch_portfolio_prices(codes_input: Any, days: int = 365) -> tuple[pd.DataFrame, dict[str, str]]:
    """FinanceDataReader로 복수 종목의 최근 1년 종가 데이터를 수집하고 날짜 정렬/결측치 처리"""
    codes = parse_stock_list(codes_input)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    logger.info("[FDR] 포트폴리오 최근 1년 주가 조회 시작 (codes=%s, %s ~ %s)", codes, start_str, end_str)

    close_series_map: dict[str, pd.Series] = {}
    name_map: dict[str, str] = {}

    for code in codes:
        try:
            df = fdr.DataReader(code, start_str, end_str)
        except Exception as exc:
            raise RuntimeError(f"종목({code}) 주가 데이터를 불러오지 못했습니다: {exc}") from exc

        if df is None or df.empty or "Close" not in df.columns:
            raise ValueError(f"종목({code})의 최근 1년 주가 데이터가 비어 있습니다.")

        # 종목명 확보 (실패해도 코드로 대체)
        try:
            basic = fetch_basic_info(code)
            name_map[code] = basic["name"]
        except Exception:
            name_map[code] = code

        close_series = pd.to_numeric(df["Close"], errors="coerce").dropna()
        close_series_map[code] = close_series

    prices_df = pd.DataFrame(close_series_map).sort_index()
    # 거래일 차이로 인한 결측치는 직전 종가로 채운 뒤 앞부분 공통 구간만 유지
    prices_df = prices_df.ffill().dropna()

    if len(prices_df) < 20:
        raise ValueError("공통 거래일 데이터가 너무 적어(20일 미만) 포트폴리오를 계산할 수 없습니다.")

    logger.info(
        "[FDR] 포트폴리오 종가 수집 완료 (종목=%d개, 공통 거래일=%d일)",
        len(codes),
        len(prices_df),
    )
    return prices_df, name_map


def _calc_mdd(cum_returns: pd.Series) -> float:
    """누적 수익률(또는 가격) 시리즈에서 최대 낙폭(MDD, %) 계산"""
    peak = cum_returns.cummax()
    drawdown = (cum_returns / peak) - 1.0
    return round(float(drawdown.min() * 100), 2)


def calculate_rebalancing(
    codes_input: Any,
    num_portfolios: int = 3000,
    risk_free_rate: float = 0.03,
) -> dict[str, Any]:
    """단순화 몬테카를로 시뮬레이션 및 효율적 프론티어로 적정 비중과 근거를 계산"""
    prices_df, name_map = fetch_portfolio_prices(codes_input, days=365)
    returns = prices_df.pct_change().dropna()
    codes = list(prices_df.columns)
    num_assets = len(codes)

    mean_returns = returns.mean() * 252
    cov_matrix = returns.cov() * 252

    # 몬테카를로 난수 시뮬레이션
    all_weights = np.random.random((num_portfolios, num_assets))
    all_weights = all_weights / all_weights.sum(axis=1, keepdims=True)

    port_returns = all_weights @ mean_returns.values
    port_vols = np.sqrt(
        np.einsum("ij,jk,ik->i", all_weights, cov_matrix.values, all_weights)
    )
    sharpe_ratios = np.where(
        port_vols > 0,
        (port_returns - risk_free_rate) / port_vols,
        -np.inf,
    )

    best_idx = int(np.argmax(sharpe_ratios))
    min_vol_idx = int(np.argmin(port_vols))

    best_weights = all_weights[best_idx]
    best_ret = float(port_returns[best_idx])
    best_vol = float(port_vols[best_idx])
    best_sharpe = float(sharpe_ratios[best_idx])

    # 최적 비중 포트폴리오의 최근 1년 MDD 계산
    portfolio_daily_ret = (returns.values @ best_weights)
    portfolio_cum = pd.Series((1.0 + portfolio_daily_ret).cumprod(), index=returns.index)
    best_mdd = _calc_mdd(portfolio_cum)

    # 개별 종목별 요약
    assets_summary: list[dict[str, Any]] = []
    for idx, code in enumerate(codes):
        asset_cum = (1.0 + returns[code]).cumprod()
        assets_summary.append(
            {
                "code": code,
                "name": name_map.get(code, code),
                "weight": round(float(best_weights[idx] * 100), 2),
                "min_vol_weight": round(float(all_weights[min_vol_idx][idx] * 100), 2),
                "annual_return": round(float(mean_returns[code] * 100), 2),
                "annual_volatility": round(float(returns[code].std() * np.sqrt(252) * 100), 2),
                "mdd": _calc_mdd(asset_cum),
            }
        )

    # 차트 시각화용 산점도 샘플 (최대 150개)
    step = max(1, num_portfolios // 150)
    scatter_points = [
        {
            "x": round(float(port_vols[i] * 100), 2),
            "y": round(float(port_returns[i] * 100), 2),
            "sharpe": round(float(sharpe_ratios[i]), 2),
        }
        for i in range(0, num_portfolios, step)
    ]

    logger.info(
        "[CALC] 몬테카를로 계산 완료 (시뮬=%d회, 최적 샤프=%.2f, 연수익=%.2f%%, 변동성=%.2f%%, MDD=%.2f%%)",
        num_portfolios,
        best_sharpe,
        best_ret * 100,
        best_vol * 100,
        best_mdd,
    )

    return {
        "period": {
            "start": prices_df.index[0].strftime("%Y-%m-%d"),
            "end": prices_df.index[-1].strftime("%Y-%m-%d"),
            "trading_days": len(prices_df),
        },
        "optimal": {
            "expected_return": round(best_ret * 100, 2),
            "volatility": round(best_vol * 100, 2),
            "sharpe_ratio": round(best_sharpe, 2),
            "mdd": best_mdd,
        },
        "assets": assets_summary,
        "frontier_samples": scatter_points,
        "simulations": num_portfolios,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    res = calculate_rebalancing(["000660", "005930", "360750"])
    logger.info("[TEST] 최적 포트폴리오 요약: %s", res["optimal"])
    logger.info("[TEST] 추천 비중: %s", [(a["name"], f"{a['weight']}%") for a in res["assets"]])
