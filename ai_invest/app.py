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

def load_addon_config():
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, "r", encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def load_data():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {"feeds": [], "update_interval": 10}
# 기존 변수 선언 유지 
config = load_addon_config() 
data = load_data()

# LLM 관련 변수 (HA 옵션에서 가져오기) 
desktop_ip = data.get("desktop_ip")
llm_api_port = data.get("llm_api_port")
ai_model = data.get("ai_model")

# --- 2. 뉴스 처리 핵심 함수 ---
# --- [수정] load_data 함수: 초기 실행 시 기본값 보장 ---
def load_data():
    default_structure = {
        "feeds": [], 
        "update_interval": 10, 
        "desktop_ip": "192.168.1.2",
        "llm_api_port": "1234",
        "ai_model": "openai/gpt-oss-20b",
        "ai_prompt": "당신은 전문 금융 분석가입니다...",
        "retention_days": 7
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                for key, value in default_structure.items():
                    if key not in loaded_data: loaded_data[key] = value
                return loaded_data
        except: pass
    return default_structure

def save_data(data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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

def get_ai_summary(title, content, system_instruction=None):
    # 전역 변수가 아닌 실시간 data 값을 사용하여 '저장' 즉시 반영되게 함
    target_ip = data.get("desktop_ip")
    target_port = data.get("llm_api_port")
    target_model = data.get("ai_model")
    
    url = f"http://{target_ip}:{target_port}/v1/chat/completions"
    
    if system_instruction:
        final_role = system_instruction
    else:
        final_role = data.get("ai_prompt", "전문 투자 분석가입니다.")

    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": final_role},
            {"role": "user", "content": f"제목: {title}\n본문: {content}"}
        ],
        "temperature": 0.3
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"❌ AI 서버 연결 실패 ({target_ip}:{target_port}): {str(e)}"
    
@st.dialog("📊 AI 정밀 분석 리포트")
def show_analysis_dialog(title, summary_text):
    # 창이 열리자마자 바로 분석 시작
    with st.spinner("AI가 뉴스를 분석 중입니다..."):
        # 기존 변수명 config, data를 사용하여 AI 호출
        # 설정(data)에 저장된 ai_prompt를 시스템 프롬프트로 사용
        analysis = get_ai_summary(title, summary_text)
    
    st.markdown(f"### {title}")
    st.divider()
    st.markdown(analysis)
    st.divider()
    
    # 하단에 원문 요약본 참고용으로 배치
    with st.expander("기사 원문 요약 보기"):
        st.write(summary_text)
    st.caption(f"🤖 모델: {config.get('ai_model')} | 분석 주관: AI Analyst")

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
    # 보고서 저장용 폴더 생성
    report_dir = "/share/ai_analyst/reports"
    os.makedirs(report_dir, exist_ok=True)
    
    # 파일명 생성: 2026-01-31_2330_종합분석.txt
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"{timestamp}_{section_name.replace(' ', '_')}.txt"
    filepath = os.path.join(report_dir, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath
    
# --- 3. UI 및 CSS 설정 ---
st.set_page_config(page_title="AI Analyst", layout="wide")

st.markdown("""
    <style>
    [data-testid="stPopoverBody"] { width: 170px !important; padding: 10px !important; }
    [data-testid="stPopoverBody"] button { padding: 2px 5px !important; margin-bottom: 2px !important; height: auto !important; font-size: 14px !important; }
    [data-testid="stSidebar"] { display: none; }
    [data-testid="stMetricValue"] { font-size: 28px !important; }
    </style>
    """, unsafe_allow_html=True)

data = load_data()
if 'active_menu' not in st.session_state: st.session_state.active_menu = "뉴스"
if 'current_feed_idx' not in st.session_state: st.session_state.current_feed_idx = "all"
if 'page_number' not in st.session_state: st.session_state.page_number = 1

# --- 4. 최상단 대메뉴 ---
st.title("🤖 AI Analyst System")
m_cols = st.columns(3)
menu_items = [("📡 뉴스 스트리밍", "뉴스"), ("🏛️ AI 투자 보고서", "AI"), ("⚙️ 설정", "설정")]

for i, (label, m_key) in enumerate(menu_items):
    if m_cols[i].button(label, use_container_width=True, type="primary" if st.session_state.active_menu == m_key else "secondary"):
        st.session_state.active_menu = m_key; st.rerun()

st.divider()

# --- 5. 메뉴별 본문 화면 구성 ---

if st.session_state.active_menu == "설정":
    st.subheader("⚙️ 시스템 및 AI 서버 설정")
    st.info("💡 보안이 필요한 AI 서버 및 DB 설정은 Home Assistant 애드온 구성 탭에서 수정하세요.")
    
# AI 서버 설정 섹션 추가
    with st.expander("🤖 로컬 AI 서버 설정", expanded=True):
        col_ip, col_port = st.columns([0.7, 0.3])
        new_ip = col_ip.text_input("데스크탑 IP 주소", value=data.get("desktop_ip", desktop_ip))
        new_port = col_port.text_input("LLM API 포트", value=data.get("llm_api_port", llm_api_port))
        new_model = st.text_input("사용할 AI 모델명", value=data.get("ai_model", ai_model))        
        
        if st.button("🚀 AI 서버 설정 저장", use_container_width=True):
            data.update({
                "desktop_ip": new_ip,
                "llm_api_port": new_port,
                "ai_model": new_model
            })
            save_data(data)
            st.success("✅ AI 서버 접속 정보가 저장되었습니다.")
            st.toast("AI 설정 반영 완료")

    st.write("") # 간격 조절
    
   
# --- 2. 뉴스 스트리밍 설정 섹션 ---
    with st.container(border=True):
        st.markdown("#### 📡 뉴스 스트리밍 설정")
        
        # AI 분석 프롬프트
        default_prompt = "전문 투자 분석가입니다. 뉴스의 핵심 포인트 3가지를 분석하세요."
        new_prompt = st.text_area(
            "AI 분석 시스템 지침 (System Prompt)", 
            value=data.get("ai_prompt", default_prompt),
            height=150
        )
        
        col_ret, col_int = st.columns(2)
        new_retention = col_ret.slider("뉴스 파일 보관 기간 (일)", 1, 30, data.get("retention_days", 7))
        new_interval = col_int.number_input("RSS 수집 주기 (분)", 1, value=data.get("update_interval", 10))
        
        if st.button("💾 뉴스 스트리밍 설정 저장", use_container_width=True, type="primary"):
            data.update({
                "ai_prompt": new_prompt,
                "retention_days": new_retention,
                "update_interval": new_interval
            })
            save_data(data)
            st.success("✅ 뉴스 수집 및 프롬프트 설정이 저장되었습니다.")
            st.toast("뉴스 설정 반영 완료")

    st.write("") # 간격 조절

    # --- 3. 투자 보고서 설정 섹션 ---
    with st.container(border=True):
        st.markdown("#### 📑 AI 투자 보고서 설정")
        report_days = st.number_input(
            "분석 데이터 범위 (일 단위)", 
            min_value=1, 
            max_value=data.get("retention_days", 30), 
            value=data.get("report_days", 3)
        )

        if st.button("📊 보고서 설정 저장", use_container_width=True):
            data["report_days"] = report_days
            save_data(data)
            st.success("✅ 투자 보고서 범위 설정이 저장되었습니다.")

    # --- 4. InfluxDB 정보 (읽기 전용) ---
    with st.expander("ℹ️ 데이터베이스(InfluxDB) 연결 정보"):
        st.info("데이터베이스 보안 설정은 HA 애드온의 '구성(Configuration)' 탭에서만 수정 가능합니다.")
        st.code(f"URL: {config.get('influx_url')}\nOrg: home_assistant\nBucket: financial_data")
        


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
                        show_analysis_dialog(entry.get('title'), cleaned_summary)

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

# [3. AI 투자 보고서]
elif st.session_state.active_menu == "AI":
    st.subheader("📑 AI 투자 보고서")
    
    # 1. 세션 및 경로 설정
    if "report_chat_history" not in st.session_state:
        st.session_state.report_chat_history = []
    if "last_report_content" not in st.session_state:
        st.session_state.last_report_content = ""

    REPORT_DIR = "/share/ai_analyst/reports"
    os.makedirs(REPORT_DIR, exist_ok=True)

    # [신규 로직] 세션에 보고서가 없으면 저장된 파일 중 가장 최신 것 로드
    if not st.session_state.last_report_content:
        report_files = sorted([f for f in os.listdir(REPORT_DIR) if f.startswith("Report_")], reverse=True)
        if report_files:
            latest_file = report_files[0]
            try:
                with open(os.path.join(REPORT_DIR, latest_file), "r", encoding="utf-8") as f:
                    st.session_state.last_report_content = f.read()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO] 기존 보고서 자동 로드: {latest_file}")
            except Exception as e:
                print(f"[ERROR] 파일 로드 실패: {e}")

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
        
        # [추가] 분석 지침 저장 버튼
        if st.button("💾 분석 지침 저장", use_container_width=True):
            data["council_prompt"] = new_instruction
            save_data(data) # 지침을 rss_config.json에 즉시 반영
            st.success("✅ 분석 지침이 성공적으로 저장되었습니다.")
            st.toast("지침 저장 완료")

        st.divider() # 시각적 구분선 추가

        # 보고서 생성 버튼 (기존 로직 유지)
        if st.button("🚀 새 종합 AI 보고서 생성", type="primary", use_container_width=True):
            # 새 보고서 작성 시작 시 기존 데이터 초기화
            st.session_state.last_report_content = ""
            st.session_state.report_chat_history = []
            
            with st.spinner("데이터 통합 분석 및 새 보고서 작성 중..."):
                # [RAG] 전날 보고서 로드 (어제 날짜 파일 검색)
                yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
                yesterday_path = os.path.join(REPORT_DIR, f"Report_{yesterday_str}.txt")
                yesterday_context = ""
                if os.path.exists(yesterday_path):
                    with open(yesterday_path, "r", encoding="utf-8") as f:
                        yesterday_context = f.read()
                
                # [Metrics] InfluxDB 데이터 로드
                metric_context = ""
                try:
                    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
                    query_api = client.query_api()
                    m_query = f'from(bucket: "{INFLUX_BUCKET}") |> range(start: -24h) |> filter(fn: (r) => r._measurement == "financial_metrics" and r._field == "price") |> last()'
                    tables = query_api.query(m_query)
                    metrics = [f"- {r['symbol']}: {r.get_value():,.2f}" for t in tables for r in t.records]
                    metric_context = "\n".join(metrics)
                except: pass

                # [News] 뉴스 데이터 로드
                raw_news = load_pending_files("일주일") 
                target_date = datetime.now() - timedelta(days=analysis_range)
                recent_news = [n for n in raw_news if n['pub_dt'] >= target_date]
                news_context = "\n".join([f"- {n['title']}" for n in recent_news[:30]])

                if not news_context:
                    st.warning("📡 분석할 뉴스가 없습니다.")
                else:
                    # 프롬프트 구성
                    full_instruction = f"{new_instruction}\n\n### [참조 데이터]\n"
                    if yesterday_context: full_instruction += f"\n- 전날 분석 맥락 포함됨"
                    if metric_context: full_instruction += f"\n- 실시간 지표:\n{metric_context}"

                    # 보고서 생성
                    report = get_ai_summary(title=f"{date.today()} 종합 전략", content=news_context, system_instruction=full_instruction)
                    st.session_state.last_report_content = report
                    
                    # 저장 및 정리
                    today_str = date.today().strftime("%Y-%m-%d")
                    with open(os.path.join(REPORT_DIR, f"Report_{today_str}.txt"), "w", encoding="utf-8") as f:
                        f.write(report)
                    
                    # 7일 경과 삭제
                    current_time = time.time()
                    for f in os.listdir(REPORT_DIR):
                        f_p = os.path.join(REPORT_DIR, f)
                        if os.path.isfile(f_p) and (current_time - os.path.getmtime(f_p) > 7 * 86400):
                            os.remove(f_p)
                    
                    st.rerun()

    # 3. 결과 출력 및 대화창
    if st.session_state.last_report_content:
        st.markdown("---")
        st.markdown("#### 📊 투자 보고서")
        with st.container(border=True):
            st.markdown(st.session_state.last_report_content)

        # 채팅 섹션
        if st.session_state.report_chat_history:
            st.markdown("#### 💬 질의응답 내역")
            for message in st.session_state.report_chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        if chat_input := st.chat_input("보고서 내용에 대해 질문하세요."):
            st.session_state.report_chat_history.append({"role": "user", "content": chat_input})
            chat_context = f"당신은 이 보고서를 작성한 전문가입니다. 보고서 내용: {st.session_state.last_report_content}"
            response = get_ai_summary(title="추가 질문", content=chat_input, system_instruction=chat_context)
            st.session_state.report_chat_history.append({"role": "assistant", "content": response})
            st.rerun()

    st.divider()
    st.caption("💾 최근 7일간의 보고서가 보관됩니다.")