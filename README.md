# Fast-MCP Project

Multi-server MCP (Model Context Protocol) 기반 AI 어시스턴트 시스템

## 프로젝트 개요

Fast-MCP는 여러 MCP 서버를 통합하여 네이버 검색, Discord, Slack, Google Calendar 기능을 제공하는 LangGraph 기반 대화형 AI 어시스턴트입니다.

### 주요 기능

- **Naver Search MCP**: 네이버 검색 API를 통한 웹 검색
- **Discord MCP**: Discord 채널에 메시지 전송, 읽기, 리액션 추가
- **Slack MCP**: Slack 채널 메시지 관리
- **Google Calendar MCP**: Google Calendar 일정 조회 및 관리
- **대화 기록 관리**: 세션 기반 대화 히스토리 저장

## 시스템 요구사항

- **Python**: 3.12 이상
- **Node.js**: 20.x LTS 이상
- **ngrok**: 외부 접근용 터널링 (Slack MCP SSE 전송)
- **OS**: macOS / Linux

## 초기 설정

### 1. Node.js 설치

#### 방법 1: 자동 설치 스크립트 (Ubuntu 전용)
```bash
# Ubuntu/Linux 환경에서만 사용 가능
sudo bash MCP_agent/Fast-MCP/scripts/setup-nodejs.sh
```
**주의**: 이 스크립트는 `apt-get`을 사용하므로 Ubuntu/Debian 계열에서만 작동합니다.

#### 방법 2: 수동 설치

**macOS (Homebrew 사용)**:
```bash
# Homebrew로 Node.js 설치
brew install node

# 설치 확인
node --version
npm --version
npx --version
```

**Ubuntu/Linux**:
```bash
# NodeSource repository 추가 (Node.js 20.x LTS)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -

# Node.js 설치
sudo apt-get install -y nodejs

# 설치 확인
node --version
npm --version
npx --version
```

### 2. ngrok 설치 및 인증

#### ngrok 계정 생성 및 authtoken 받기
1. https://dashboard.ngrok.com/signup 에서 무료 계정 생성
2. https://dashboard.ngrok.com/get-started/your-authtoken 에서 authtoken 복사

#### 방법 1: 자동 설치 (Ubuntu 전용)
```bash
# Ubuntu/Linux 환경에서만 사용 가능
# 먼저 setup-ngrok.sh 파일에서 authtoken을 본인의 토큰으로 변경
# Line 29: ngrok config add-authtoken YOUR_TOKEN_HERE

sudo bash MCP_agent/Fast-MCP/scripts/setup-ngrok.sh
```
**주의**: 이 스크립트는 `apt`를 사용하므로 Ubuntu/Debian 계열에서만 작동합니다.

#### 방법 2: 수동 설치

**macOS (Homebrew 사용)**:
```bash
# Homebrew로 ngrok 설치
brew install ngrok

# authtoken 설정 (YOUR_TOKEN_HERE를 실제 토큰으로 변경)
ngrok config add-authtoken YOUR_TOKEN_HERE

# 설치 확인
ngrok version
```

**Ubuntu/Linux**:
```bash
# ngrok 설치
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
  | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
  | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

# authtoken 설정 (YOUR_TOKEN_HERE를 실제 토큰으로 변경)
ngrok config add-authtoken YOUR_TOKEN_HERE

# 설치 확인
ngrok version
```

### 3. Python 환경 설정

```bash
# 저장소 클론 및 이동
git clone https://github.com/<your-org>/pro-nlp-finalproject-nlp-05.git
cd pro-nlp-finalproject-nlp-05

# uv를 사용한 가상환경 설정 및 의존성 설치
uv venv
source .venv/bin/activate

# 의존성 설치 (pyproject.toml + uv.lock 기반, 권장)
uv sync

# 또는 requirements.txt 사용
uv pip install -r requirements.txt
```

### 4. 환경변수 설정

프로젝트 루트에 `.env` 파일 생성:

