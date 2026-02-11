#!/bin/bash
echo "========================================="
echo "Node.js 및 npm 설치 스크립트"
echo "========================================="
# Node.js 설치 확인
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    echo "✅ Node.js가 이미 설치되어 있습니다: $NODE_VERSION"
else
    echo "📦 Node.js 설치 중..."
    # NodeSource repository 추가 (Node.js 20.x LTS)
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    # Node.js 설치
    apt-get install -y nodejs
    if [ $? -eq 0 ]; then
        NODE_VERSION=$(node --version)
        NPM_VERSION=$(npm --version)
        echo "✅ Node.js 설치 완료: $NODE_VERSION"
        echo "✅ npm 설치 완료: $NPM_VERSION"
    else
        echo "❌ Node.js 설치 실패"
        exit 1
    fi
fi
# npx 확인
if command -v npx &> /dev/null; then
    NPX_VERSION=$(npx --version)
    echo "✅ npx 사용 가능: $NPX_VERSION"
else
    echo "❌ npx를 찾을 수 없습니다"
    exit 1
fi
echo "========================================="
echo "Node.js 설정 완료!"
echo "이제 start-slack-mcp.sh를 실행할 수 있습니다."
echo "========================================="
