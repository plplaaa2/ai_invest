# 🤖 AI Invest Lite (Home Assistant Add-on)

**AI Invest Lite**는 Home Assistant 환경에서 사용자가 지정한 RSS 피드의 뉴스를 수집하고, 로컬 LLM(Local LLM)을 연동하여 심도 있는 뉴스 요약 및 투자 보고서를 생성하는 도구입니다.

AI가 만든 투자 보고서는 참고 자료일 뿐이며 생성된 보고서의 질은 수집된 뉴스와 AI 모델의 성능, 프롬프트의 정교함에 따라 올라갑니다.

---

## 🌟 핵심 기능 (Core Features)

### 1. 스마트 뉴스 큐레이션
- **RSS 실시간 수집**: 사용자 정의 RSS 피드로부터 최신 시장 동향을 끊임없이 확보합니다. 
- **정밀 필터링**: 제목 기반의 전역/개별 키워드 필터링을 통해 투자에 불필요한 노이즈를 완벽히 제거합니다.
- **뉴스 AI분석**: 이해하기 어려운 경제뉴스를 AI가 분석하여 알기 쉽게 알려줍니다.

### 2. RAG 기반 AI 전략 보고서
- **역사적 맥락 복기 (Memory)**: 단순히 현재 뉴스만 분석하지 않고, 과거의 일간/주간/월간 리포트를 참조하여 전략의 일관성을 유지합니다.
- **계층형 자동 생성**: Daily(뉴스 중심), Weekly(트렌드 중심), Monthly(거시 지표 중심) 보고서를 주기에 맞춰 자동 발행합니다.
- **대화형 리포트**: 생성된 보고서 내용을 바탕으로 AI와 실시간 질의응답이 가능합니다.

### 3. 지능형 자가 유지보수
- **🏛️ 계층형 AI 보고서**:
  - **Daily**: 금일 시황 및 뉴스 분석, 유동성 및 자산별 점수 산정.
  - **Weekly**: 한 주간의 인과관계 규명 및 흐름 요약.
  - **Monthly**: 거시경제적 구조 변화 및 장기 추세 기록.
- **PDF Export**: 분석된 전략 리포트를 나눔고딕 폰트가 적용된 PDF 문서로 즉시 출력할 수 있습니다.
---

## 🛠️ 설치 방법 (Installation)

1. **Home Assistant** 대시보드에서 `설정 > 애드온 > 애드온 상점`으로 이동합니다.
2. 우측 상단 메뉴(⋮)에서 **리포지토리(Repositories)**를 선택합니다.
3. 이 GitHub 리포지토리의 URL을 추가합니다.
4. 목록에 새로 고침 후 나타나는 **AI Analyst Lite**를 클릭하여 설치합니다.
5. `Web UI 열기`를 통해 대시보드에 접속합니다.

---

## 🛠️ 기술 스택 (Tech Stack)

- **UI/UX**: Streamlit
- **Backend**: Python 3.9+
- **LLM**: Ollama (Local), Google Gemini (Cloud), OpenAI GPT (Cloud)
- **Data Storage**: Local Text Files (Flat-file DB System)
- **Data collect**: Pykrx, Yfinance
---

## 데이터 저작권

 - 모든 금융데이터는 사용자의 로컬환경에서 pykrx 및 yfinance 라이브를 통해 실시간으로 호출 됩니다.
 - 각 데이터의 저작권은 한국거래소, 네이버금융, Yahoo Finance 등 원천제공처에 있습니다.
 - 본 도구를 상업적 목적으로 이용하거나 데이터를 무단 재배포하여 발생하는 모든 법적 책임은 사용자 본인에게 있습니다.
 - 개발자는 본 소프트웨어의 사용으로 인해 발생하는 어떠한 손실이나 손해에 대해서도 책임을 지지 않습니다.
---

## ⚙️ 설정 가이드 (Configuration)

### 1. 애드온 구성 (HA Configuration)
애드온의 **구성** 탭에서 웹 UI 포트를 설정합니다.
- `web_port`: 기본값 `8501`
- `openai_api_key`: 'option`
- `gemini_api_key`: 'option`

### 2. 내부 시스템 설정 (Web UI)
애드온 실행 후 웹 UI의 **[설정]** 메뉴에서 다음 항목을 입력해야 기능이 활성화됩니다.
- **로컬 AI 서버**: 사용 중인 데스크탑의 IP 주소와 LLM API 포트
  (예: local: `192.168.x.x`, `1234` or cloud: https://generativelanguage.googleapis.com)
- **AI 모델명**: 서버에 로드된 모델 이름 (예: `gpt-oss-20b`)
- **시스템 프롬프트**: 분석 시 AI가 가질 전문적인 역할 설정

---

## 📂 리포지토리 구조 (Project Structure)

```text
/
├── repository.yaml           # 리포지토리 정보 정의
├── README.md                 # 프로젝트 메인 설명
└── ai_analyst/               # 애드온 패키지 폴더
    ├── .streamlit            # 웹 인터페이스 설정
    ├── config.yaml           # 애드온 실행 환경 설정
    ├── Dockerfile            # 컨테이너 빌드 정의
    ├── run.sh                # 프로세스 자동 실행 스크립트
    ├── app.py                # Streamlit 기반 메인 웹 인터페이스
    ├── common.py             # 공통 엔진
    ├── prompt.py             # 보고서 작성 프롬프트 설정
    └── scraper.py            # RSS 뉴스 수집 엔진
```
