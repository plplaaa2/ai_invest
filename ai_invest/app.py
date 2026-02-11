import streamlit as st
import pandas as pd
from common import *
from fpdf import FPDF
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.85 # 85% 이상 유사하면 중복으로 간주

def is_similar(a, b):
    """두 문자열의 유사도를 계산합니다. (공백/특수문자 무시)"""
    normalized_a = ''.join(filter(str.isalnum, a)).lower()
    normalized_b = ''.join(filter(str.isalnum, b)).lower()
    return SequenceMatcher(None, normalized_a, normalized_b).ratio()

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

def parse_rss_date(date_str):
    try:
        p = feedparser._parse_date(date_str)
        return datetime.fromtimestamp(time.mktime(p))
    except: return get_now_kst()

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

def render_metric_grid(symbols, grid_cols=4):
    """카테고리별 단위 포맷팅을 자동으로 적용하여 버튼 렌더링"""
    for i in range(0, len(symbols), grid_cols):
        row_syms = symbols[i : i + grid_cols]
        cols = st.columns(grid_cols)
        
        for j, sym in enumerate(row_syms):
            m, p_hist, _, _ = get_metric_data(sym)
            if not m or 'price' not in m: continue
            
            curr = m['price']
            prev = m.get('prev_close', p_hist[0] if p_hist else curr)
            diff = curr - prev
            diff_pct = (diff / prev * 100) if prev != 0 else 0
            icon = "🔺" if diff > 0 else "🔻" if diff < 0 else "─"
            
            # 🎯 [동적 단위 포맷팅 로직 통합]
            # 1. 환율 및 국내 금
            if "KRW" in sym or "KOR_GOLD" in sym: val_str = f"{curr:,.1f}원"
            # 2. 원자재 및 국제 금
            elif sym in ["WTI", "NAT_GAS", "COPPER", "US_GOLD"]: val_str = f"${curr:,.2f}"
            # 3. 달러 인덱스
            elif sym == "DXY": val_str = f"{curr:.2f}pt"
            # 4. 연준 자산 (T/B 단위)
            elif sym == "FED_ASSETS": val_str = f"${curr/1_000_000:.2f}T"
            elif sym in ["RRP", "RESERVES", "US_TGA", "US_SRF", "BTFP", "US_M2"]: val_str = f"${curr/1_000:.1f}B"
            # 5. 수급 (억 단위)
            elif sym in CAT_FUNDS: val_str = f"{curr:,.1f}억"
            # 6. 금리 및 물가/고용 (%)
            elif any(x in sym for x in ["RATE", "UNRATE", "INFL", "CPI", "PCE", "PPI", "SOFR", "EFFR", "Y"]):
                val_str = f"{curr:.2f}%"
            # 7. 기타 (지수 등)
            else: val_str = f"{curr:,.1f}"

            # 변동 표시 (수급은 억 단위 변동액 표시, 나머지는 % 표시)
            change_str = f"{diff:+,.1f}억" if sym in CAT_FUNDS else f"{diff_pct:+.2f}%"
            btn_label = f"{display_names.get(sym, sym)}\n\n{val_str}\n{icon} {change_str}"
            
            if cols[j].button(btn_label, key=f"btn_{sym}", width='stretch'):
                st.session_state.selected_chart = sym
                st.rerun()
                

    
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


if 'active_menu' not in st.session_state: st.session_state.active_menu = "시장"
if 'current_feed_idx' not in st.session_state: st.session_state.current_feed_idx = "all"
if 'page_number' not in st.session_state: st.session_state.page_number = 1

# --- 4. 최상단 대메뉴 ---
st.title("🤖 AI Analyst System")
m_cols = st.columns(4)
menu_items = [("📈 시장 지표", "시장"), ("📡 뉴스 스트리밍", "뉴스"), ("🏛️ AI 투자 보고서", "AI"), ("⚙️ 설정", "설정")]

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
        

