import streamlit as st
import pandas as pd
import json
import os
import feedparser
import re
import requests
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup
import time
import math

# --- 1. 경로 및 설정 로드 ---
CONFIG_PATH = "/share/ai_analyst/rss_config.json"
PENDING_PATH = "/share/ai_analyst/pending"
OPTIONS_PATH = "/data/options.json"

# --- 2. 뉴스 처리 핵심 함수 ---
def load_data():
    """설정 파일을 로드하며, 멀티 모델 구조를 지원하도록 생성합니다."""
    default_structure = {
        "feeds": [], 
        "update_interval": 10, 
        "view_range": "실시간",
        "retention_days": 7,
        
        # 🎯 뉴스 판독 모델 설정 (Filter)
        "filter_model": {
            "provider": "Local",      # Local, Gemini, OpenAI 선택 가능
            "name": "openai/gpt-oss-20b",
            "url": "http://192.168.1.2:1234/v1",
            "key": "",
            "prompt": "투자 분석가입니다. 제공된 뉴스를 거시경제, 증시, 채권, 환율, 원자재로 분류하고 요약 후 0~5점을 매깁니다. 4점 이상은 상세 요약을 하며 요약 구조는 제목, 날짜, 출처, 분류, 요약, 점수 순으로 합니다."
        },
        
        # 🏛️ 투자 보고서 모델 설정 (Analyst)
        "analyst_model": {
            "provider": "Local",
            "name": "openai/gpt-oss-20b",
            "url": "http://192.168.1.105:11434/v1",
            "key": "",
            "prompt": "투자 전략가로서 제공된 뉴스의 지표를 수집하여 표로 만들고 각 지표를 분석하여 전체 시황과 유동성 위기를 진단하고 투자자를 위한 섹터별 조언 및 총평을 하시오"
        },

        "report_news_count": 30,
        "report_auto_gen": False,
        "report_gen_time": "08:00",
        "report_days": 3
    }
    
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # 💡 새로운 멀티 모델 구조가 없으면 기본값으로 채워넣음
                for key, val in default_structure.items():
                    if key not in loaded: 
                        loaded[key] = val
                return loaded
        except: pass
    return default_structure

# 초기 설정 로드
data = load_data()

# app.py 내의 is_filtered 함수를 이 내용으로 교체하세요.
def is_filtered(title, summary, g_inc, g_exc, l_inc="", l_exc=""):
    # 변수 보존: 제목(title) 기준 필터링
    text = title.lower().strip()
    
    # 1. 제외 필터: 전역/개별 제외어 중 하나라도 제목에 있으면 즉시 탈락
    exc_tags = [t.strip().lower() for t in (g_exc + "," + l_exc).split(",") if t.strip()]
    if any(t in text for t in exc_tags): 
        return False
    
    # 2. 전역 포함어: 값이 설정된 경우에만 제목에 해당 단어가 있어야 통과
    g_inc_tags = [t.strip().lower() for t in g_inc.split(",") if t.strip()]
    if g_inc_tags and not any(t in text for t in g_inc_tags):
        return False
        
    # 3. 개별 포함어: 값이 설정된 경우에만 제목에 해당 단어가 있어야 통과
    l_inc_tags = [t.strip().lower() for t in l_inc.split(",") if t.strip()]
    if l_inc_tags and not any(t in text for t in l_inc_tags):
        return False
    
    return True

