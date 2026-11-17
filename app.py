import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from collector import collect_stock_data

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


@app.get("/health")
def health_check():
    """서버 상태 및 API Key 설정 여부를 반환 (키 값 자체는 절대 노출 금지)"""
    serper_configured = bool(os.getenv("SERPER_API_KEY", "").strip())
    gemini_configured = bool(os.getenv("GEMINI_API_KEY", "").strip())

    logger.info("[HEALTH] 상태 확인 요청 (serper=%s, gemini=%s)", serper_configured, gemini_configured)

    return jsonify(
        {
            "status": "ok",
            "serper_api_key_configured": serper_configured,
            "gemini_api_key_configured": gemini_configured,
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


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("[SERVER] Flask 서버 시작 (debug=%s)", debug_mode)
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
