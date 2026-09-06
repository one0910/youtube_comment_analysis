from .ai_analysis_provider import (
    AIAnalysisProvider,
    AIAnalysisRequest,
    AIProviderResponse,
)


"""使用固定資料模擬 AI Provider，不呼叫外部 API。"""
class FakeAIAnalysisProvider(AIAnalysisProvider):

    def __init__(self, response: AIProviderResponse,analysis_error: Exception | None = None  ):
        self._response = response
        self._analysis_error = analysis_error
        self.received_analysis_requests: list[AIAnalysisRequest] = []

    def analyze_comments(self,analysis_request: AIAnalysisRequest) -> AIProviderResponse:
        self.received_analysis_requests.append(analysis_request)

        if self._analysis_error is not None:
            raise self._analysis_error

        return self._response