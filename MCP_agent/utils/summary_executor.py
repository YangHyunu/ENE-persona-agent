from .clovastudio_executor import CLOVAStudioExecutor
from http import HTTPStatus

class SummarizationExecutor(CLOVAStudioExecutor):
    def __init__(self, host, api_key, request_id):
        # 최신 API에서는 app_id 경로 파라미터가 제거됨
        super().__init__(host, api_key, request_id)

    def execute(self, summary_request):
        # 최신 엔드포인트 경로 반영: /v1/api-tools/summarization/v2
        endpoint = '/v1/api-tools/summarization/v2' # 클로바 용 endpoint 수정 필요
        res, status = super().execute(summary_request, endpoint)
        
        if status == HTTPStatus.OK and "result" in res:
            return res["result"]["text"]
        else:
            error_message = res.get("status", {}).get("message", "Unknown error") if isinstance(res, dict) else "Unknown error"
            raise ValueError(f"오류 발생: HTTP {status}, 메시지: {error_message}")


