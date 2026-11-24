"""알리고(aligo.in) 문자 발송 API 연동.

키·아이디·발신번호는 코드에 넣지 않고 .env(환경변수)에서 읽는다.
  ALIGO_API_KEY, ALIGO_USER_ID, ALIGO_SENDER

주의: 알리고는 등록된 서버 IP에서만 API 호출을 받는다.
      (알리고 사이트 > 문자 API > 발송 서버 IP 등록)
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

SEND_URL = "https://apis.aligo.in/send/"
SMS_MAX_BYTES = 90  # 이보다 길면 장문(LMS)으로 보낸다
TITLE_MAX_BYTES = 44


@dataclass
class SendResult:
    ok: bool
    code: str = ""
    message: str = ""
    msg_id: str = ""
    msg_type: str = ""


def byte_len(text):
    """문자 길이 계산은 EUC-KR 기준(한글 2바이트)."""
    return len(text.encode("cp949", errors="replace"))


def cut_bytes(text, limit):
    out = ""
    for ch in text:
        if byte_len(out + ch) > limit:
            break
        out += ch
    return out


def is_configured():
    return all([settings.ALIGO_API_KEY, settings.ALIGO_USER_ID, settings.ALIGO_SENDER])


def send(receiver, text, title="", testmode=False, timeout=10):
    """문자 1건 발송. 실패해도 예외를 던지지 않고 SendResult(ok=False)를 돌려준다."""
    if not is_configured():
        return SendResult(False, "CONFIG", ".env에 ALIGO_API_KEY·ALIGO_USER_ID·ALIGO_SENDER를 설정해 주세요.")
    msg_type = "SMS" if byte_len(text) <= SMS_MAX_BYTES else "LMS"
    data = {
        "key": settings.ALIGO_API_KEY,
        "user_id": settings.ALIGO_USER_ID,
        "sender": "".join(c for c in settings.ALIGO_SENDER if c.isdigit()),
        "receiver": receiver,
        "msg": text,
        "msg_type": msg_type,
    }
    if msg_type == "LMS" and title:
        data["title"] = cut_bytes(title, TITLE_MAX_BYTES)
    if testmode:
        data["testmode_yn"] = "Y"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(SEND_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        logger.warning("알리고 발송 요청 실패: %s", e)
        return SendResult(False, "NETWORK", f"알리고 연결 실패: {e}"[:200], msg_type=msg_type)
    code = str(payload.get("result_code", ""))
    ok = code == "1"
    if not ok:
        logger.warning("알리고 발송 실패: %s %s", code, payload.get("message"))
    return SendResult(ok, code, str(payload.get("message", ""))[:200], str(payload.get("msg_id", "") or ""),
                      str(payload.get("msg_type", "") or msg_type))
