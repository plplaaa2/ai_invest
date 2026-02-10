import streamlit as st
import pandas as pd
from common import *
from fpdf import FPDF

# app.py 내의 is_filtered 함수를 이 내용으로 교체하세요.
def is_filtered(title, summary, g_inc, g_exc, l_inc="", l_exc=""):
    """제목(Title)만을 기준으로 전역/개별 필터를 적용합니다."""
    # 🎯 1. 대소문자 무시 및 공백 정리 
    text = title.lower().strip()
    
    # 🎯 2. 제외 필터 (Exclude): 제목에 단 하나라도 포함되면 즉시 탈락 
    exclude_str = f"{g_exc},{l_exc}"
    exc_tags = [t.strip().lower() for t in exclude_str.split(",") if t.strip()]
    if any(t in text for t in exc_tags): 
        return False
    
    # 🎯 3. 전역 포함어 (Global Include): 설정된 경우, 제목에 반드시 있어야 통과 
    g_inc_tags = [t.strip().lower() for t in g_inc.split(",") if t.strip()]
    if g_inc_tags and not any(t in text for t in g_inc_tags):
        return False
        
    # 🎯 4. 개별(피드) 포함어 (Local Include): 설정된 경우, 제목에 반드시 있어야 통과 
    l_inc_tags = [t.strip().lower() for t in l_inc.split(",") if t.strip()]
    if l_inc_tags and not any(t in text for t in l_inc_tags):
        return False
    
    return True # 모든 검사를 통과함