elif st.session_state.active_menu == "시장":
    # 1. 초기 선택값 및 상태 설정
    if 'selected_chart' not in st.session_state:
        st.session_state.selected_chart = "KOSPI"


    try:
        # --- (상단) 지표 요약 탭: 클릭 시 연동 ---
        st.subheader("📊 주요 시장 지표 요약 (클릭 시 하단 차트 연동)")
        
        # 탭 구성 (5단 분리)
        t1, t2, t3, t4, t5 = st.tabs([
            "🏛️ 주요 지수", "🌍 환율/원자재", "🏦 금리/수급", "🏦 연준 유동성", "🛒 물가/고용"
        ])


        # 🏛️ [t1] 주요 지수 탭
        with t1:
            st.markdown("##### [ 🏛️ 주요 국내외 지수 및 선물 ]")
            render_metric_grid(CAT_INDICES, 4)



        # 🌍 [t2] 환율/원자재 탭
        with t2:
            st.markdown("##### [ 🌍 글로벌 환율 및 원자재 현황 ]")
            render_metric_grid(CAT_FX_CMD, 4)



        # 🏦 [t3] 금리/수급 탭
        with t3:
            st.markdown("##### [ 🏦 국채 금리 및 증시 수급 ]")
            render_metric_grid(CAT_RATES, len(CAT_RATES)) # 금리는 한 줄 배치
            st.write("")
            render_metric_grid(CAT_FUNDS, len(CAT_FUNDS)) # 수급도 한 줄 배치     

        # 🏛️ [t4] 연준 유동성 탭
        with t4:
            st.markdown("##### [ 🏛️ 연준 유동성 및 자금 시장 ]")
            render_metric_grid(CAT_MACRO_1, 5)


        # 🛒 [t5] 물가/고용 탭
        with t5:
            st.markdown("##### [ 🛒 물가 및 고용 경제 지표 ]")
            render_metric_grid(CAT_MACRO_2, 4)

        st.divider()


        # --- (하단) 상세 차트 대시보드 섹션 ---
        target = st.session_state.selected_chart
        st.subheader(f"📈 {display_names.get(target, target)} 상세 분석")


        # 차트 옵션 설정
        c_range = st.radio("조회 기간", ["1개월", "3개월", "6개월", "1년"], horizontal=True, index=1)
        days_map = {"1개월": 30, "3개월": 90, "6개월": 180, "1년": 365}


        # 상세 데이터 호출
        m_data, p_hist, l_t, q_api = get_metric_data(target)


        if m_data and 'price' in m_data:
            curr = m_data['price']
            # 🎯 차트 기간과 무관하게 '전일 종가' 고정 사용
            prev = m_data.get('prev_close', curr)
            diff = curr - prev
            diff_pct = (diff / prev * 100) if prev != 0 else 0


            # 메트릭 레이아웃
            st.write("")
            c1, c2, c3, c4 = st.columns(4)
            
            with c1:
                st.metric("현재가", f"{curr:,.2f}")
            with c2:
                # 이제 코스피 -4%대가 정확히 찍힙니다.
                st.metric("변동폭", f"{diff:+,.2f}", f"{diff_pct:+,.2f}%")
            with c3:
                # 🎯 1순위: 수급/자금 지표 (금일 수급 표시)
                if target in CAT_FUNDS or "NET" in target:
                    st.metric("금일 수급", f"{curr:,.1f}억")
                
                # 🎯 2순위: 금리/FED/매크로 (거래량 대신 날짜/시간 표시)
                elif "RATE" in target or "FED" in target or target in CAT_MACRO or "Y" in target[-1:]:
                    st.metric("업데이트", l_t)
                
                # 🎯 3순위: 그 외 일반 지수/주식 (거래량 표시)
                else:
                    vol = m_data.get('volume', 0)
                    st.metric("거래량", f"{format_korean_unit(vol)}주")

            with c4:
                # 🎯 1순위: 거래 데이터가 있는 일반 지수/주식 (거래대금 표시)
                if target not in CAT_FUNDS and "NET" not in target and "RATE" not in target and "FED" not in target and target not in CAT_MACRO:
                    val = m_data.get('value', 0)
                    st.metric("거래대금", f"{format_korean_unit(val)}원")
                
                # 🎯 2순위: 나머지는 수치나 상태 표시 (중복 방지)
                else:
                    if "RATE" in target or "FED" in target:
                        st.metric("상태", "정상 수집")
                    else:
                        st.metric("데이터", "통계")


