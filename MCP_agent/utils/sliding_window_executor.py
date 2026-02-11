from .clovastudio_executor import CLOVAStudioExecutor
import json

class SlidingWindowExecutor(CLOVAStudioExecutor):
    def execute(self, completion_request):
        # 최신 엔드포인트 경로 반영: /v1/api-tools/sliding/chat-messages/{modelName}
        model_name = completion_request.get("modelName", "HCX-003")
        endpoint = f'/v1/api-tools/sliding/chat-messages/{model_name}'
        
        try:
            result, status = super().execute(completion_request, endpoint)
            if status == 200:
                # 슬라이딩 윈도우 적용 후 메시지를 반환
                return result['result']['messages']
            else:
                error_message = result.get('status', {}).get('message', 'Unknown error')
                raise ValueError(f"오류 발생: HTTP {status}, 메시지: {error_message}")
        except Exception:
            return 'Error'