def load_historical_contexts():
    """과거 리포트 맥락 로드 로직 [보존]"""
    base_dir = REPORTS_BASE_DIR
    dir_map = {
        'YEARLY_STRATEGY': '04_yearly/latest.txt',
        'MONTHLY_THEME': '03_monthly/latest.txt',
        'WEEKLY_MOMENTUM': '02_weekly/latest.txt',
        'DAILY_LOG': '01_daily/latest.txt'
    }
    
    context_text = "### [ 역사적 맥락 참조 데이터 ]\n"
    for label, rel_path in dir_map.items():
        full_path = os.path.join(base_dir, rel_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                if len(content.strip()) > 10:
                    context_text += f"\n<{label}>\n{content[:1000]}\n"
                else:
                    context_text += f"\n<{label}>: 해당 주기의 분석 데이터가 아직 비어 있습니다.\n"
        else:
            context_text += f"\n<{label}>: 데이터가 생성되지 않았습니다. 현재 데이터 중심으로 분석하십시오.\n"
    return context_text

# 초기 데이터 로드 실행
data = load_data()

# --- 2. 뉴스 처리 및 AI 분석 함수 ---
def get_ai_summary(title, content, system_instruction=None, role="filter"):
    # 🕒 현재 시간 확보 (한국 시간 기준)
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 설정 데이터(data)에서 역할에 맞는 모델 설정 로드
    cfg = data.get("filter_model") if role == "filter" else data.get("analyst_model")
    
    base_url = cfg.get("url", "").rstrip('/')
    url = f"{base_url}/chat/completions"
    
    # 💡 [보안/인증] API Key가 설정되어 있다면 헤더에 추가 (OpenAI 등 공용 API 대응)
    headers = {}
    if cfg.get("key"):
        headers["Authorization"] = f"Bearer {cfg['key']}"
    
    # 시스템 프롬프트 구성: 현재 시간을 주입하여 AI가 시점 정보를 인지하게 함
    user_prompt = system_instruction if system_instruction else cfg["prompt"]
    final_role = f"현재 시각: {now_time}\n분석 지침: {user_prompt}"

    payload = {
        "model": cfg["name"],
        "messages": [
            {"role": "system", "content": final_role},
            {"role": "user", "content": f"분석 기준 시각: {now_time}\n제목: {title}\n본문: {content}"}
        ],
        "temperature": 0.3
    }

    try:
        # 대량 뉴스 처리를 위해 타임아웃 600초 유지
        resp = requests.post(url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status() 
        return resp.json()['choices'][0]['message']['content']

    except requests.exceptions.Timeout:
        error_msg = f"❌ [TIMEOUT] AI 분석 시간이 초과되었습니다. (서버 응답 확인 필요)"
        print(f"[{now_time}] {error_msg}")
        return error_msg

    except requests.exceptions.ConnectionError:
        error_msg = f"❌ [CONNECTION] AI 서버({base_url})에 연결할 수 없습니다."
        print(f"[{now_time}] {error_msg}")
        return error_msg

    except Exception as e:
        error_msg = f"❌ [ERROR] AI 분석 중 예외 발생: {str(e)}"
        print(f"[{now_time}] {error_msg}")
        return error_msg
        
# [수정] 인자에 pub_dt(날짜)를 추가합니다.
@st.dialog("📊 AI 정밀 분석 리포트")
def show_analysis_dialog(title, summary_text, pub_dt, role="filter"): 
    with st.spinner("AI가 뉴스를 심층 분석 중입니다..."):
        # 💡 [전략] 기사 작성일(pub_dt)과 분석 시점(현재)의 간극을 AI가 인지하도록 제목 구성
        enhanced_title = f"(기사작성일: {pub_dt}) {title}"
        analysis = get_ai_summary(enhanced_title, summary_text, role=role)
    
    # 상단 헤더 섹션
    st.markdown(f"### {title}")
    st.caption(f"📅 기사 작성일: {pub_dt}") 
    st.divider()
    
    # AI 분석 본문
    st.markdown(analysis)
    st.divider()
    
    # 하단 정보 및 원문 섹션
    with st.expander("기사 원문 요약 보기"):
        st.write(summary_text)

    # 🤖 모델 정보 및 분석 시각 (디버깅 및 신뢰도용)
    model_cfg = data.get("filter_model" if role == "filter" else "analyst_model", {})
    model_name = model_cfg.get("name", "Unknown Model")
    
    # 🕒 현재 분석 시각을 구해서 캡션에 추가
    analysis_time = datetime.now().strftime('%H:%M:%S')
    
    st.caption(
        f"🤖 분석 모델: {model_name} | "
        f"🕒 분석 완료 시각: {analysis_time} | "
        f"📊 역할: {'뉴스 필터링' if role == 'filter' else '심층 분석'}"
    )

def check_filters(title, include_str, exclude_str):
    title = title.lower().strip()
    if exclude_str:
        exc_tags = [t.strip().lower() for t in exclude_str.split(",") if t.strip()]
        if any(t in title for t in exc_tags): return False
    if include_str:
        inc_tags = [t.strip().lower() for t in include_str.split(",") if t.strip()]
        if not any(t in title for t in inc_tags): return False
    return True

def clean_html(raw_html):
    if not raw_html: return "요약 내용 없음"
    soup = BeautifulSoup(raw_html, "html.parser")
    for s in soup(['style', 'script', 'span']): s.decompose()
    return re.sub(r'\s+', ' ', soup.get_text()).strip()

def parse_rss_date(date_str):
    try:
        p = feedparser._parse_date(date_str)
        return datetime.fromtimestamp(time.mktime(p))
    except: return datetime.now()

def format_korean_unit(num):
    """숫자를 조, 억 단위로 변환합니다."""
    if num is None or num == 0: return "0"
    if num >= 1e12:
        return f"{num / 1e12:.2f}조"
    elif num >= 1e8:
        return f"{num / 1e8:.2f}억"
    elif num >= 1e4:
        return f"{num / 1e4:.1f}만"
    return f"{num:,.0f}"

def load_pending_files(range_type, target_feed=None):
    news_list = []
    if not os.path.exists(PENDING_PATH): return news_list
    today_date = date.today()
    one_week_ago = datetime.now() - timedelta(days=7)
    for filename in os.listdir(PENDING_PATH):
        if filename.endswith(".txt"):
            try:
                with open(os.path.join(PENDING_PATH, filename), 'r', encoding='utf-8') as f:
                    lines = f.read().splitlines()
                    title = lines[0].replace("제목: ", "")
                    link = lines[1].replace("링크: ", "")
                    pub_str = lines[2].replace("날짜: ", "")
                    summary = "\n".join(lines[3:]).replace("요약: ", "")
                    pub_dt = parse_rss_date(pub_str)
                    if range_type == "오늘" and pub_dt.date() != today_date: continue
                    if range_type == "일주일" and pub_dt < one_week_ago: continue
                    if target_feed:
                        if not check_filters(title, target_feed.get('include', ""), target_feed.get('exclude', "")): continue
                    news_list.append({"title": title, "link": link, "published": pub_str, "summary": summary, "pub_dt": pub_dt, "source": "저장된 데이터"})
            except: continue
    news_list.sort(key=lambda x: x['pub_dt'], reverse=True)
    return news_list
    
def save_report_to_file(content, section_name):
    """AI 보고서를 파일로 저장하고 주기에 따라 오래된 파일을 정제합니다."""
    # 1. 경로 설정 및 폴더 세분화 (기존 경로 유지)
    base_dir = "/share/ai_analyst/reports"
    dir_map = {
        'daily': '01_daily', 
        'weekly': '02_weekly', 
        'monthly': '03_monthly', 
        'yearly': '04_yearly'
    }
    
    # section_name이 맵에 없으면 기본(etc) 폴더 사용
    subdir = dir_map.get(section_name.lower(), "05_etc")
    report_dir = os.path.join(base_dir, subdir)
    os.makedirs(report_dir, exist_ok=True) # 폴더가 없으면 생성
    
    # 2. 파일명 생성 및 저장 (타임스탬프 기반 기록용)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}_{section_name.replace(' ', '_')}.txt"
    filepath = os.path.join(report_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    # 3. 🎯 AI 참조용 Latest 파일 갱신 (RAG 분석용 고정 경로)
    # 이 파일은 load_historical_contexts()에서 최신 맥락을 읽을 때 사용됩니다.
    latest_path = os.path.join(report_dir, "latest.txt")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 4. 🧹 계층형 자동 정제 (Purge) 로직
    # 보관 규칙: Daily(7일), Weekly(30일), Monthly(365일)
    purge_rules = {'01_daily': 7, '02_weekly': 30, '03_monthly': 365}
    
    if subdir in purge_rules:
        limit_days = purge_rules[subdir]
        # 현재 시간 기준으로 보관 한계 시점 계산
        threshold = time.time() - (limit_days * 86400)
        
        for f in os.listdir(report_dir):
            if f == "latest.txt": continue # 최신 맥락 파일은 보호
            f_p = os.path.join(report_dir, f)
            # 수정 시간(mtime)이 한계점보다 오래된 파일 삭제
            if os.path.isfile(f_p) and os.path.getmtime(f_p) < threshold:
                try:
                    os.remove(f_p)
                except Exception as e:
                    print(f"파일 삭제 에러 ({f}): {e}")
                
    return filepath
    
def save_data(data):
    """변경된 설정 데이터를 JSON 파일로 안전하게 저장합니다."""
    # 폴더가 없으면 자동으로 생성합니다.
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    
    # 파일을 열어 딕셔너리 데이터를 기록합니다.
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        # 한글 깨짐 방지 및 가독성을 위해 옵션을 추가합니다.
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 2. 표시용 이름 딕셔너리
    
# --- 3. UI 및 CSS 설정 ---
st.set_page_config(page_title="AI Analyst", layout="wide")

st.markdown("""
    <style>
    [data-testid="stPopoverBody"] { width: 170px !important; padding: 10px !important; }
    [data-testid="stPopoverBody"] button { padding: 2px 5px !important; margin-bottom: 2px !important; height: auto !important; font-size: 14px !important; }
    [data-testid="stSidebar"] { display: none; }
    /* 지표 관련 CSS는 필요 없으므로 stMetricValue 스타일은 삭제하거나 유지해도 무방합니다 */
    </style>
    """, unsafe_allow_html=True)

# 초기 세션 상태 설정 (기본 메뉴를 "뉴스"로 변경)
if 'active_menu' not in st.session_state: 
    st.session_state.active_menu = "뉴스"
if 'current_feed_idx' not in st.session_state: 
    st.session_state.current_feed_idx = "all"
if 'page_number' not in st.session_state: 
    st.session_state.page_number = 1

# --- 4. 최상단 대메뉴 (시장 지표 제거) ---
st.title("🤖 AI Analyst System")

# 메뉴가 3개이므로 컬럼을 3개로 조정합니다.
m_cols = st.columns(3)
menu_items = [
    ("📡 뉴스 스트리밍", "뉴스"), 
    ("🏛️ AI 투자 보고서", "AI"), 
    ("⚙️ 설정", "설정")
]

for i, (label, m_key) in enumerate(menu_items):
    if m_cols[i].button(label, use_container_width=True, type="primary" if st.session_state.active_menu == m_key else "secondary"):
        st.session_state.active_menu = m_key
        st.rerun()

st.divider()

# --- 5. 메뉴별 본문 화면 구성 ---

if st.session_state.active_menu == "설정":
    st.subheader("⚙️ 로컬 멀티 AI 서버 및 시스템 설정")
    
    # 세 가지 설정 탭으로 통합 관리
    tab_f, tab_a, tab_g = st.tabs(["🎯 뉴스 판독 (Filter)", "🏛️ 투자 분석 (Analyst)", "🌐 일반 설정"])

    with tab_f:
        st.markdown("#### 📡 뉴스 스트리밍 요약용 모델")
        f_cfg = data.get("filter_model")
        # 고유 키: f_url_input
        f_url = st.text_input("API 서버 주소 (URL)", value=f_cfg.get("url"), help="예: http://192.168.1.2:1234/v1", key="f_url_input")
        f_name = st.text_input("모델명", value=f_cfg.get("name"), key="f_name_input")
        f_prompt = st.text_area("기본 요약 지침", value=f_cfg.get("prompt"), height=100, key="f_prompt_input")
        
        if st.button("💾 판독 모델 설정 저장", use_container_width=True):
            data["filter_model"].update({"url": f_url, "name": f_name, "prompt": f_prompt})
            save_data(data); st.success("✅ 판독 모델 설정 저장 완료!")

    with tab_a:
        st.markdown("#### 🏛️ 투자 보고서 생성용 모델")
        a_cfg = data.get("analyst_model")
        # 고유 키: a_url_input
        a_url = st.text_input("API 서버 주소 (URL)", value=a_cfg.get("url"), help="예: http://192.168.1.105:11434/v1", key="a_url_input")
        a_name = st.text_input("모델명", value=a_cfg.get("name"), key="a_name_input")
        
        if st.button("💾 분석 모델 설정 저장", use_container_width=True):
            data["analyst_model"].update({"url": a_url, "name": a_name})
            save_data(data); st.success("✅ 분석 모델 설정 저장 완료!")

    with tab_g:
        st.markdown("#### ⚙️ 시스템 공통 및 뉴스 수집 설정")
        col1, col2 = st.columns(2)
        
        # 1. 뉴스 수집 및 보관 설정
        new_retention = col1.slider("뉴스 파일 보관 기간 (일)", 1, 30, value=data.get("retention_days", 7), key="cfg_retention_days")
        new_interval = col2.number_input("RSS 수집 주기 (분)", 1, value=data.get("update_interval", 10), key="cfg_update_interval")
        
        st.divider()
        
        st.markdown("#### 📑 AI 투자 보고서 자동화")
        # 2. 자동 생성 및 시간 설정
        col_auto, col_time = st.columns([0.4, 0.6])
        auto_gen = col_auto.toggle("매일 보고서 자동 생성", value=data.get("report_auto_gen", False), key="cfg_report_auto_gen")
        gen_time = col_time.text_input("생성 시간 (24시간제, 예: 08:00)", value=data.get("report_gen_time", "08:00"), key="cfg_report_gen_time")
        
        # 3. 분석 뉴스 개수 설정 (최대 500개로 확장 및 날짜 범위 제거)
        # 이제 AI는 날짜 범위 대신 '최신 뉴스 N개'와 '과거 리포트 맥락'으로만 분석합니다.
        report_news_count = st.slider("분석 포함 뉴스 개수 (최대 500개)", 10, 500, value=data.get("report_news_count", 100), key="cfg_report_news_count")

        if st.button("💾 모든 시스템 설정 저장", use_container_width=True, type="primary"):
            # 데이터 구조 업데이트 (report_days 항목 제거)
            data.update({
                "retention_days": new_retention,
                "update_interval": new_interval,
                "report_auto_gen": auto_gen,
                "report_gen_time": gen_time,
                "report_news_count": report_news_count
            })
            # 필요 없는 구형 설정 키 삭제
            if "report_days" in data:
                del data["report_days"]
                
            save_data(data)
            st.success("✅ 불필요한 범위를 제거하고 뉴스 처리량이 500개로 확장되었습니다.")
            st.rerun() 

    st.write("") # 간격 조절
        

# [2. 뉴스 스트리밍]
elif st.session_state.active_menu == "뉴스":    
    col_side, col_main = st.columns([0.22, 0.78])
    
    with col_side:
        st.markdown("#### 📌 RSS 관리")
        # 전체 보기 버튼
        if st.button("🏠 전체 보기", use_container_width=True, type="primary" if st.session_state.current_feed_idx == "all" else "secondary"):
            st.session_state.current_feed_idx = "all"; st.session_state.page_number = 1; st.rerun()
        
# 각 피드 리스트 및 관리 메뉴
        for i, f in enumerate(data.get('feeds', [])):
            btn_col, pop_col = st.columns([0.8, 0.2])
            with btn_col:
                if st.button(f['name'], key=f"f_{i}", use_container_width=True, type="primary" if st.session_state.current_feed_idx == i else "secondary"):
                    st.session_state.current_feed_idx = i; st.session_state.page_number = 1; st.rerun()
            with pop_col:
                # 아이콘 없이 '설정' 텍스트만 사용하거나 더 작게 줄인 팝업
                with st.popover(""):
                    # 아이콘(✏️, 🔍, 🗑️)을 모두 제거하고 텍스트로만 구성
                    if st.button("편집", key=f"ed_{i}", use_container_width=True):
                        @st.dialog("피드 수정")
                        def ed_diag(idx=i):
                            fe = data['feeds'][idx]
                            n = st.text_input("이름", value=fe['name'])
                            u = st.text_input("URL", value=fe['url'])
                            if st.button("저장"):
                                data['feeds'][idx].update({"name": n, "url": u}); save_data(data); st.rerun()
                        ed_diag()
                    
                    if st.button("필터", key=f"fi_{i}", use_container_width=True):
                        @st.dialog("키워드 필터")
                        def fi_diag(idx=i):
                            fe = data['feeds'][idx]
                            inc = st.text_area("포함 키워드", value=fe.get('include', ""))
                            exc = st.text_area("제외 키워드", value=fe.get('exclude', ""))
                            if st.button("필터 적용"):
                                data['feeds'][idx].update({"include": inc, "exclude": exc}); save_data(data); st.rerun()
                        fi_diag()
                        
                    if st.button("삭제", key=f"de_{i}", use_container_width=True):
                        data['feeds'].pop(i); save_data(data); st.rerun()
        
        st.divider()
        # [복구] 피드 추가 버튼
        if st.button("➕ 새 RSS 추가", use_container_width=True):
            @st.dialog("새 RSS 등록")
            def add_diag():
                n = st.text_input("피드 이름 (예: 연합뉴스)")
                u = st.text_input("RSS URL 주소")
                if st.button("등록 완료"):
                    data['feeds'].append({"name": n, "url": u, "include": "", "exclude": ""})
                    save_data(data); st.rerun()
            add_diag()
    with col_side:
        # [추가] 전역 필터 설정 구역
        with st.expander("🌐 전역 필터 설정", expanded=False):
            g_inc = st.text_area("전역 포함 키워드", value=data.get("global_include", ""), help="쉼표(,)로 구분")
            g_exc = st.text_area("전역 제외 키워드", value=data.get("global_exclude", ""), help="쉼표(,)로 구분")
            if st.button("전역 필터 저장", use_container_width=True):
                data.update({"global_include": g_inc, "global_exclude": g_exc})
                save_data(data)
                st.toast("전역 필터가 저장되었습니다!")

    with col_main:
        full_list = []
        target = data.get('feeds', []) if st.session_state.current_feed_idx == "all" else [data['feeds'][st.session_state.current_feed_idx]]
        
        for f_info in target:
            try:
                parsed = feedparser.parse(f_info['url'])
                for e in parsed.entries:
                    # 강화된 제목 필터 적용 (버그 수정됨)
                    if is_filtered(e.title, e.get('summary', ''), 
                                   data.get("global_include", ""), data.get("global_exclude", ""),
                                   f_info.get('include', ""), f_info.get('exclude', "")):
                        e['source'] = f_info['name']
                        full_list.append(e)
            except: continue
            
        full_list.sort(key=lambda x: x.get('published_parsed', 0), reverse=True)
        
        if full_list:
            # 1. 페이지네이션 변수 정의
            items_per_page = 10
            total_pages = math.ceil(len(full_list) / items_per_page)
            
            # 2. 현재 페이지 슬라이싱 계산
            start_idx = (st.session_state.page_number - 1) * items_per_page
            end_idx = start_idx + items_per_page
            
            # 3. 뉴스 기사 반복 출력
            for entry in full_list[start_idx:end_idx]:
                with st.container(border=True):
                    st.caption(f"📍 {entry.get('source')} | {entry.get('published', '')}")
                    st.markdown(f"#### {entry.get('title')}")
                    
                    cleaned_summary = clean_html(entry.get('summary', ''))
                    st.write(cleaned_summary[:200] + "...")
                    
                    btn_c1, btn_c2 = st.columns([0.2, 0.8])
                    
                    # 1. 원문 읽기
                    btn_c1.link_button("🌐 원문 읽기", entry.get('link', '#'), use_container_width=True)
                    
                    # 2. AI 요약 분석 (클릭 즉시 분석 팝업 실행)
                    if btn_c2.button("🤖 AI 요약 분석", key=f"ai_btn_{entry.get('link')}", use_container_width=True):
                        show_analysis_dialog(entry.get('title'), cleaned_summary, entry.get('published', '날짜 미상'), role="filter")

            st.divider()
            
            # --- [ 4. 개선된 페이지 내비게이터 ] ---
            if total_pages > 1:
                # 10단위 뭉치 계산
                current_group = (st.session_state.page_number - 1) // 10
                start_page = current_group * 10 + 1
                end_page = min(start_page + 9, total_pages)
                
                # 버튼 레이아웃 (이전 + 숫자 10개 + 다음)
                nav_cols = st.columns([0.6] + [1] * (end_page - start_page + 1) + [0.6])
                
                # [ < ] 이전 10개 뭉치 이동
                if start_page > 1:
                    if nav_cols[0].button("<", key="prev_group"):
                        st.session_state.page_number = start_page - 1
                        st.rerun()
                
                # 숫자 버튼들
                for i, page_idx in enumerate(range(start_page, end_page + 1)):
                    if nav_cols[i+1].button(
                        str(page_idx), 
                        key=f"page_{page_idx}",
                        type="primary" if st.session_state.page_number == page_idx else "secondary",
                        use_container_width=True
                    ):
                        st.session_state.page_number = page_idx
                        st.rerun()
                
                # [ > ] 다음 10개 뭉치 이동
                if end_page < total_pages:
                    if nav_cols[-1].button(">", key="next_group"):
                        st.session_state.page_number = end_page + 1
                        st.rerun()
        else:
            st.warning("📡 표시할 뉴스가 없습니다.")

elif st.session_state.active_menu == "AI":
    st.subheader("📑 AI 투자 보고서")
    
    # 1. 세션 및 경로 설정
    if "report_chat_history" not in st.session_state:
        st.session_state.report_chat_history = []
    if "last_report_content" not in st.session_state:
        st.session_state.last_report_content = ""

    # 경로 설정 (기존 유지)
    REPORT_DIR = "/share/ai_analyst/reports"
    os.makedirs(REPORT_DIR, exist_ok=True)

    # [신규 로직] 세션에 보고서가 없으면 저장된 파일 중 가장 최신 것 로드
    if not st.session_state.last_report_content:
        # 파일 리스트 확보 (latest.txt 제외한 기록 파일들)
        report_files = sorted([f for f in os.listdir(REPORT_DIR) if f.endswith(".txt") and "latest" not in f], reverse=True)
        if report_files:
            latest_file = report_files[0]
            try:
                # 최신 파일이 존재하는 서브 디렉토리까지 찾기 위해 daily 폴더 확인
                daily_dir = os.path.join(REPORT_DIR, "01_daily")
                daily_files = sorted([f for f in os.listdir(daily_dir) if f.endswith(".txt")], reverse=True)
                if daily_files:
                    with open(os.path.join(daily_dir, daily_files[0]), "r", encoding="utf-8") as f:
                        st.session_state.last_report_content = f.read()
            except:
                pass

    # 설정값 로드
    analysis_range = data.get("report_days", 3)
    council_instruction = data.get("council_prompt", "시니어 투자 전략가로서 종합 의견을 제시하라.")

    # 2. 분석 실행 섹션
    with st.container(border=True):
        st.markdown("### 🏛️ 시장 종합 의견 분석")
        
        # 분석 지침 입력 영역
        new_instruction = st.text_area(
            "분석 지침 수정", 
            value=council_instruction, 
            height=150, 
            key="report_instr_area"
        )
        
        # 분석 지침 저장 버튼
        if st.button("💾 분석 지침 저장", use_container_width=True):
            data["council_prompt"] = new_instruction
            save_data(data)
            st.success("✅ 분석 지침이 성공적으로 저장되었습니다.")
            st.toast("지침 저장 완료")

        st.divider()

        # 보고서 생성 버튼
        if st.button("🚀 새 종합 AI 보고서 생성", type="primary", use_container_width=True):
            st.session_state.last_report_content = ""
            st.session_state.report_chat_history = []
            
            with st.spinner("과거 맥락 복기 및 최신 뉴스 통합 분석 중..."):
                # 1. [RAG] 과거 보고서 맥락 로드 (보존된 함수)
                historical_context = load_historical_contexts()

                # 2. [News] 뉴스 데이터 로드 (DB 수치 로직 제거)
                raw_news = load_pending_files("일주일") 
                target_date = datetime.now() - timedelta(days=analysis_range)
                
                # 설정된 범위 내의 뉴스만 필터링
                recent_news = [n for n in raw_news if n['pub_dt'] >= target_date]
                news_limit = data.get("report_news_count", 50)
                
                # AI에게 날짜, 출처, 제목 전달
                news_items = []
                for n in recent_news[:news_limit]:
                    time_str = n['pub_dt'].strftime("%m/%d %H:%M")
                    source = n.get('source', '뉴스')
                    news_items.append(f"[{time_str}][{source}] {n['title']}")
                
                news_context = "### [ 최신 주요 뉴스 리스트 ]\n" + "\n".join(news_items)

                if not news_items:
                    st.warning("📡 분석 범위 내에 최신 뉴스가 없습니다.")
                else:
                    # 🎯 프롬프트 재구성: DB 수치 대신 텍스트 맥락에 집중
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    full_instruction = (
                        f"현재 분석 시점: {now_str}\n"
                        f"당신은 {new_instruction}\n\n"
                        f"{historical_context}\n"
                        f"지침: 위의 과거 전략 맥락을 참고하여, 아래 나열된 최신 뉴스가 시장에 미칠 영향을 분석하고 대응 전략을 수립하십시오."
                    )

                    # 심층 분석 모델(analyst role) 호출
                    report = get_ai_summary(
                        title=f"{date.today()} 종합 전략 보고서", 
                        content=news_context, 
                        system_instruction=full_instruction,
                        role="analyst"
                    )
                    
                    st.session_state.last_report_content = report   
                    save_report_to_file(report, "daily")
                    st.rerun()

    # 3. 결과 출력 및 대화창
    if st.session_state.last_report_content:
        st.markdown("---")
        st.markdown(f"#### 📊 투자 보고서")
        
        with st.container(border=True):
            st.markdown(st.session_state.last_report_content)

        # 💬 질의응답 내역 표시
        if st.session_state.report_chat_history:
            st.markdown("#### 💬 질의응답 내역")
            for message in st.session_state.report_chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        # ✉️ 채팅 입력 (DB 지표 주입 로직 제거)
        if chat_input := st.chat_input("보고서 내용에 대해 궁금한 점을 질문하세요."):
            now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            st.session_state.report_chat_history.append({"role": "user", "content": chat_input})
            
            # 💡 [프롬프트] 보고서 텍스트 맥락 위주로 답변 유도
            chat_context = (
                f"당신은 이 보고서를 작성한 전문 투자 애널리스트입니다.\n"
                f"현재 시각: {now_time}\n\n"
                f"📝 [작성된 보고서 내용]\n{st.session_state.last_report_content}\n\n"
                f"지침: 사용자가 위 보고서 내용에 대해 질문하고 있습니다. 보고서의 맥락을 유지하며 전문적으로 답변하십시오."
            )
            
            response = get_ai_summary(title="보고서 내용 질의", content=chat_input, system_instruction=chat_context, role="analyst")
            st.session_state.report_chat_history.append({"role": "assistant", "content": response})
            st.rerun()

    st.divider()
    st.caption("💾 최근 생성된 보고서는 /share/ai_analyst/reports 에 저장됩니다.")


