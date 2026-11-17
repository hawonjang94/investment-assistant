import json
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from collector import collect_stock_data, resolve_stock_code
from dify_client import ask_dify_chatbot
from portfolio import calculate_rebalancing
from technical import calculate_technical_indicators

# .env 파일에서 환경변수 불러오기
load_dotenv()

# Backend 로깅 설정 (print() 대신 logging 사용)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.get("/")
def index():
    """메인 웹 화면 반환"""
    return render_template("index.html")


@app.get("/test")
def test_collector_page():
    """기존 1차 종목 데이터 수집기 테스트 화면 반환"""
    return render_template("test.html")


@app.get("/health")
def health_check():
    """서버 상태 및 API Key 설정 여부를 반환 (키 값 자체는 절대 노출 금지)"""
    serper_configured = bool(os.getenv("SERPER_API_KEY", "").strip())
    gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
    dify_analysis_configured = bool(os.getenv("DIFY_ANALYSIS_API_KEY", "").strip())
    dify_tech_configured = bool(os.getenv("DIFY_TECH_API_KEY", "").strip())

    logger.info(
        "[HEALTH] 상태 확인 요청 (serper=%s, gemini=%s, dify_analysis=%s, dify_tech=%s)",
        serper_configured,
        gemini_configured,
        dify_analysis_configured,
        dify_tech_configured,
    )

    return jsonify(
        {
            "status": "ok",
            "serper_api_key_configured": serper_configured,
            "gemini_api_key_configured": gemini_configured,
            "dify_analysis_api_key_configured": dify_analysis_configured,
            "dify_tech_api_key_configured": dify_tech_configured,
        }
    )