def get_ai_summary(title, content, system_instruction=None, role="filter"):
    """뉴스 판독 또는 요약을 위해 AI 모델을 호출합니다."""
    now_time = get_now_kst().strftime('%Y-%m-%d %H:%M:%S')
    
    # 🎯 1. 설정 및 모델 정보 로드
    cfg = data.get("filter_model") if role == "filter" else data.get("analyst_model")
    base_url = cfg.get("url", "").rstrip('/')
    model_name = cfg.get("name")
    
    # 지침 설정
    user_prompt = system_instruction if system_instruction else cfg.get("prompt", "")
    final_role = f"현재 시각: {now_time}\n분석 지침: {user_prompt}"

    # 🎯 2. [수정 포인트] 클라우드(Google 직접 호출) 여부 판별
    # 모델명에 gemini가 있더라도, URL이 구글 주소일 때만 '진짜 클라우드'로 판정합니다.
    is_direct_google = "generativelanguage.googleapis.com" in base_url
    
    # API 키 선택 로직 강화
    if is_direct_google:
        # 구글 공식 서비스는 무조건 gemini_api_key 사용
        api_key = config.get("gemini_api_key", "")
    else:
        # 그 외(로컬/OpenAI 등)는 설정된 개별 키 -> OpenAI 키 순으로 시도
        api_key = cfg.get("key") if cfg.get("key") else config.get("openai_api_key", "")

    # 🎯 3. 호출 방식 분기 (URL 구조 기반)
    if is_direct_google:
        # 🌐 [Case A] 구글 서버 직접 호출 방식 (Gemini API 규격)
        url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": f"시스템 지침: {final_role}\n\n사용자 입력:\n제목: {title}\n본문: {content}"}]
            }],
            "generationConfig": {"temperature": cfg.get("temperature", 0.3)}
        }
    else:
        # 🏠 [Case B] 로컬 서버(Ollama/Open WebUI) 또는 OpenAI 방식 (Chat Completion 규격)
        # 이제 gemini-3-flash-preview:cloud 모델도 주소가 로컬이면 이 로직을 탑니다.
        url = f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": final_role},
                {"role": "user", "content": f"제목: {title}\n본문: {content}"}
            ],
            "temperature": cfg.get("temperature", 0.3)
        }

    try:
        # 🎯 4. 요청 전송 (타임아웃 10분)
        resp = requests.post(url, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        result = resp.json()

        # 🎯 5. 응답 구조 판별 및 추출
        # 구글 직접 호출인 경우 'candidates' 구조를 가집니다.
        if "candidates" in result:
            return result['candidates'][0]['content']['parts'][0]['text']
        # 로컬 서버/OpenAI인 경우 'choices' 구조를 가집니다.
        else:
            return result['choices'][0]['message']['content']

    except requests.exceptions.Timeout:
        return "❌ [TIMEOUT] AI 분석 시간이 10분을 초과했습니다."
    except Exception as e:
        print(f"[{now_time}] AI 분석 에러: {str(e)}")
        return f"❌ [ERROR] AI 분석 중 예외 발생: {str(e)}"
        
@st.dialog("📊 AI 정밀 분석 리포트")
def show_analysis_dialog(title, summary_text, pub_dt, role="filter"): 
    with st.spinner("AI가 뉴스를 심층 분석 중입니다..."):
        enhanced_title = f"(기사작성일: {pub_dt}) {title}"
        # 여기서 방금 수정한 get_ai_summary가 호출되면서 
        # Add-on 설정의 키를 찾아 Gemini를 태울 것입니다.
        analysis = get_ai_summary(enhanced_title, summary_text, role=role)
    
    st.markdown(f"### {title}")
    st.caption(f"📅 기사 작성일: {pub_dt}") 
    st.divider()
    
    st.markdown(analysis)
    st.divider()
    
    with st.expander("기사 원문 요약 보기"):
        st.write(summary_text)

    # 🎯 [보완 포인트] 모델 정보 표시 로직 최적화
    cfg = data.get("filter_model" if role == "filter" else "analyst_model", {})
    display_model = cfg.get("name", "Unknown Model")
    
    # 💡 UI 설정(cfg)이나 Add-on 설정(config) 중 하나라도 키가 있으면 클라우드로 표시
    has_openai = cfg.get("key") or config.get("openai_api_key")
    has_gemini = cfg.get("key") or config.get("gemini_api_key")

    if has_gemini and "gemini" in display_model.lower():
        display_model = f"✨ Gemini ({display_model})"
    elif has_openai and "gpt" in display_model.lower():
        display_model = f"🌐 OpenAI ({display_model})"
    else:
        # 키가 없거나 모델명이 일치하지 않으면 로컬로 표시
        display_model = f"🏠 Local ({display_model})"

    analysis_time = get_now_kst().strftime('%H:%M:%S')
    
    st.caption(
        f"🤖 사용 모델: {display_model} | "
        f"🕒 분석 시각: {analysis_time} | "
        f"📊 분석 모드: {'단기 판독' if role == 'filter' else '심층 전략'}"
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

def load_pending_files(range_type, target_feed=None):
    """
    단계별 로그를 통해 원인을 파악하는 뉴스 로더
    """
    news_list = []
    if not os.path.exists(PENDING_PATH):
        st.error(f"❌ 경로 미존재: {PENDING_PATH}")
        return news_list
        
    # 🔍 로그 1: 물리적 파일 검색
    all_files = os.listdir(PENDING_PATH)
    target_files = [f for f in all_files if f.endswith(".json") or f.endswith(".txt")]
    print(f"🔍 [STEP 1] 전체 파일: {len(all_files)}개 | 대상 확장자: {len(target_files)}개")

    now_kst = get_now_kst()
    today_date = now_kst.date()
    # 시간대 정보 제거(naive) 버전 준비 (비교용)
    one_week_ago = (now_kst - timedelta(days=7)).replace(tzinfo=None)
    
    parse_fail = 0
    filter_fail = 0

    for filename in target_files:
        fpath = os.path.join(PENDING_PATH, filename)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                if filename.endswith(".json"):
                    data = json.load(f)
                    title = data.get('title', '제목 없음')
                    pub_str = data.get('pub_dt', '')
                    
                    # 🎯 날짜 파싱 강화 (pub_dt_str 형식: %Y-%m-%d %H:%M:%S)
                    try:
                        pub_dt = datetime.strptime(pub_str, '%Y-%m-%d %H:%M:%S')
                    except:
                        # 파싱 실패 시 파일 수정 시간으로 강제 복구
                        pub_dt = datetime.fromtimestamp(os.path.getmtime(fpath))
                    
                    link = data.get('link', '')
                    summary = data.get('summary', '')
                    source = data.get('source', '저장된 데이터')
                else:
                    lines = f.read().splitlines()
                    if len(lines) < 3: continue
                    title = lines[0].replace("제목: ", "")
                    pub_str = lines[2].replace("날짜: ", "")
                    pub_dt = parse_rss_date(pub_str)
                    link = lines[1].replace("링크: ", "")
                    summary = "\n".join(lines[3:]).replace("요약: ", "")
                    source = "저장된 데이터"

                # 🔍 로그 2: 필터링 전 데이터 확보 확인
                # 시간대 정보가 섞여 비교 에러가 나는 것을 방지
                pub_dt_naive = pub_dt.replace(tzinfo=None) if pub_dt.tzinfo else pub_dt
                
                # 필터링 로직
                if range_type == "오늘" and pub_dt_naive.date() != today_date:
                    filter_fail += 1
                    continue
                if range_type == "일주일" and pub_dt_naive < one_week_ago:
                    filter_fail += 1
                    continue
                
                if target_feed:
                    if not check_filters(title, target_feed.get('include', ""), target_feed.get('exclude', "")):
                        filter_fail += 1
                        continue
                
                news_list.append({
                    "title": title, "link": link, "published": pub_str, 
                    "summary": summary, "pub_dt": pub_dt_naive, "source": source
                })

        except Exception as e:
            parse_fail += 1
            print(f"❌ [에러] {filename} 로드 실패: {e}")
            continue
            
    # 🔍 로그 3: 최종 결과 집계
    print(f"✅ [STEP 2] 최종 로드: {len(news_list)}개 | 파싱실패: {parse_fail} | 기간/필터제외: {filter_fail}")
    
    news_list.sort(key=lambda x: x['pub_dt'], reverse=True)
    return news_list

def save_data(data):
    """변경된 설정 데이터를 JSON 파일로 안전하게 저장합니다."""
    # 폴더가 없으면 자동으로 생성합니다.
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    
    # 파일을 열어 딕셔너리 데이터를 기록합니다.
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        # 한글 깨짐 방지 및 가독성을 위해 옵션을 추가합니다.
        json.dump(data, f, ensure_ascii=False, indent=2)


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


if 'active_menu' not in st.session_state: st.session_state.active_menu = "뉴스"
if 'current_feed_idx' not in st.session_state: st.session_state.current_feed_idx = "all"
if 'page_number' not in st.session_state: st.session_state.page_number = 1

# --- 4. 최상단 대메뉴 ---
st.title("🤖 AI Analyst System")
m_cols = st.columns(3)
menu_items = [("📡 뉴스 스트리밍", "뉴스"), ("🏛️ AI 투자 보고서", "AI"), ("⚙️ 설정", "설정")]

for i, (label, m_key) in enumerate(menu_items):
    if m_cols[i].button(label, width='stretch', type="primary" if st.session_state.active_menu == m_key else "secondary"):
        st.session_state.active_menu = m_key; st.rerun()

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
        
        if st.button("💾 판독 모델 설정 저장", width='stretch'):
            data["filter_model"].update({"url": f_url, "name": f_name, "prompt": f_prompt})
            save_data(data); st.success("✅ 판독 모델 설정 저장 완료!")

    with tab_a:
        st.markdown("#### 🏛️ 투자 보고서 생성용 모델")
        a_cfg = data.get("analyst_model")
        # 고유 키: a_url_input
        a_url = st.text_input("API 서버 주소 (URL)", value=a_cfg.get("url"), help="예: http://192.168.1.105:11434/v1", key="a_url_input")
        a_name = st.text_input("모델명", value=a_cfg.get("name"), key="a_name_input")
        
        if st.button("💾 분석 모델 설정 저장", width='stretch'):
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
        # 2. 자동 생성 및 시간 설정 (stock_collector.py에서 이 값을 읽어 정시 가동)
        col_auto, col_time = st.columns([0.4, 0.6])
        auto_gen = col_auto.toggle("매일 보고서 자동 생성", value=data.get("report_auto_gen", False), key="cfg_report_auto_gen")
        gen_time = col_time.text_input("생성 시간 (24시간제, 예: 08:00)", value=data.get("report_gen_time", "08:00"), key="cfg_report_gen_time")
        
        # 3. 분석 뉴스 개수 설정 (최대 500개 확장 반영)
        report_news_count = st.slider("분석 포함 뉴스 개수 (최대 500개)", 10, 500, value=data.get("report_news_count", 100), key="cfg_report_news_count")

        if st.button("💾 모든 시스템 설정 저장", width='stretch', type="primary"):
            # 🎯 [데이터 구조 동기화]
            data.update({
                "retention_days": new_retention,
                "update_interval": new_interval,
                "report_auto_gen": auto_gen,
                "report_gen_time": gen_time,
                "report_news_count": report_news_count
            })
            
            # 💡 수집기 혼선을 방지하기 위해 구형 설정 제거
            if "report_days" in data:
                del data["report_days"]
                
            save_data(data)
            st.success("✅ 시스템 설정이 저장되었습니다. 뉴스 처리량이 500개로 확장되었습니다.")
            st.rerun()

    st.write("") # 간격 조절
        

# [2. 뉴스 스트리밍]
if st.session_state.active_menu == "뉴스":    
    # 🎯 1. 사이드바 상태 관리 세션 초기화
    if 'show_rss_sidebar' not in st.session_state:
        st.session_state.show_rss_sidebar = False # 기본으로 닫아두어 광폭 화면 확보

    # 🎯 2. 최상단 컨트롤 바
    t_col1, t_col2 = st.columns([0.8, 0.2])

    try:
        if st.session_state.current_feed_idx == "all":
            current_f_name = "🏠 전체 뉴스"
        else:
            # 인덱스를 정수로 변환하여 리스트 범위 체크
            idx = int(st.session_state.current_feed_idx)
            feeds = data.get('feeds', [])
            if 0 <= idx < len(feeds):
                current_f_name = feeds[idx]['name']
            else:
                # 범위를 벗어나면 안전하게 '전체'로 복구
                st.session_state.current_feed_idx = "all"
                current_f_name = "🏠 전체 뉴스"
    except (ValueError, IndexError, TypeError):
        # 숫자가 아니거나 값이 없을 경우 '전체'로 복구
        st.session_state.current_feed_idx = "all"
        current_f_name = "🏠 전체 뉴스"
    # ---------------------------------------
    t_col1.subheader(f"📡 {current_f_name}")
    
    # 버튼을 우측 끝에 배치하여 사이드바 열기 유도
    btn_text = "📂 RSS 닫기" if st.session_state.show_rss_sidebar else "📂 RSS 관리"
    if t_col2.button(btn_text, width='stretch', type="secondary"):
        st.session_state.show_rss_sidebar = not st.session_state.show_rss_sidebar
        st.rerun()

# 🎯 3. 동적 컬럼 배치 (우측 사이드바 체제)
    # 본문(Main)을 먼저 배치하고, 사이드바(Side)를 뒤에 배치합니다.
    if st.session_state.show_rss_sidebar:
        col_main, col_side = st.columns([0.75, 0.25]) 
    else:
        col_main, col_side = st.columns([0.999, 0.001])

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
            items_per_page = 10
            total_pages = math.ceil(len(full_list) / items_per_page)
            start_idx = (st.session_state.page_number - 1) * items_per_page
            
            for entry in full_list[start_idx : start_idx + items_per_page]:
                with st.container(border=True):
                    st.caption(f"📍 {entry.get('source')} | {entry.get('published', '')}")
                    st.markdown(f"#### {entry.get('title')}")
                    
                    cleaned_summary = clean_html(entry.get('summary', ''))
                    st.write(cleaned_summary[:200] + "...")
                    
                    btn_c1, btn_c2 = st.columns([0.2, 0.8])
                    btn_c1.link_button("🌐 원문", entry.get('link', '#'), width='stretch')
                    if btn_c2.button("🤖 AI 요약", key=f"ai_{entry.get('link')}", width='stretch'):
                        show_analysis_dialog(entry.get('title'), cleaned_summary, entry.get('published', '날짜 미상'), role="filter")

            # 페이지네이션 로직 (기존과 동일하되 띄어쓰기 정돈)
            st.write("")
            
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
                        width='stretch'
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
    
# --- 사이드바 (RSS 관리) 구역 (오른쪽) ---
    with col_side:
        if st.session_state.show_rss_sidebar:
            st.markdown("### 📌 RSS 관리")
            
            # 전체 보기 버튼
            is_all = st.session_state.current_feed_idx == "all"
            if st.button("🏠 전체 보기", width='stretch', type="primary" if is_all else "secondary"):
                st.session_state.current_feed_idx = "all"
                st.session_state.page_number = 1
                st.rerun()
            
            st.write("")
            
# 피드 리스트 반복문 (기존 로직 유지하며 띄어쓰기 정돈)
            for i, f in enumerate(data.get('feeds', [])):
                is_active = st.session_state.current_feed_idx == i
# 8:2 비율로 가로 컬럼 생성
                btn_col, opt_col = st.columns([0.82, 0.18], gap="small")
                


            # 1. 메인 피드 선택 버튼
                with btn_col:
                    if st.button(
                        f"📡 {f['name']}", 
                        key=f"f_{i}", 
                        width='stretch', 
                        type="primary" if is_active else "secondary"
                    ):
                        st.session_state.current_feed_idx = i
                        st.session_state.page_number = 1
                        st.rerun()
                        
                    # A. 편집 버튼
                with opt_col:
                    with st.popover("", width='stretch'):
                        col_ed, col_fi, col_de = st.columns(3)
                        if col_ed.button("편집", key=f"ed_{i}", width='stretch'):
                            @st.dialog("피드 수정", width="small")
                            def ed_diag(idx=i):
                                fe = data['feeds'][idx]
                                n = st.text_input("이름", value=fe['name'])
                                u = st.text_input("URL", value=fe['url'])
                                if st.button("저장"):
                                    data['feeds'][idx].update({"name": n, "url": u})
                                    save_data(data)
                                    st.rerun()
                            ed_diag()
                    
                        # B. 필터 버튼
                        if col_fi.button("필터", key=f"fi_{i}", width='stretch'):
                            @st.dialog("키워드 필터", width="small")
                            def fi_diag(idx=i):
                                fe = data['feeds'][idx]
                                inc = st.text_area("포함 키워드", value=fe.get('include', ""))
                                exc = st.text_area("제외 키워드", value=fe.get('exclude', ""))
                                if st.button("필터 적용"):
                                    data['feeds'][idx].update({"include": inc, "exclude": exc})
                                    save_data(data)
                                    st.rerun()
                            fi_diag()
                        
                        # C. 삭제 버튼
                        if col_de.button("삭제", key=f"de_{i}", width='stretch'):
                            data['feeds'].pop(i)
                            save_data(data)
                            st.rerun()
                
                    # 피드 아이템 간의 시각적 간격 추가
                    st.write("")
            
            st.divider()
            
            # 피드 추가 버튼
            if st.button("➕ 새 RSS 추가", width='stretch'):
                @st.dialog("새 RSS 등록")
                def add_diag():
                    n = st.text_input("피드 이름 (예: 연합뉴스)")
                    u = st.text_input("RSS URL 주소")
                    if st.button("등록 완료"):
                        data['feeds'].append({"name": n, "url": u, "include": "", "exclude": ""})
                        save_data(data); st.rerun()
                add_diag()

            # 전역 필터 설정 구역 (사이드바 안에 포함)
            with st.expander("🌐 전역 필터 설정", expanded=False):
                g_inc = st.text_area("전역 포함 키워드", value=data.get("global_include", ""), help="쉼표(,)로 구분")
                g_exc = st.text_area("전역 제외 키워드", value=data.get("global_exclude", ""), help="쉼표(,)로 구분")
                if st.button("전역 필터 저장", width='stretch'):
                    data.update({"global_include": g_inc, "global_exclude": g_exc})
                    save_data(data); st.toast("전역 필터가 저장되었습니다!")
        else:
            # 🎯 사이드바가 숨겨졌을 때는 아주 얇은 공간만 유지하거나 비워둡니다.
            st.empty()

# [3. AI 투자 보고서]
elif st.session_state.active_menu == "AI":
    st.subheader("📑 AI 투자 사령부 보고서")
    
    # 1. 기초 설정 (기존 경로 및 세션 유지)    
    DIR_MAP = {'daily': '01_daily', 'weekly': '02_weekly', 'monthly': '03_monthly'}
    
    if "report_chat_history" not in st.session_state:
        st.session_state.report_chat_history = []
    if "last_report_content" not in st.session_state:
        st.session_state.last_report_content = ""

    # 🎯 탭 구성: 일간, 주간, 월간
    tabs = st.tabs(["📅 일간 보고서", "🗓️ 주간 보고서", "📊 월간 보고서"])
    r_types = ["daily", "weekly", "monthly"]
    r_days_map = {"daily": data.get("report_days", 1), "weekly": 7, "monthly": 30}

    # 탭별 루프 시작
    for i, tab in enumerate(tabs):
        r_type = r_types[i]
        r_days = r_days_map[r_type]
        
        # 사령관님 폴더 매칭
        target_dir = os.path.join(REPORT_DIR, DIR_MAP.get(r_type, "05_etc"))
        os.makedirs(target_dir, exist_ok=True)

        with tab:
            st.markdown(f"#### 🏛️ {r_type.upper()} 분석 컨트롤")
            
            # 📁 과거 기록 스캔 (latest.txt 제외)
            r_files = sorted([f for f in os.listdir(target_dir) if f.endswith(".txt") and f != "latest.txt"], reverse=True)
            
            c1, c2 = st.columns([0.8, 0.2])
            selected_f = c1.selectbox(f"기록실 ({r_type})", r_files, key=f"sel_{r_type}", label_visibility="collapsed")
            
            if c2.button("📖 로드", key=f"load_{r_type}", width='stretch', disabled=not r_files):
                with open(os.path.join(target_dir, selected_f), "r", encoding="utf-8") as f:
                    st.session_state.last_report_content = f.read()
                st.rerun()

            st.divider()

            # 🚀 보고서 생성 버튼
            if st.button(f"🚀 새 {r_type.upper()} 보고서 생성 ({r_days}일 분석)", type="primary", width='stretch', key=f"gen_{r_type}"):
                st.info(f"🔍 시스템 경로 확인 중...")
                abs_path = os.path.abspath(PENDING_PATH)
                st.write(f"📍 현재 PENDING_PATH (절대경로): `{abs_path}`")
                
                if os.path.exists(abs_path):
                    all_files = os.listdir(abs_path)
                    st.write(f"📁 폴더 내 전체 파일 개수: {len(all_files)}개")
                else:
                    st.error(f"❌ 경로가 존재하지 않습니다: {abs_path}")
                st.session_state.last_report_content = ""
                st.session_state.report_chat_history = []
                
                with st.spinner(f"AI 애널리스트가 {r_days}일치 데이터를 통합 분석 중..."):
                    # [A] 과거 맥락 로드
                    historical_context = load_historical_contexts()
                    extended_days = r_days + 2

# [C] 뉴스 데이터 로드 (r_days 적용)
                    raw_news = load_pending_files("일주일")
                    if not raw_news:
                        st.error(f"📍 파일 {len(os.listdir(PENDING_PATH))}개 중 유효한 형식이 없습니다.")
                        st.stop()
                    
                    now = datetime.now()
                    # 주말(토, 일)이나 월요일 아침에는 금요일(3일 전) 데이터까지 포함
                    lookback_days = 3 if now.weekday() in [5, 6, 0] else 2           
                    news_target_dt = now - timedelta(days=lookback_days)
                    
                    recent_news = [n for n in raw_news if n['pub_dt'].replace(tzinfo=None) >= news_target_dt]
                    recent_news.sort(key=lambda x: x['pub_dt'], reverse=True)                    
                   
                    news_limit = data.get("report_news_count", 100)
                    news_items = [f"[{n['pub_dt'].strftime('%m/%d %H:%M')}] {n['title']}" for n in recent_news]
                    
                    for n in recent_news[:news_limit]:
                        # HTML 태그 제거 및 가독성 최적화
                        title = n['title']
                        summary = clean_html(n.get('summary', ''))[:150]
                        time_str = n['pub_dt'].strftime('%Y-%m-%d %H:%M:%S')
    
                        news_items.append(f"[{time_str}] {title}\n   - 요약: {summary}")
                    
                    news_context = f"### [ 최근 주요 뉴스 데이터 ]\n" + "\n".join(news_items)

                    # [D] AI 보고서 생성 및 저장
                    council_instruction = data.get("council_prompt", "당신은 전문 금융 애널리스트입니다.")
                    
                    # 분석 지침 강화: 숫자의 우선순위를 명확히 함
                    analysis_guideline = (
                        "### [ 자료 분석 지침 ]\n" 
                        "1. 시장 상태 인지: 현재가 주말이면 가장 최근 거래일(금요일) 종가를 현재가로 간주한다.\n"
                        "2. 수치 절대 우선: 뉴스 제목의 톤보다 뉴스에 나온 등락 수치(+0.55% 등)를 최우선 팩트로 삼는다.\n"
                        "3. 추세와 반등 구분: 며칠간 하락했더라도 마지막 지표가 상승이면 '단기 반등 성공'으로 해석하라.\n"
                        "4. 연속성 원칙: '과거 분석 기록'에서 제시했던 주요 전망과 오늘 '원천 수급 지표'를 비교하여, 예측이 적중했는지 혹은 상황이 변했는지 반드시 언급하라.\n"
                        "5. 전략적 수정: 지표 변화에 따라 포트폴리오 비중이나 투자 행동 지침을 유연하게 업데이트하라.\n"
                    )
                    structure_instruction = (
                        "### [ 보고서 작성 형식 ]\n"
                        "각 항목은 아래의 구조를 반드시 엄수하여 작성하라:\n"
                        "1. 시황 브리핑: 현재 시장의 핵심 테마를 한 줄 요약 후 전체적인 분위기 기술\n"
                        "2. 주요 뉴스 및 오피니언: 제공된 뉴스 중 시장 영향력이 큰 발언이나 사건 인용\n"
                        "3. 거시경제 분석: 환율, 금리, 수급 지표를 바탕으로 한 매크로 환경 진단\n"
                        "4. 자산별 분석: 주식(국내/외), 채권, 가상자산, 원자재를 5점 척도로 평가\n"
                        "5. 산업별 분석: 반도체, 금융, 에너지 등 주요 섹터를 5점 척도로 평가\n"
                        "6. 주력/미래 산업 전망: 현재 주도주의 지속 가능성과 새롭게 부각되는 미래 먹거리 분석\n"
                        "7. 리스크 분석: 현재 시장의 최대 뇌관 및 잠재적 위험 요소 2~3가지 지적\n"
                        "8. 포트폴리오 및 전략: 구체적인 자산 배분 비중(%)과 사령관을 위한 투자 행동 지침 하달\n"
                        "9. 수치 기록: 다음 보고서에서 참고하게 뉴스에서 수집한 경제지표를 날짜와 함께 기록\n"
                    )
                    
                    # 프롬프트 구성: 지표(Fact)를 마지막에 배치하여 강조
                    full_instruction = (
                        f"당신은 {council_instruction}\n"
                        f"현재 시각: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"{analysis_guideline}\n\n"
                        f"--- [ 1. 과거 분석 기록 ] ---\n{historical_context}\n\n"
                        f"--- [ 2. 분석 대상 뉴스 데이터 ] ---\n{news_context}\n\n"
                        f"{structure_instruction}\n"
                        f"**주의: 반드시 위 뉴스 데이터에 명시된 수치와 사건을 바탕으로 보고서를 작성하라.**"
                    )
                    
                    # 실제 리포트 생성 (뉴스 본문은 content로 전달)
                    report = get_ai_summary(
                        title=f"{date.today()} {r_type.upper()} 보고서", 
                        content=news_context, 
                        system_instruction=full_instruction, 
                        role="analyst"
                    )
                    
                    save_report_to_file(report, r_type)
                    st.session_state.last_report_content = report
                    st.rerun()

    # 3. 결과 출력 및 대화창 (하단 공통)
    if st.session_state.last_report_content:
        st.divider()
        st.markdown("#### 📊 투자 전략 리포트 본문")
        with st.container(border=True):
            st.markdown(st.session_state.last_report_content)

        # 질의응답 내역
        for message in st.session_state.report_chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

# 실시간 채팅 입력
        if chat_input := st.chat_input("보고서 내용에 대해 질문하세요."):
            st.session_state.report_chat_history.append({"role": "user", "content": chat_input})
            
            # 1. 현재 시간 및 요일 정보 생성
            now = get_now_kst()
            days = ['월', '화', '수', '목', '금', '토', '일']
            current_time_info = f"{now.strftime('%Y-%m-%d %H:%M:%S')} ({days[now.weekday()]}요일)"
            
            # 2. 페르소나 및 시간 정보가 포함된 시스템 컨텍스트
            chat_context = (
                f"당신은 전문 금융 애널리스트입니다.\n"
                f"🕒 [현재 시각]: {current_time_info}\n"                
                f"📝 [보고서 본문]:\n{st.session_state.last_report_content}\n\n"
                f"질문에 답할 때 반드시 현재 시각(휴장 여부 등)을 고려하여 답변하세요."
            )
            
            response = get_ai_summary(title="질의", content=chat_input, system_instruction=chat_context, role="analyst")
            st.session_state.report_chat_history.append({"role": "assistant", "content": response})
            st.rerun()
# 🎯 1. 세션에서 보고서 본문 가져오기
    report_to_download = st.session_state.get('last_report_content', "아직 생성된 보고서가 없습니다.")

    def create_pdf_data(text):
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()
        
        # 🎯 폰트 등록 및 설정 (유니코드 대응)
        try:
            # run.sh에서 다운로드한 경로를 지정합니다.
            pdf.add_font("Nanum", "", "/app/fonts/NanumGothic.ttf")
            pdf.set_font("Nanum", size=14)
        except Exception as e:
            # 폰트 로드 실패 시 기본 폰트로 후퇴 (글자는 깨지겠지만 에러는 안 남)
            pdf.set_font("helvetica", size=14)
            print(f"🚨 폰트 로드 실패: {e}")

        # 🎯 실제 보고서 본문 작성 (한글 그대로 주입)
        pdf.multi_cell(0, 10, text=text)
        
        return bytes(pdf.output())

    # --- 다운로드 버튼 부분 ---
    try:
        import datetime
        current_date_str = datetime.datetime.now().strftime('%Y%m%d')
        
        # 버튼을 누르면 위 함수가 실행되어 bytes 데이터를 반환합니다.
        st.download_button(
            label="📥 현재 보고서 PDF 다운로드",
            data=create_pdf_data(report_to_download),
            file_name=f"Report_{current_date_str}.pdf",
            mime="application/pdf",
            use_container_width=True
        )
    except Exception as e:
        st.error(f"🚨 다운로드 버튼 생성 실패: {e}")
        
    # 4. 분석 지침 설정 (하단 expander)
    with st.expander("⚙️ 분석 지침 수정"):
        council_instr = data.get("council_prompt", "")
        new_instr = st.text_area("지침 내용", value=council_instr, height=150)
        if st.button("💾 지침 저장", width='stretch'):
            data["council_prompt"] = new_instr
            save_data(data)
            st.success("저장 완료")











