import os
import asyncio
import uuid
from dotenv import load_dotenv
import re
from bs4 import BeautifulSoup

from langchain.tools import tool
from langchain_naver import ChatClovaX
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
load_dotenv()


async def main(clova_api_key: str, server_config: dict, checkpoint_path: str = "/data/ephemeral/pro-nlp-finalproject-nlp-05/Fast-MCP/scripts/checkpoint.db"):

    model = ChatClovaX(model="HCX-005", api_key=clova_api_key)
    client = MultiServerMCPClient(server_config)
    tools = await client.get_tools()
    tool_map = {t.name: t for t in tools}
    web_search = tool_map.get("web_search")
    browser_navigate = tool_map.get("browser_navigate")
    discord_send_message = tool_map.get("send_message")
    discord_tools = [
        tool for tool in tools 
        if tool.name in ["send_message", "read_messages", "add_reaction"]
    ]
    slack_tools = [
        tool for tool in tools 
        if tool.name in ["conversations_history","conversations_replies","conversations_add_message", "conversations_search_messages","channels_list"]
    ]
    @tool
    async def scrape_and_clean(url: str) -> str:
        """주어진 URL로 이동하여 페이지의 HTML을 스크래핑한 뒤 본문 텍스트를 정제합니다."""

        # browser_navigate 도구를 사용하여 페이지 HTML을 가져옵니다.
        html_content = await browser_navigate.ainvoke({"url": url})
        soup = BeautifulSoup(html_content, 'html.parser')
        text = soup.get_text()
        
        # 불필요한 태그, 특수문자, 과도한 공백 등을 제거합니다.
        text = re.sub(
            r'(?:\b[a-z]+(?:\s+\[[^\]]*\])?:\s*|\[[^\]]*\]|[.,\-\|/]{3,}|\s+)',
            ' ',
            text,
            flags=re.I
        ).strip()
 
        return text
    
    # tools_list = [web_search, discord_send_message, scrape_and_clean]
    tools_list = [web_search] + discord_tools + slack_tools
    async with AsyncSqliteSaver.from_conn_string(checkpoint_path) as checkpointer:
        agent = create_agent(model, tools_list, checkpointer=checkpointer)

        thread_id = input("세션 ID를 입력하세요(새 세션 시작은 Enter): ").strip()
        if not thread_id:
            thread_id = str(uuid.uuid4())
            print(f"새 세션이 생성되었습니다. 세션 ID: {thread_id}")
        config = {"configurable": {"thread_id": thread_id}}
        print(f"현재 세션 ID: {thread_id}\n")
        print("안녕하세요. 저는 AI 어시스턴트입니다. (종료: '종료')\n")

        system_message = SystemMessage(content=(
            "당신은 친절한 AI 어시스턴트입니다.\\n"
            "사용자의 질문에 대해 신뢰할 수 있는 정보만 근거로 삼아 답변하세요.\\n"
            "만약 정보를 찾기 위해 도구를 사용해야 한다면, 다음 작업 순서에 따라 진행하세요:\\n"
            "먼저 web_search 도구를 사용하여 관련 정보를 검색합니다.\\n"
            "수집한 정보를 바탕으로 종합적인 답변을 제공합니다.\\n"
            "디스코드 도구 사용이 필요한 경우 채널id를 요구하세요.\\n"
            "슬랙 도구 사용이 필요한 경우 채널이름을 요구하세요.\\n"
            "도구에 접근할때 어떤 도구를 사용해야하는지 스스로 한번 더 생각하세요.\\n"
        ))

        while True:
            user_input = input("사용자: ").strip()

            if not user_input:
                print("입력이 비어 있습니다. 다시 시도해 주세요.")
                continue
            if user_input.lower() in {"종료", "exit", "quit"}:
                print("대화를 종료합니다.")
                break

            try:
                existing_checkpoint = await checkpointer.aget_tuple(config)

                if existing_checkpoint is not None:
                    existing_messages = existing_checkpoint.checkpoint["channel_values"]["messages"]
                    # 이전 메시지가 있다면 system 메시지를 제외한 기존 메시지에 새 사용자 메시지를 추가
                    state = {
                        "messages": existing_messages + [HumanMessage(content=user_input)]
                    }
                else:

                    state = {
                        "messages": [system_message, HumanMessage(content=user_input)]
                    }
                
                print("\nAI 어시스턴트: ", end="", flush=True)

                async for event in agent.astream_events(state, config=config, version="v1"):
                    kind = event["event"]
                    
                    if kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            print(chunk.content, end="", flush=True)
                    
                    elif kind == "on_tool_start":
                        tool_name = event["name"]
                        tool_input = event["data"].get("input", {})
                        print(f"\n\n[도구]: {tool_name}")
                        print(f"[입력]: {tool_input}")
                    
                    elif kind == "on_tool_end":
                        tool_name = event.get("name", "")
                        tool_output = event["data"].get("output", "")
                        
                        if tool_name != "browser_navigate":
                            output_preview = str(tool_output)[:150]
                            print(f"[응답]: {output_preview}...")
                
                print("\\n")
                
            except Exception as e:
                print(f"\\n❌ 오류: {e}\\n")
if __name__ == "__main__":
    load_dotenv()

    CLOVA_STUDIO_API_KEY = os.getenv("CLOVA_STUDIO_API_KEY")
    SLACK_MCP_URL = os.getenv("SLACK_MCP_URL")

    if not SLACK_MCP_URL:
        print("❌ SLACK_MCP_URL이 .env 파일에 설정되어 있지 않습니다.")
        print("📋 start-slack-mcp.sh를 먼저 실행하여 ngrok URL을 생성하세요.")
        exit(1)

    SERVER_CONFIG = {
    "search-mcp": {
        "url": "http://127.0.0.1:8000/mcp/",
        "transport": "streamable_http",
    },
    "playwright-mcp": {
        "url": "http://localhost:8931/mcp",
        "transport": "streamable_http",
    },
    "discord-mcp": {
        "url": "http://localhost:8001/mcp/",
        "transport": "streamable_http",
    },
    "slack-mcp": {
        "url": SLACK_MCP_URL,
        "transport": "sse",
    }
}

    asyncio.run(main(CLOVA_STUDIO_API_KEY, SERVER_CONFIG))