# 상세 차트 시각화
            if q_api:
                is_supply = "NET" in target
                lookback_str = "365d"
                agg_window = "1d" if days_map[c_range] >= 180 else "1h"
                
                chart_q = (
                    f'from(bucket: "{INFLUX_BUCKET}") '
                    f'|> range(start: -{lookback_str}) '
                    f'|> filter(fn: (r) => r._measurement == "financial_metrics" and r.symbol == "{target}") '
                    f'|> filter(fn: (r) => r._field == "price" or r._field == "value") '
                    f'|> aggregateWindow(every: {agg_window}, fn: last, createEmpty: false) '
                    f'|> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'
                )

                try:
                    query_result = q_api.query(chart_q)
                    df_list = []
                    zero_is_fine = ["US_SRF", "BTFP", "US_REVERSE_REPO", "US_RESERVES"]
                    
                    for table in query_result:
                        for r in table.records:
                            val = r.values.get('price') if r.values.get('price') is not None else r.values.get('value')
                            if val is not None:
                                if is_supply or target in zero_is_fine or val > 0:
                                    df_list.append({"time": r.get_time(), "Value": val})

                    df = pd.DataFrame(df_list)

                    if not df.empty:
                        # 통계값 계산
                        hi_val, lo_val = df['Value'].max(), df['Value'].min()
                        position = ((curr - lo_val) / (hi_val - lo_val) * 100) if hi_val != lo_val else 50.0
                        
                        df = df.sort_values("time").drop_duplicates("time")
                        
                        # 20일 이동평균선
                        if target in CAT_INDICES:
                            df['20MA'] = df['Value'].rolling(window=480, min_periods=1).mean()

                        # 선택 기간 필터링
                        cutoff_date = df['time'].max() - pd.Timedelta(days=days_map[c_range])
                        df = df[df['time'] >= cutoff_date]
                        df = df[df['Value'].diff() != 0].set_index("time")

                        # Vega-Lite 시각화
                        st.write("")
                        chart_df = df.reset_index()

                        # 🛠️ 줌 기능 보강 및 그리드 흐리게 설정 (안정화 버전)
                        final_spec = {
                            "width": "container",
                            "height": 450,
                            "layer": [
                                {
                                    # 줌/이동을 위한 셀렉션 정의
                                    "selection": {
                                        "grid": {
                                            "type": "interval", 
                                            "bind": "scales"
                                        }
                                    },
                                    "mark": {"type": "line", "color": "#FF0000", "strokeWidth": 2,"interpolate": "monotone", "connectNulls": False },
                                    "encoding": {
                                        "x": {"field": "time", "type": "temporal", "title": None, "axis": {"format": "%m/%d %H:%M"}},
                                        "y": {
                                            "field": "Value", 
                                            "type": "quantitative", 
                                            "scale": {"zero": is_supply, "nice": True},
                                            "title": None
                                        },
                                        "tooltip": [
                                            {"field": "time", "type": "temporal", "title": "시간", "format": "%Y-%m-%d %H:%M"},
                                            {"field": "Value", "type": "quantitative", "title": "값", "format": ",.2f"}
                                        ]
                                    }
                                }
                            ],
                            "config": {
                                "view": {"stroke": "transparent"},
                                "axis": {
                                    "grid": True,
                                    "gridColor": "#eeeeee",
                                    "gridOpacity": 0.1, # 훨씬 더 흐리게 조절
                                    "gridDash": [3, 3]
                                }
                            }
                        }

                        if '20MA' in chart_df.columns:
                            ma_layer = {
                                "mark": {"type": "line", "color": "#29b5e8", "strokeDash": [4, 4], "opacity": 0.7},
                                "encoding": {
                                    "x": {"field": "time", "type": "temporal"},
                                    "y": {"field": "20MA", "type": "quantitative"}
                                }
                            }
                            final_spec["layer"].append(ma_layer)
                        
                        st.vega_lite_chart(chart_df, final_spec, width='stretch')


                        # 분석 요약 정보
                        st.caption(f"📊 {display_names.get(target, target)}: {c_range} 추세 분석")
                        st.write("")
                        
                        col_a, col_b = st.columns([2, 1])
                        with col_a:
                            st.info(f"✨ **{c_range} 가격 범위**: 최고 **{hi_val:,.2f}** / 최저 **{lo_val:,.2f}**")
                        with col_b:
                            st.metric("현재 위치(%)", f"{position:.1f}%", help="최저점 대비 현재가 위치")


                        st.write("---")                        
