import json
import http.client
from http import HTTPStatus

class CLOVAStudioExecutor:
    def __init__(self, host, api_key, request_id):
        self._host = host
        # 사용자가 'Bearer '를 포함하거나 생략해도 작동하도록 처리
        if not api_key.startswith('Bearer '):
            self._api_key = f'Bearer {api_key}'
        else:
            self._api_key = api_key
        self._request_id = request_id

    def _send_request(self, completion_request, endpoint):
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Authorization': self._api_key,
            'X-NCP-CLOVASTUDIO-REQUEST-ID': self._request_id
        }

        conn = http.client.HTTPSConnection(self._host)
        conn.request('POST', endpoint, json.dumps(completion_request), headers)
        response = conn.getresponse()
        status = response.status
        result = json.loads(response.read().decode(encoding='utf-8'))
        conn.close()
        return result, status

    def execute(self, completion_request, endpoint):
        res, status = self._send_request(completion_request, endpoint)
        
        # 최신 API 성공 코드('20000') 확인
        if isinstance(res, dict) and res.get('status', {}).get('code') == '20000':
            return res, status
        elif status == HTTPStatus.OK:
            # 일부 API가 구버전 형식을 반환할 수도 있으므로 fallback
            return res, status
        else:
            code = res.get("status", {}).get("code", "Unknown")
            error_message = res.get("status", {}).get("message", "Unknown error") if isinstance(res, dict) else "Unknown error"
            raise ValueError(f"오류 발생: HTTP {status}, 결과코드 {code}, 메시지: {error_message}")