```bash
# Clova Studio API (HCX-005 모델용)
CLOVA_STUDIO_API_KEY=your_clova_api_key_here
CLOVASTUDIO_API_KEY=your_clova_api_key_here
NCP_CLOVASTUDIO_API_KEY=your_clova_api_key_here
NCP_CLOVASTUDIO_REQUEST_ID=your_request_id_here

# OpenAI API (선택 사항)
OPENAI_API_KEY=your_openai_api_key_here

# Naver Search API
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret

# Discord Bot Token
DISCORD_TOKEN=your_discord_bot_token

# Slack Bot Token
SLACK_MCP_PORT=3001
SLACK_MCP_ADD_MESSAGE_TOOL=true
SLACK_MCP_XOXB_TOKEN=xoxb-your-slack-bot-token

# ngrok URL (start-slack-mcp.sh 실행 시 자동 설정됨)
SLACK_MCP_URL=https://xxx.ngrok-free.app/sse

# Google Calendar API (OAuth 자격증명 JSON)
GOOGLE_CREDENTIALS_JSON='{"installed":{"client_id":"...","project_id":"...","auth_uri":"...","token_uri":"...","auth_provider_x509_cert_url":"...","client_secret":"...","redirect_uris":["..."]}}'
```

`.env.example` 파일을 참고하여 작성할 수 있습니다.

#### API 키 발급 방법

- **Clova Studio**: https://www.ncloud.com/product/aiService/clovaStudio
  - 네이버 클라우드 플랫폼 가입 후 HCX-005 API 키 발급

- **Naver Search API**: https://developers.naver.com/products/search/
  - 네이버 개발자 센터에서 애플리케이션 등록 후 Client ID/Secret 발급

- **Discord Bot**: https://discord.com/developers/applications
  1. New Application 생성
  2. Bot 탭에서 Bot 추가
  3. Token 복사 (한 번만 표시됨)
  4. Privileged Gateway Intents에서 MESSAGE CONTENT INTENT 활성화

- **Slack Bot**: https://api.slack.com/apps
  1. Create New App → From scratch
  2. OAuth & Permissions에서 Bot Token Scopes 추가:
     - `channels:history`
     - `channels:read`
     - `chat:write`
     - `groups:history`
     - `groups:read`
  3. Install to Workspace
  4. Bot User OAuth Token (xoxb-로 시작) 복사

- **Google Cloud Console**:                      
  - 1단계: Google Cloud Console에서 프로젝트 생성                                                                       
    1. https://console.cloud.google.com 접속                                                            
    2. 상단의 프로젝트 선택 → 새 프로젝트 클릭                                                          
    3. 프로젝트 이름 입력 (예: calendar-mcp) → 만들기                     
  - 2단계: Google Calendar API 활성화                          
    1. 좌측 메뉴 → API 및 서비스 → 라이브러리                                                           
    2. "Google Calendar API" 검색                                                                       
    3. 사용 설정 클릭                         
  - 3단계: OAuth 동의 화면 설정                          
    1. API 및 서비스 → OAuth 동의 화면                                                                  
    2. User Type: 외부 선택 → 만들기                                                                    
    3. 앱 이름, 사용자 지원 이메일 입력                                                                 
    4. 범위 추가: https://www.googleapis.com/auth/calendar.events                                       
    5. 테스트 사용자에 본인 Gmail 추가                            
  - 4단계: OAuth 자격증명 생성                            
    1. API 및 서비스 → 사용자 인증 정보                                                                 
    2. + 사용자 인증 정보 만들기 → OAuth 클라이언트 ID                                                  
    3. 애플리케이션 유형: 데스크톱 앱 ⚠️ (중요!)                                                        
    4. 이름 입력 → 만들기        
    5. JSON 다운로드 클릭  
    .env에 GOOGLE_CREDENTIALS_JSON='your_json_here'({"web":...})      
  

## 실행 방법

### 1. MCP 서버 시작

```bash
# 프로젝트 루트에서 실행
bash MCP_agent/Fast-MCP/scripts/start-slack-mcp.sh
```

**실행되는 서버:**
- **Naver Search MCP**: http://localhost:8000/mcp/
- **Discord MCP**: http://localhost:8001/mcp/
- **Google Calendar MCP**: http://localhost:8002/mcp/
- **Slack MCP Server**: http://localhost:3001 (ngrok 필요)

