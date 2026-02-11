#!/bin/bash

echo "========================================="
echo "ngrok 설치 및 설정 스크립트"
echo "========================================="

# ngrok 설치 확인
if command -v ngrok &> /dev/null; then
    echo "✅ ngrok이 이미 설치되어 있습니다."
else
    echo "📦 ngrok 설치 중..."
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
      | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null \
      && echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
      | tee /etc/apt/sources.list.d/ngrok.list \
      && apt update \
      && apt install ngrok

    if [ $? -eq 0 ]; then
        echo "✅ ngrok 설치 완료"
    else
        echo "❌ ngrok 설치 실패"
        exit 1
    fi
fi

# authtoken 설정
echo "🔑 ngrok authtoken 설정 중..."
ngrok config add-authtoken {YOUR_NGROK_AUTHTOKEN_HERE}

if [ $? -eq 0 ]; then
    echo "✅ authtoken 설정 완료"
else
    echo "❌ authtoken 설정 실패"
    exit 1
fi

echo "========================================="
echo "ngrok 설정 완료!"
echo "이제 start-slack-mcp.sh를 실행할 수 있습니다."
echo "========================================="
