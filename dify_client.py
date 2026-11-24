import json
import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DIFY_TIMEOUT = 60
DIFY_MAX_ATTEMPTS = 3
DIFY_RETRY_DELAY = 1.5
TRANSIENT_KEYWORDS = (
    "high demand",
    "overloaded",
    "temporarily",
    "rate limit",
    "try again later",
)


def _is_transient_dify_error(status_code: int, detail: str) -> bool:
    """일시적인 모델 과부하/서버 혼잡 오류인지 판별"""
    if status_code in {429, 500, 502, 503, 504}:
        return True
    if status_code == 400:
        lowered = detail.lower()
        return any(kw in lowered for kw in TRANSIENT_KEYWORDS)
    return False


def _get_dify_config(bot_type: str) -> tuple[str, str]:
    """bot_type('analysis' | 'tech')에 따라 Dify Base URL과 API Key를 반환"""
    base_url = os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1").strip().rstrip("/")

    if bot_type == "analysis":
        api_key = os.getenv("DIFY_ANALYSIS_API_KEY", "").strip()
        bot_label = "종목심층분석 챗봇(DIFY_ANALYSIS_API_KEY)"
    elif bot_type == "tech":
        api_key = os.getenv("DIFY_TECH_API_KEY", "").strip()
        bot_label = "지표해석기 챗봇(DIFY_TECH_API_KEY)"
    else:
        raise ValueError(f"지원하지 않는 Dify 챗봇 유형입니다: {bot_type}")

    if not api_key:
        raise RuntimeError(f"{bot_label}가 설정되지 않았습니다. (.env 파일을 확인해 주세요)")

    return base_url, api_key


def _normalize_inputs(inputs: dict[str, Any] | None) -> dict[str, str]:
    """Dify inputs 값은 문자열/숫자 위주이므로 dict/list는 JSON 문자열로 안전 변환"""
    if not inputs:
        return {}

    normalized: dict[str, str] = {}
    for key, val in inputs.items():
        if val is None:
            normalized[key] = ""
        elif isinstance(val, (dict, list)):
            normalized[key] = json.dumps(val, ensure_ascii=False)
        else:
            normalized[key] = str(val)
    return normalized


def ask_dify_chatbot(
    bot_type: str,
    query: str,
    inputs: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    user_id: str = "investment-assistant-user",
) -> dict[str, Any]:
    """Dify 챗봇 API(/chat-messages)를 호출하고 답변과 conversation_id를 반환"""
    query_text = str(query or "").strip()
    if not query_text:
        raise ValueError("질문 내용을 입력해 주세요.")

    base_url, api_key = _get_dify_config(bot_type)
    url = f"{base_url}/chat-messages"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "inputs": _normalize_inputs(inputs),
        "query": query_text,
        "response_mode": "blocking",
        "user": user_id,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id

    # API Key는 로그에 절대 출력하지 않는다
    logger.info("[DIFY] Dify 챗봇 API 호출 시작 (bot=%s)", bot_type)

    resp = None
    for attempt in range(1, DIFY_MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=DIFY_TIMEOUT)
        except requests.Timeout as exc:
            if attempt < DIFY_MAX_ATTEMPTS:
                logger.warning("[DIFY] 응답 시간 초과, 재시도 (%d/%d)", attempt, DIFY_MAX_ATTEMPTS)
                time.sleep(DIFY_RETRY_DELAY)
                continue
            raise RuntimeError("Dify 챗봇 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"Dify 서버 네트워크 연결에 실패했습니다: {exc}") from exc

        if resp.status_code in {401, 403}:
            raise RuntimeError("Dify API Key가 유효하지 않거나 권한이 없습니다.")
        if resp.status_code == 200:
            break

        detail = ""
        try:
            err_json = resp.json()
            detail = err_json.get("message") or str(err_json)
        except Exception:
            detail = resp.text[:200]

        if attempt < DIFY_MAX_ATTEMPTS and _is_transient_dify_error(resp.status_code, detail):
            logger.warning(
                "[DIFY] 일시적 모델 혼잡 오류(HTTP %s), 재시도 (%d/%d)",
                resp.status_code,
                attempt,
                DIFY_MAX_ATTEMPTS,
            )
            time.sleep(DIFY_RETRY_DELAY)
            continue

        raise RuntimeError(f"Dify 챗봇 호출 실패 (HTTP {resp.status_code}): {detail}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise RuntimeError("Dify 챗봇 응답을 JSON으로 변환하는 데 실패했습니다.") from exc

    answer = data.get("answer", "")
    new_conversation_id = data.get("conversation_id", "")

    logger.info("[DIFY] Dify 챗봇 응답 수신 완료 (bot=%s, len=%d)", bot_type, len(answer))

    return {
        "answer": answer,
        "conversation_id": new_conversation_id,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # 단위 테스트: 설정 로드 및 inputs 문자열 정규화 확인 (실제 유료/토큰 소모 호출 전 기본 검증)
    base, _ = _get_dify_config("analysis")
    base_tech, _ = _get_dify_config("tech")
    sample_inputs = _normalize_inputs({"stock_data": {"name": "SK하이닉스", "per": 4.94}})
    logger.info("[TEST] Dify 설정 확인 완료 (base=%s, normalized_keys=%s)", base, list(sample_inputs.keys()))