# 1️⃣ [데이터 수집] SGI 분석에 필요한 7대 지표를 먼저 로드합니다.
                    # [2026-02-07] 이 블록이 반드시 calculate_and_save_sgi 호출보다 위에 있어야 합니다.
                        sgi_symbols = ["KOSPI", "KOR_NET_FOR", "KOR_NET_INST", "KOR_NET_RETAIL", "KOR_DEPOSIT", "KOR_CREDIT_LOAN", "USD_KRW"]
                        sgi_data_dict = {}
                    
                        for s_sym in sgi_symbols:
                            m_val, p_hist, _, _ = get_metric_data(s_sym)
                            
                            key_name = "KOR_NET_RETAIL" if s_sym == "KOR_NET_IND" else s_sym
                            
                            if m_val:
                                sgi_data_dict[s_sym] = {
                                    'curr': m_val.get('price', 0),
                                    'prev': p_hist[0] if (p_hist and len(p_hist) > 0) else m_val.get('price', 0),
                                    'hist': p_hist if p_hist else []
                                }
                            else:
                                sgi_data_dict[s_sym] = {'curr': 0, 'prev': 0, 'hist': []}
                        sgi_score, g_f, g_i, g_r, omega, avg_fx_3m = calculate_and_save_sgi(write_api, INFLUX_BUCKET, sgi_data_dict)
                        inertia_val = get_sgi_inertia(query_api, INFLUX_BUCKET) 

                        # 🎯 2. 휴장 및 정체 판정 (app.py에서 직접 수행)
                        import datetime
                        now = datetime.datetime.now()
                        is_weekend = now.weekday() >= 5
                        delta_val = abs(sgi_data_dict['KOSPI']['curr'] - sgi_data_dict['KOSPI']['prev'])
                        is_stagnant = delta_val < 0.1

                        # 🎯 3. UI 출력 섹션
                        st.subheader("📊 수급 중력 분석 (SGI 2.0)")                  
                        
                        if is_weekend or (abs(sgi_data_dict['KOSPI']['curr'] - sgi_data_dict['KOSPI']['prev']) < 0.1):
                            st.caption("⚠️ 현재 휴장일 또는 지수 변동 정체기로 인해 수치가 왜곡될 수 있습니다.")

                        col_sgi1, col_sgi2, col_sgi3 = st.columns([1, 1, 2]) 
                        
                        with col_sgi1:
                            st.metric("SGI 에너지", f"{sgi_score:,.2f}", delta=f"ω: {omega:.2f}")
                            st.caption(f"Ref(3M Avg): {avg_fx_3m:,.1f}원")

                        with col_sgi2:
                            # 🎯 관성(Inertia) 메트릭 배치
                            i_delta = "강력" if abs(inertia_val) > 300 else "보통"
                            st.metric("추세 관성 (5D)", f"{inertia_val:,.1f}", delta=i_delta)
                            st.caption("누적 수급 질량")

                        with col_sgi3:
                            # 상태 판독 및 메시지 출력
                            retail_msg = " | 🧱 매물 압박" if g_r > 5 else " | 🎈 가벼움" if g_r < -5 else ""
                            
                            if sgi_score < -100:
                                st.error(f"**🔴 1단계: 강한 수급 이탈**\n\n외인 매도 압력이 지수 방어력을 압도 중입니다. (하방 가속)")
                            elif sgi_score > 150:
                                st.success(f"**🚀 5단계: 수급 과밀 상승**\n\n저항 돌파! {retail_msg} 무중력 도약 구간입니다.")
                            else:
                                stage_desc = "🟢 4단계: 상승 탄력 확보" if sgi_score > 50 else "🟡 3단계: 수급 평형 구간" if sgi_score > -50 else "🟠 2단계: 하방 압력 우세"
                                st.info(f"**{stage_desc}**\n\n에너지 {sgi_score:,.1f}와 관성 {inertia_val:,.1f}를 종합 분석 중입니다.")

                        st.write("")
                        # 물리 지표 상세 분석 (4분할)
                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.caption("**외인 수급 강도**")
                            st.write(f"Gf: {g_f:,.1f}")
                            st.write('⚡ 주도' if abs(g_f)>15 else '☁️ 관망')
                        with c2:
                            st.caption("**기관 지원 강도**")
                            st.write(f"Gi: {g_i:,.1f}")
                            st.write('🛡️ 방어' if g_i>0 else '💣 파손')
                        with c3:
                            st.caption("**개인 매물 저항**")
                            st.write(f"Gr: {g_r:,.1f}")
                            st.write('🧱 압박' if g_r>5 else '🎈 가벼움')
                        with c4:
                            st.caption("**환율 매질 저항**")
                            st.write(f"ω: {omega:.2f}")
                            st.write('🍃 진공' if omega>1 else '🌊 늪지대')

                        st.caption(f"※ SGI 2.0: 3개월 평균 환율({avg_fx_3m:,.1f}원) 대비 현재 수급의 물리적 효율을 분석합니다.")

                    else:
                        st.info("차트용 데이터가 부족합니다.")


                except Exception as e:
                    st.error(f"차트 로딩 실패: {e}")


    except Exception as e:
        st.error(f"시장 데이터 로드 중 오류 발생: {e}")