### 2. CLOVA MCP 에이전트 실행

**새 터미널**을 열고:

```bash
source .venv/bin/activate

python MCP_agent/agent/clova_mcp_gui.py
```

이 에이전트는:
- CLOVA X (HyperCLOVA) 기반 대화
- MCP 서버 도구 통합 (Naver Search, Discord, Slack, Google Calendar)
- 페르소나/메모리 기능 지원
- 감정 분석 및 호감도 관리

## 사용 예시

### 대화형 AI 어시스턴트

```
🔗 Slack MCP URL: https://abc123.ngrok-free.app/sse
세션 ID를 입력하세요(새 세션 시작은 Enter): [Enter 입력]
새 세션이 생성되었습니다. 세션 ID: 550e8400-e29b-41d4-a716-446655440000
현재 세션 ID: 550e8400-e29b-41d4-a716-446655440000

안녕하세요. 저는 AI 어시스턴트입니다. (종료: '종료')

사용자: 안녕하세요
AI 어시스턴트: 안녕하세요! 무엇을 도와드릴까요?

사용자: 2024년 AI 트렌드를 검색해줘

[도구]: web_search
[입력]: {'query': '2024년 AI 트렌드', 'display': 20, 'start': 1, 'sort': 'sim'}
[응답]: {'query': '2024년 AI 트렌드', 'total': 15234, 'items': [{'title': '2024년 AI 트렌드 전망', ...}]}...

AI 어시스턴트: 2024년 AI 트렌드를 검색한 결과, 주요 트렌드는...
```

### Discord 메시지 전송

```
사용자: 디스코드 채널 1234567890에 "프로젝트 완료!" 메시지 보내줘

[도구]: send_message
[입력]: {'channel_id': '1234567890', 'content': '프로젝트 완료!'}
[응답]: Message sent successfully. Message ID: 9876543210

AI 어시스턴트: Discord 채널에 메시지를 성공적으로 전송했습니다.
```

### Slack 채널 목록 조회

```
사용자: 슬랙 채널 목록 보여줘

[도구]: channels_list
[입력]: {'channel_types': 'public_channel,private_channel'}
[응답]: [{'id': 'C123456', 'name': 'general'}, ...]

AI 어시스턴트: 사용 가능한 Slack 채널은 다음과 같습니다: general, random, dev...
```

## 프로젝트 구조

```
.
├── MCP_agent/                          # 메인 에이전트 모듈
│   ├── graph.py                        # 표준 ReAct 패턴 LangGraph
│   ├── agent/                          # 에이전트 구현
│   │   ├── clova_mcp_gui.py            # PySide6 GUI 버전 (메인)
│   │   ├── persona_logic.py            # 페르소나 로직
│   │   └── assets/                     # 캐릭터 이미지
│   ├── memory/                         # 메모리 모듈
│   │   ├── chroma_adapters.py          # ChromaDB 어댑터
│   │   ├── clova_adapters.py           # Clova 어댑터
│   │   └── interfaces.py              # 메모리 인터페이스
│   ├── nodes/                          # LangGraph 노드
│   │   ├── analyzer.py                 # 감정/호감도 분석
│   │   ├── context_builder.py          # 컨텍스트 빌더
│   │   └── memory_manager.py           # 메모리 매니저
│   └── Fast-MCP/                       # MCP 서버 모듈
│       ├── mcp_servers/
│       │   ├── naver_mcp.py            # 네이버 검색 MCP
│       │   ├── discord-mcp.py          # Discord MCP
│       │   └── google_calendar_mcp.py  # Google Calendar MCP
│       ├── scripts/
│       │   ├── start-slack-mcp.sh      # MCP 서버 통합 실행
│       │   ├── setup-nodejs.sh         # Node.js 설치 (Ubuntu)
│       │   └── setup-ngrok.sh          # ngrok 설치 (Ubuntu)
│       └── src/
│           └── client.py               # MCP 클라이언트
├── .env.example                        # 환경변수 템플릿
├── pyproject.toml                      # Python 프로젝트 설정 (uv)
├── requirements.txt                    # pip 의존성
└── uv.lock                             # uv 락 파일
```

## 트러블슈팅