@app.post("/fetch")
def fetch_stock():
    """종목코드를 받아 네이버 금융 수집 + Serper 뉴스 검색을 통합 실행하고 JSON 반환"""
    payload = request.get_json(silent=True) or {}
    code = payload.get("code", "")
    logger.info("[REQUEST] POST /fetch code=%s", str(code).strip())

    try:
        result = collect_stock_data(code)
        return jsonify(result), 200
    except ValueError as exc:
        logger.warning("[ERROR] 잘못된 요청 (code=%s): %s", code, exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("[ERROR] 수집 실패 및 Stack Trace")
        return jsonify({"error": f"데이터 수집 중 오류가 발생했습니다: {exc}"}), 500


@app.post("/api/chat/analysis")
def chat_analysis():
    """[탭1] 종목코드/종목명 + 질문을 받아 collector 수집 JSON을 Dify 챗봇① inputs에 주입해 답변 반환"""
    payload = request.get_json(silent=True) or {}
    raw_code = payload.get("code", "")
    question = str(payload.get("question", "")).strip() or "이 종목의 현재 투자 지표, 실적 추이, 최신 뉴스를 근거로 분석해 주세요."
    conversation_id = payload.get("conversation_id") or None

    logger.info("[REQUEST] POST /api/chat/analysis code=%s", str(raw_code).strip())

    try:
        resolved_code = resolve_stock_code(raw_code)
        stock_data = collect_stock_data(resolved_code)

        dify_inputs = {
            "stock_code": stock_data["code"],
            "stock_name": stock_data["name"],
            "stock_data": json.dumps(stock_data, ensure_ascii=False),
        }

        # Dify 오케스트레이드 변수 유무와 무관하게 챗봇이 데이터를 확실히 읽을 수 있도록 질문에 근거 JSON 함께 주입
        dify_query = (
            f"[종목 분석 요청: {stock_data['name']}({stock_data['code']})]\n"
            f"아래는 방금 수집한 최신 JSON 데이터입니다. 반드시 이 데이터만을 근거로 답변하세요.\n"
            f"```json\n{json.dumps(stock_data, ensure_ascii=False)}\n```\n\n"
            f"사용자 질문: {question}"
        )

        dify_res = ask_dify_chatbot(
            bot_type="analysis",
            query=dify_query,
            inputs=dify_inputs,
            conversation_id=conversation_id,
        )

        logger.info("[RESPONSE] 탭1 심층분석 채팅 응답 완료 (name=%s)", stock_data["name"])
        return jsonify(
            {
                "answer": dify_res["answer"],
                "conversation_id": dify_res["conversation_id"],
                "stock": stock_data,
            }
        ), 200
    except ValueError as exc:
        logger.warning("[ERROR] 탭1 잘못된 요청: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("[ERROR] 탭1 심층분석 채팅 실패")
        return jsonify({"error": f"종목 분석 채팅 중 오류가 발생했습니다: {exc}"}), 500


@app.post("/api/rebalance")
def rebalance_portfolio():
    """[탭2] 보유 종목/ETF 목록을 받아 FDR 최근 1년 기반 몬테카를로·효율적 프론티어 계산 반환 (Dify 없음)"""
    payload = request.get_json(silent=True) or {}
    codes = payload.get("codes", [])
    logger.info("[REQUEST] POST /api/rebalance codes=%s", codes)

    try:
        result = calculate_rebalancing(codes)
        logger.info("[RESPONSE] 탭2 리밸런싱 계산 완료 (assets=%d)", len(result["assets"]))
        return jsonify(result), 200
    except ValueError as exc:
        logger.warning("[ERROR] 탭2 잘못된 요청: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("[ERROR] 탭2 리밸런싱 계산 실패")
        return jsonify({"error": f"리밸런싱 계산 중 오류가 발생했습니다: {exc}"}), 500


@app.post("/api/technical")
def technical_indicators():
    """[탭3] 종목코드/명을 받아 FDR 기반 MA/RSI/MACD/볼린저밴드 계산 결과 반환"""
    payload = request.get_json(silent=True) or {}
    raw_code = payload.get("code", "")
    logger.info("[REQUEST] POST /api/technical code=%s", str(raw_code).strip())

    try:
        result = calculate_technical_indicators(raw_code)
        logger.info("[RESPONSE] 탭3 기술지표 계산 완료 (name=%s)", result["name"])
        return jsonify(result), 200
    except ValueError as exc:
        logger.warning("[ERROR] 탭3 잘못된 요청: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("[ERROR] 탭3 기술지표 계산 실패")
        return jsonify({"error": f"기술지표 계산 중 오류가 발생했습니다: {exc}"}), 500


@app.post("/api/chat/technical")
def chat_technical():
    """[탭3] 계산된 기술지표 숫자를 Dify 챗봇③(지표해석기)에 보이지 않게 주입해 설명 답변 반환"""
    payload = request.get_json(silent=True) or {}
    raw_code = payload.get("code", "")
    indicators = payload.get("indicators")
    question = str(payload.get("question", "")).strip() or "현재 계산된 기술지표 숫자들을 초보자도 이해하기 쉽게 설명해 주세요."
    conversation_id = payload.get("conversation_id") or None

    logger.info("[REQUEST] POST /api/chat/technical code=%s", str(raw_code).strip())

    try:
        # 프론트에서 전달받은 indicators가 없으면 서버에서 직접 최신 계산
        if not isinstance(indicators, dict) or not indicators:
            calc_res = calculate_technical_indicators(raw_code)
            stock_code = calc_res["code"]
            stock_name = calc_res["name"]
            indicators = calc_res["latest"]
        else:
            stock_code = resolve_stock_code(raw_code) if raw_code else str(indicators.get("code", ""))
            stock_name = str(payload.get("name") or stock_code)

        dify_inputs = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "indicators": json.dumps(indicators, ensure_ascii=False),
        }

        # 오케스트레이드 변수 유무와 무관하게 챗봇이 계산된 숫자만 근거로 설명하도록 컨텍스트 주입
        dify_query = (
            f"[기술지표 해석 요청: {stock_name}({stock_code})]\n"
            f"아래는 Python(FinanceDataReader)으로 방금 계산한 최신 기술지표 숫자입니다. 반드시 이 숫자만을 근거로 쉽게 설명하세요.\n"
            f"```json\n{json.dumps(indicators, ensure_ascii=False)}\n```\n\n"
            f"사용자 질문: {question}"
        )

        dify_res = ask_dify_chatbot(
            bot_type="tech",
            query=dify_query,
            inputs=dify_inputs,
            conversation_id=conversation_id,
        )

        logger.info("[RESPONSE] 탭3 지표해석기 응답 완료 (name=%s)", stock_name)
        return jsonify(
            {
                "answer": dify_res["answer"],
                "conversation_id": dify_res["conversation_id"],
            }
        ), 200
    except ValueError as exc:
        logger.warning("[ERROR] 탭3 채팅 잘못된 요청: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("[ERROR] 탭3 지표해석기 채팅 실패")
        return jsonify({"error": f"기술지표 설명 채팅 중 오류가 발생했습니다: {exc}"}), 500


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("[SERVER] Flask 서버 시작 (debug=%s)", debug_mode)
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