# [2. 뉴스 스트리밍]
elif st.session_state.active_menu == "뉴스":    
    # 🎯 1. 사이드바 상태 관리 세션 초기화
    if 'show_rss_sidebar' not in st.session_state:
        st.session_state.show_rss_sidebar = False # 기본으로 닫아두어 광폭 화면 확보

    # 🎯 2. 최상단 컨트롤 바
    t_col1, t_col2 = st.columns([0.8, 0.2])
    
# --- [ 수정된 안전한 이름 결정 로직 ] ---
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
        selected_idx = st.session_state.current_feed_idx
        
        # 🎯 1. target_feed 결정 로직
        if selected_idx == "all":
            target_feed = None
        else:
            try:
                feeds = data.get('feeds', [])
                idx = int(selected_idx)
                target_feed = feeds[idx] if 0 <= idx < len(feeds) else None
            except:
                target_feed = None
                
        # 🎯 2. 데이터 로드 및 정렬 키 수정
        full_list = load_pending_files("일주일", target_feed=target_feed)
        # JSON 로더의 pub_dt 객체를 사용하여 최신순 정렬
        full_list.sort(key=lambda x: x.get('pub_dt', get_now_kst()), reverse=True)
        
        if full_list:
            items_per_page = 10
            total_pages = math.ceil(len(full_list) / items_per_page)
            
            if st.session_state.page_number > total_pages:
                st.session_state.page_number = 1
                
            start_idx = (st.session_state.page_number - 1) * items_per_page
            