### ngrok 연결 실패

**증상**: `httpx.ConnectTimeout` 또는 `404 Not Found` 에러

**해결 방법**:
```bash
# ngrok 설정 확인
ngrok config check

# ngrok 프로세스 확인
ps aux | grep ngrok

# ngrok 대시보드 접근 (터널 상태 확인)
curl http://localhost:4040/api/tunnels
# 또는 브라우저에서: http://localhost:4040
```

**ngrok 무료 플랜 제약**:
- 무료 플랜은 브라우저 경고 페이지가 먼저 표시됨
- API 클라이언트는 이 경고를 건너뛸 수 없어 타임아웃 발생 가능
- 해결: 브라우저에서 한 번 `ngrok URL`을 열고 "Visit Site" 클릭

### MCP 서버 연결 실패

**증상**: `ConnectionRefusedError` 또는 서버 응답 없음

**확인 방법**:
```bash
# 서버 프로세스 확인
ps aux | grep python | grep mcp
ps aux | grep npx

# 포트별 연결 테스트
curl http://localhost:8000/mcp/  # Naver Search MCP
curl http://localhost:8001/mcp/  # Discord MCP
curl http://localhost:8002/mcp/  # Google Calendar MCP
curl http://localhost:3001       # Slack MCP

# 포트 사용 확인
# macOS:
lsof -i -P | grep -E '8000|8001|8002|3001'
# Linux:
netstat -tulpn | grep -E '8000|8001|8002|3001'
```

**서버 재시작**:
```bash
# 기존 프로세스 종료
pkill -f "python.*mcp"
pkill -f "npx.*slack-mcp"
pkill ngrok

# 서버 재시작
bash MCP_agent/Fast-MCP/scripts/start-slack-mcp.sh
```

### SQLite Pickle 에러

**증상**: `cannot pickle 'sqlite3.Connection' object`

**임시 해결**:
```bash
# checkpoint.db 파일 삭제 및 재생성
rm MCP_agent/Fast-MCP/scripts/checkpoint.db
touch MCP_agent/Fast-MCP/scripts/checkpoint.db

# 클라이언트 재실행
python MCP_agent/Fast-MCP/src/client.py
```

**근본 해결**:
- `AsyncSqliteSaver` 대신 `MemorySaver` 사용 (코드 수정 필요)
- 패키지 버전 다운그레이드

### Discord 봇이 응답하지 않음

**확인 사항**:
1. `.env`의 `DISCORD_TOKEN`이 올바른지 확인
2. Discord 개발자 포털에서 MESSAGE CONTENT INTENT 활성화 확인
3. 봇이 서버에 초대되었는지 확인

### Slack 봇 channel_not_found 에러

**원인**: 봇이 해당 채널에 접근 권한이 없음

**해결**:
1. Slack 워크스페이스에서 해당 채널로 이동
2. `/invite @봇이름` 명령으로 봇 초대
3. 또는 채널 설정 → Integrations → Add apps에서 봇 추가

## 주의사항

### 보안
- `.env` 파일에는 민감한 API 키가 포함되므로 **절대 Git에 커밋하지 마세요**
- `.gitignore`에 `.env` 추가 권장

### ngrok URL 자동 업데이트
- `SLACK_MCP_URL`은 `start-slack-mcp.sh` 실행 시 자동으로 `.env`에 저장됩니다
- ngrok 재시작 시마다 URL이 변경되므로 재실행 필요

### 비동기 실행 구조
- **Discord MCP 서버**: 2개의 독립적인 이벤트 루프 사용
  - 메인 루프: Discord 봇 (24시간 메시지 수신)
  - 별도 스레드: FastMCP HTTP 서버 (MCP 요청 처리)
  - 크로스-스레드 통신: `asyncio.run_coroutine_threadsafe` 사용

### 대화 기록 저장
- SQLite 기반 checkpoint 사용 시 세션 ID로 이전 대화 복원 가능
- MemorySaver 사용 시 프로그램 재시작 시 대화 기록 소실

## 참고 자료

- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [MCP Protocol](https://modelcontextprotocol.io/)
- [ngrok Documentation](https://ngrok.com/docs)
