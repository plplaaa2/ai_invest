#!/usr/bin/env bash
echo "🚀 AI Analyst 통합 서비스를 시작합니다..."
cd /app

# 0. 필수 패키지 설치 체크 및 설치
echo "📦 라이브러리 상태를 점검합니다..."

# 🎯 fpdf2(PDF 생성), pykrx(지표 수집), pandas(데이터 처리) 존재 여부 확인
python3 -c "import fpdf, pykrx, pandas, yfinance" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️ 필수 라이브als러리가 누락되었습니다. 설치를 시작합니다..."
    pip install --no-cache-dir fpdf2 pykrx pandas yfinance
    echo "✅ 라이브러리 설치 완료"
else
    echo "✅ 모든 라이브러리가 이미 설치되어 있습니다."
fi

echo "📂 폰트 정비 중..."
mkdir -p /app/fonts
# 🎯 폰트 파일이 없을 때만 다운로드 (기존 로직 유지)
if [ ! -f "/app/fonts/NanumGothic.ttf" ]; then
    echo "📥 나눔고딕 폰트가 없습니다. 다운로드를 시작합니다..."
    python3 -c "import urllib.request; urllib.request.urlretrieve('https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf', '/app/fonts/NanumGothic.ttf')"
    echo "✅ 나눔고딕 다운로드 완료"
else
    echo "✅ 나눔고딕 폰트가 이미 존재합니다."
fi

# 1. RSS 수집기 및 자동 보고서 스케줄러 실행 (-u 옵션)
python3 -u /app/scraper.py &

# 3. Streamlit 웹 UI 실행
python3 -m streamlit run /app/app.py \
    --server.port 8501 \
    --server.address 0.0.0.0