# 🎯 3. 뉴스 카드 렌더링 루프
            current_page = st.session_state.page_number
            
            for i, entry in enumerate(full_list[start_idx : start_idx + items_per_page]):
                # 🔗 AI 요약 버튼을 위한 고유 식별자 생성
                safe_link = entry.get('link', 'no_link')[-30:] 
                unique_key = f"p{current_page}_idx{i}_{safe_link}"
                
                with st.container(border=True):
                    # KST 시각 표시
                    display_time = entry['pub_dt'].strftime('%Y-%m-%d %H:%M:%S')
                    st.caption(f"📍 {entry.get('source')} | 🕒 {display_time} (KST)")
                    st.markdown(f"#### {entry.get('title')}")
                    
                    cleaned_summary = clean_html(entry.get('summary', ''))
                    st.write(cleaned_summary[:200] + "...")
                    
                    btn_c1, btn_c2 = st.columns([0.2, 0.8])
                    
                    # 🌐 [교정] link_button에는 key 인자를 넣지 않습니다.
                    btn_c1.link_button("🌐 원문", entry.get('link', '#'), width='stretch')
                    
                    # 🤖 AI 요약 버튼은 고유 key가 반드시 필요합니다.
                    if btn_c2.button("🤖 AI 요약", key=f"ai_btn_{unique_key}", width='stretch'):
                        show_analysis_dialog(entry.get('title'), cleaned_summary, display_time, role="filter")

            st.write("")
            if total_pages > 1:
                # 10개씩 묶어서 표시 (예: 1~10, 11~20)
                current_group = (st.session_state.page_number - 1) // 10
                start_page = current_group * 10 + 1
                end_page = min(start_page + 9, total_pages)
                
                # 버튼 레이아웃 설정
                nav_cols = st.columns([0.6] + [1] * (end_page - start_page + 1) + [0.6])
                
                # [ < ] 이전 묶음 버튼
                if start_page > 1:
                    if nav_cols[0].button("<", key="prev_group"):
                        st.session_state.page_number = start_page - 1
                        st.rerun()
                
                # 숫자 버튼들
                for i, page_idx in enumerate(range(start_page, end_page + 1)):
                    if nav_cols[i+1].button(
                        str(page_idx), 
                        key=f"page_btn_{page_idx}",
                        type="primary" if st.session_state.page_number == page_idx else "secondary",
                        use_container_width=True
                    ):
                        st.session_state.page_number = page_idx
                        st.rerun()
                
                # [ > ] 다음 묶음 버튼
                if end_page < total_pages:
                    if nav_cols[-1].button(">", key="next_group"):
                        st.session_state.page_number = end_page + 1
                        st.rerun()
        else:
            st.warning("📡 수집된 뉴스 데이터가 없습니다.")
            
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
                # 디버그
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
                    try:
                        # 🚀 common.py의 통합 리포트 생성 함수 호출
                        report = generate_market_report(r_type, data)
                        
                        save_report_to_file(report, r_type)
                        st.session_state.last_report_content = report
                        st.rerun()
                    except Exception as e:
                        st.error(f"보고서 생성 실패: {e}")

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
        if chat_input := st.chat_input("보고서 내용이나 현재 지표에 대해 질문하세요."):
            st.session_state.report_chat_history.append({"role": "user", "content": chat_input})
            
            # 1. 현재 시간 및 요일 정보 생성
            now = get_now_kst()
            days = ['월', '화', '수', '목', '금', '토', '일']
            current_time_info = f"{now.strftime('%Y-%m-%d %H:%M:%S')} ({days[now.weekday()]}요일)"
            
            # 실시간 DB 지표 주입
            all_metrics_text = ""
            for sym in ALL_SYMBOLS:
                m_data, p_hist, _, _ = get_metric_data(sym)
                if m_data and 'price' in m_data:
                    curr = m_data['price']
                    prev = p_hist[0] if p_hist else curr
                    diff = ((curr - prev) / prev * 100) if prev != 0 else 0
                    all_metrics_text += f"- {display_names.get(sym, sym)}: {curr:,.2f} ({diff:+.2f}%)\n"
            
            # 2. 페르소나 및 시간 정보가 포함된 시스템 컨텍스트
            chat_context = (
                f"당신은 전문 금융 애널리스트입니다.\n"
                f"🕒 [현재 시각]: {current_time_info}\n"
                f"📊 [실시간 지표]:\n{all_metrics_text}\n"
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