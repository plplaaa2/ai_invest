# 🤖 AI Invest Lite (Home Assistant Add-on)

**AI Invest Lite**는 Home Assistant 환경에서 사용자가 지정한 RSS 피드의 뉴스를 수집하고, 로컬 LLM(Local LLM)을 연동하여 심도 있는 뉴스 요약 및 투자 보고서를 생성하는 도구입니다.

AI가 만든 투자 보고서는 참고 자료일 뿐이며 생성된 보고서의 질은 수집된 뉴스와 AI 모델의 성능, 프롬프트의 정교함에 따라 올라갑니다.

---

## 🌟 핵심 기능 (Core Features)

### 1. 스마트 뉴스 큐레이션
- **RSS 실시간 수집**: 사용자 정의 RSS 피드로부터 최신 시장 동향을 끊임없이 확보합니다.
- **정보량 기반 가변 갱신**: 동일 뉴스 수집 시, 더 많은 정보(요약본 길이 등)를 담은 최신 기사로 자동 업데이트합니다.
- **정밀 필터링**: 제목 기반의 전역/개별 키워드 필터링을 통해 투자에 불필요한 노이즈를 완벽히 제거합니다.

### 2. RAG 기반 AI 전략 보고서
- **역사적 맥락 복기 (Memory)**: 단순히 현재 뉴스만 분석하지 않고, 과거의 일간/주간/월간 리포트를 참조하여 전략의 일관성을 유지합니다.
- **계층형 자동 생성**: Daily(뉴스 중심), Weekly(트렌드 중심), Monthly(거시 지표 중심) 보고서를 주기에 맞춰 자동 발행합니다.
- **대화형 리포트**: 생성된 보고서 내용을 바탕으로 AI와 실시간 질의응답이 가능합니다.

### 3. 지능형 자가 유지보수
- **계층형 파일 정제 (Purge)**: 
  - **일간 보고서**: 9일 보관
  - **주간 보고서**: 35일 보관
  - **월간 보고서**: 370일 보관
  - 설정된 기간이 지나면 스토리지 용량 확보를 위해 오래된 리포트를 자동으로 삭제합니다.
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
    └── scraper.py            # RSS 뉴스 수집 엔진
