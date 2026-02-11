"""
nodes/analyzer.py - 감정/호감도 분석 노드

역할:
- 사용자 메시지 분석 (LLM 호출)
- 감정 상태 파악
- 호감도 변화 계산
- 닉네임/관계 변경 감지

v2의 context_builder와 함께 사용 가능
"""

import json
from typing import Dict, Any, Optional, Type
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


@dataclass
class AnalyzerConfig:
    """분석기 설정"""
    max_intimacy_change: int = 5  # 한 번에 최대 변화량
    temperature: float = 0.1
    max_tokens: int = 512


class AnalyzerNode:
    """
    감정/호감도 분석 노드

    mcp_new의 analyze_interaction_node를 클래스로 분리
    LLM을 사용해 사용자 메시지를 분석
    """

    def __init__(
        self,
        llm,
        config: Optional[AnalyzerConfig] = None
    ):
        """
        Args:
            llm: 분석용 LLM (도구 바인딩 없음)
            config: 분석기 설정
        """
        self.llm = llm
        self.config = config or AnalyzerConfig()

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        분석 노드 실행

        Args:
            state: 그래프 상태

        Returns:
            {
                "intimacy_level": int,
                "current_emotion": str,
                "user_profile": Dict (닉네임/관계 변경 시)
            }
        """
        messages = state.get("messages", [])

        if not messages:
            return {}

        # 마지막 사용자 메시지 찾기
        last_user_message = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_message = msg.content
                break

        if not last_user_message:
            return {}

        # 분석 프롬프트
        analysis_prompt = self._build_analysis_prompt()

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=analysis_prompt),
                HumanMessage(content=f"분석할 메시지: {last_user_message}")
            ])

            # JSON 파싱
            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()
            analysis = json.loads(content)

            # 결과 처리
            return self._process_analysis(state, analysis)

        except Exception:
            # 분석 실패 시 기본값
            return {"current_emotion": "basic"}

    def _build_analysis_prompt(self) -> str:
        """분석 프롬프트 생성"""
        return f"""당신은 감정을 가진 AI입니다. 사용자의 대화 태도를 분석하여 당신이 느끼는 감정과 친밀감 변화를 파악하세요.

[분석 기준]
- 사용자가 예의 바르고 다정한가? (+점수)
- 사용자가 무례하거나 도구로만 취급하는가? (-점수)
- 대화가 깊어지고 서로를 알아가는가? (+점수)
- 한 번의 분석에서 변화 폭은 -{self.config.max_intimacy_change} ~ +{self.config.max_intimacy_change} 이내

[결과 항목]
1. mood: 현재 당신(AI)이 느끼는 상태. 다음 7가지 중 하나로만 답변 (basic, angry, busy, happy, love, pouting, sad)
2. intimacy_change: 호감도 변화량 (-{self.config.max_intimacy_change} ~ +{self.config.max_intimacy_change})
3. reason: 그 감정을 느끼게 된 이유 (간단히)
4. new_nickname: 사용자가 제안한 호칭 (없으면 null)
5. new_relation: 관계 변경 요청 (없으면 null)

출력 형식 (JSON만, 다른 텍스트 없이):
{{"mood": "...", "intimacy_change": 0, "reason": "...", "new_nickname": null, "new_relation": null}}"""

    def _process_analysis(
        self,
        state: Dict[str, Any],
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """분석 결과 처리"""
        updates = {}

        # 1. 감정 상태
        mood = analysis.get("mood", "basic")
        updates["current_emotion"] = mood

        # 2. 호감도 변화
        current_level = state.get("intimacy_level", 50)
        change = int(analysis.get("intimacy_change", 0))

        # 범위 제한
        change = max(-self.config.max_intimacy_change,
                    min(self.config.max_intimacy_change, change))
        new_level = max(0, min(100, current_level + change))
        updates["intimacy_level"] = new_level

        # 3. 닉네임/관계 변경
        user_profile = state.get("user_profile", {}).copy()
        profile_changed = False

        if analysis.get("new_nickname"):
            user_profile["nickname"] = analysis["new_nickname"]
            profile_changed = True

        if analysis.get("new_relation"):
            user_profile["relation_type"] = analysis["new_relation"]
            profile_changed = True

        if profile_changed:
            updates["user_profile"] = user_profile

        return updates


# ============================================================
# 팩토리 함수
# ============================================================

def create_analyzer_node(
    llm_cls: Type,
    model: str = "HCX-005",
    config: Optional[AnalyzerConfig] = None
) -> AnalyzerNode:
    """
    분석 노드 생성 편의 함수

    Args:
        llm_cls: LLM 클래스 (ChatClovaX 등)
        model: 모델 이름
        config: 분석기 설정

    Returns:
        AnalyzerNode 인스턴스
    """
    cfg = config or AnalyzerConfig()

    llm = llm_cls(
        model=model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens
    )

    return AnalyzerNode(llm=llm, config=cfg)
