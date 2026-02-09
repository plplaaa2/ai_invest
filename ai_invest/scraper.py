import hashlib
from common import *

processed_titles = set()

def save_file(entry, feed_name):
    """개선된 타임라인 보존 저장 방식 (JSON)"""
    global processed_titles
    
    title = entry.title.strip()
# 🎯 1. 발행 시간을 KST(한국 표준시)로 엄격하게 변환 [cite: 1, 4]
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        # UTC 기반 구조체 시간을 KST datetime 객체로 변환 [cite: 3, 4]
        dt_obj = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc).astimezone(KST)
    else:
        # 시간 정보가 없는 경우 현재 KST 시각 사용 
        dt_obj = get_now_kst()
        
    dt_str = dt_obj.strftime('%Y%m%d_%H%M%S')# 파일명 정렬용
    date_key = dt_obj.strftime('%Y%m%d')     # 일별 중복 분리용
    pub_dt_str = dt_obj.strftime('%Y-%m-%d %H:%M:%S') # 데이터 저장용
    
    # 🎯 2. 중복 체크 키 강화 (날짜 + 제목 15자)
    # 이제 날짜가 다르면 같은 제목이라도 별개 뉴스로 수집합니다.
    clean_key = f"{date_key}_{title.replace(' ', '')[:15]}"
    
    if clean_key in processed_titles:
        return False
    
    # 🎯 3. 파일명에 시간 정보 주입 (정렬 최적화)
    file_hash = hashlib.md5(title.encode()).hexdigest()[:6]
    filename = f"{dt_str}_{file_hash}.json" # JSON 확장자 사용
    filepath = os.path.join(PENDING_PATH, filename)
    
    # 🎯 4. 데이터 구조화 (AI 분석용 정보 확장)
    news_data = {
        "title": title,
        "pub_dt": pub_dt_str, # [수정 완료]
        "source": feed_name,
        "summary": entry.get('summary', '내용 없음'),
        "link": entry.get('link', '')
    }
    
    try:
        os.makedirs(PENDING_PATH, exist_ok=True)
        with open(filepath, "w", encoding='utf-8') as f:
            json.dump(news_data, f, ensure_ascii=False, indent=2)
        processed_titles.add(clean_key)
        return True
    except Exception as e:
        print(f"❌ 파일 쓰기 실패: {e}") # 에러 로그를 남겨야 경로 문제를 알 수 있습니다.
        return False
        
def check_logic(text, inc_list, exc_list):
    """필터링 로직: 제외어 포함 시 탈락, 포함어 설정 시 포함되어야 통과"""
    text = text.lower()
    if any(x in text for x in exc_list if x):
        return False
    if inc_list:
        if not any(i in text for i in inc_list if i):
            return False
    return True

def cleanup_old_files(retention_days):
    """설정된 기간보다 오래된 파일 및 메모리 캐시 삭제"""
    global processed_titles
    if not os.path.exists(PENDING_PATH): return
    
    current_time = time.time()
    seconds_threshold = retention_days * 86400
    deleted_count = 0
    
    for filename in os.listdir(PENDING_PATH):
        file_path = os.path.join(PENDING_PATH, filename)
        if os.path.isfile(file_path) and (filename.endswith(".json") or filename.endswith(".txt")):
            if (current_time - os.path.getmtime(file_path)) > seconds_threshold:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except: pass
    
    # 파일 삭제 시 메모리 캐시도 함께 비워 시스템을 가볍게 유지
    processed_titles.clear()
    if deleted_count > 0:
        print(f"🧹 {deleted_count}개의 뉴스 파일을 정리하고 중복 필터를 초기화했습니다.")


def generate_auto_report(config_data, r_type="daily"):
    """
    [통합 보고서 엔진] - 유형별 데이터 준비와 AI 엔진을 분리하여 실행
    """
    now_kst = get_now_kst()
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[ {now_str} ] 🏛️ {r_type.upper()} 보고서 생성 프로세스 시작...")

    # 1. 보고서 유형별 데이터 준비
    if r_type == "daily":
        input_content, report_label = _prepare_daily_report_data(config_data, now_kst)
    else:
        input_content, report_label = _prepare_periodical_report_data(config_data, r_type)

    if not input_content:
        print(f"⚠️ [경고] {r_type.upper()} 리포트 생성을 위한 데이터가 부족하여 중단합니다.")
        return False

    # 2. AI 엔진 호출 (분석 및 저장)
    return _execute_report_ai_engine(config_data, r_type, report_label, input_content)

def _prepare_daily_report_data(config_data, now_kst):
    """일간 보고서용 데이터 구성 (뉴스 필터링 + 지표 데이터)"""
    print(f"🔍 [STEP 2-D] Daily 데이터 수집 및 뉴스 필터링 시작...")
    
    # (1) 지표 데이터 가져오기 (최근 7일 추세)
    metric_ctx = get_influx_metric_context(7)
    
    # (2) 뉴스 수집 및 중복/날짜 필터링 (제공된 로직 적용)
    news_count = config_data.get("report_news_count", 100)
    raw_news_list = []
    seen_keys = set()
    target_date_limit = (now_kst - timedelta(days=3)).date()
    
    if os.path.exists(PENDING_PATH):
        files = sorted([f for f in os.listdir(PENDING_PATH) if f.endswith(".json")], reverse=True)
        parse_fail, filter_fail = 0, 0

        for f_name in files:
            try:
                with open(os.path.join(PENDING_PATH, f_name), "r", encoding="utf-8") as file:
                    news_data = json.load(file)
                    title = news_data.get("title", "").strip()
                    pub_dt_str = news_data.get("pub_dt", "")
                    
                    if not title: continue
                    
                    # 날짜 체크
                    try:
                        f_dt = datetime.strptime(pub_dt_str, '%Y-%m-%d %H:%M:%S').date()
                    except:
                        f_dt = now_kst.date()

                    if f_dt < target_date_limit:
                        filter_fail += 1
                        continue

                    # 중복 제거 키 생성
                    clean_key = title.replace("[특징주]", "").replace("[속보]", "").replace(" ", "")[:18]
                    if clean_key not in seen_keys:
                        seen_keys.add(clean_key)
                        raw_news_list.append(f"[{pub_dt_str[5:16]}] {title}")
                        
                    if len(raw_news_list) >= news_count:
                        break
            except:
                parse_fail += 1
                continue
        print(f"📊 [결과] 뉴스 수집 완료: 최종 {len(raw_news_list)}개 (제외: {filter_fail}, 실패: {parse_fail})")
    
    news_ctx = f"### [ 금일 주요 뉴스 {len(raw_news_list)}선 ]\n" + "\n".join([f"- {t}" for t in raw_news_list])
    
    final_input = f"{metric_ctx}\n\n{news_ctx}"
    return final_input, "일간(Daily)"

def _prepare_periodical_report_data(config_data, r_type):
    """주간/월간 보고서용 데이터 구성 (과거 리포트 요약)"""
    lookback = 7 if r_type == "weekly" else 30
    label = "주간(Weekly)" if r_type == "weekly" else "월간(Monthly)"
    print(f"🗓️ [STEP 2-{r_type[0].upper()}] {label} 모드: 과거 리포트 요약 구성 중...")

    # (1) 지표 데이터 가져오기
    metric_ctx = get_influx_metric_context(lookback)
    
    # (2) 과거 일간 리포트 파일 읽기
    daily_dir = os.path.join(REPORT_DIR, "01_daily")
    report_summary = f"### [ 지난 {lookback}일간의 분석 기록 요약 ]\n"
    
    if os.path.exists(daily_dir):
        files = sorted([f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"], reverse=True)
        for f_name in files[:lookback]:
            try:
                with open(os.path.join(daily_dir, f_name), 'r', encoding='utf-8') as f:
                    # 파일명과 본문 일부 추출
                    report_summary += f"\n- {f_name}: {f.read()[:400]}...\n"
            except Exception as e:
                print(f"⚠️ 파일 로드 실패 ({f_name}): {e}")
    
    final_input = f"{metric_ctx}\n\n{report_summary}"
    return final_input, label

def _execute_report_ai_engine(config_data, r_type, report_label, input_content):
    """[공통 AI 엔진] 지침 구성, AI 호출 및 저장"""
    now_kst = get_now_kst()
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    historical_context = load_historical_contexts() # STEP 1 맥락 로드

    # 1. 프롬프트 설정 (참조하신 구조 적용)
    if r_type == "daily":
        base_prompt = config_data.get("council_prompt", "당신은 전략 자산 배분가입니다.")
    else:
        base_prompt = (
            f"당신은 '전략 자산 배분가'입니다. 제공된 뉴스의 지표 추세와 과거 분석 기록들을 바탕으로 "
            "단기적 소음(Noise)을 제거하고 거시적인 흐름(Trend)을 요약하세요."
        )

    analysis_guideline = (
        "### [ 자료 분석 지침 ]\n"
        "1. 수치 절대 우선: 뉴스 수치를 최우선 팩트로 삼는다.\n"
        "2. 연속성 원칙: 과거 분석 기록과 현재 지표를 비교하여 전망의 적중 여부를 언급하라.\n"
        "3. 전략적 수정: 변화에 따라 포트폴리오 비중을 유연하게 업데이트하라.\n"
    )

    final_prompt = f"현재 임무: {report_label} 투자 전략 보고서 작성\n\n당신은 {base_prompt}\n\n{analysis_guideline}"

    # 2. AI 모델 설정 및 호출 (Gemini/OpenAI 분기 로직)
    a_cfg = config_data.get("analyst_model", {})
    model_name = a_cfg.get("name")
    print(f"🤖 [STEP 3] AI 모델 호출: {model_name}")



def _execute_report_ai_engine(config_data, r_type, report_label, input_content):
    """
    [AI 분석 실행 엔진] 지침 구성, 모델 호출, 결과 저장 프로세스를 통합 관리합니다.
    """
    now_kst = get_now_kst()
    now_str = now_kst.strftime("%Y-%m-%d %H:%M")
    
    # 🎯 STEP 1: 과거 맥락 및 설정 로드
    historical_context = load_historical_contexts()
    a_cfg = config_data.get("analyst_model", {})
    base_url = a_cfg.get("url", "").rstrip('/')
    model_name = a_cfg.get("name")
    
    print(f"🤖 [STEP 3] AI 모델 호출 시도: {model_name} (유형: {report_label})")

    # 🎯 STEP 2: 리포트 타입에 따른 맞춤형 페르소나(Base Prompt) 설정
    if r_type == "daily":
        # 일간 보고서는 설정파일의 기본 프롬프트 사용
        base_prompt = config_data.get("council_prompt", "당신은 전문 금융 분석가입니다.")
    elif r_type in ["weekly", "monthly"]:
        # 주간/월간은 전략 자산 배분가 관점의 거시적 지침 부여
        base_prompt = (
            f"당신은 '전략 자산 배분가'입니다. 제공된 {r_type} 지표 추세와 과거 분석 기록들을 바탕으로 "
            "단기적 소음(Noise)을 제거하고 거시적인 흐름(Trend)을 요약하세요. "
            "향후 대응 전략과 포트폴리오 조정 방향에 집중하여 보고서를 작성하세요."
        )
    else:
        base_prompt = config_data.get("council_prompt", "당신은 전문 금융 분석가입니다.")

    # 🎯 STEP 3: 분석 가이드라인 및 출력 구조 정의
    analysis_guideline = (
        "### [ 자료 분석 지침 ]\n"                        
        "1. 시장 상태 인지: 현재가 주말이면 가장 최근 거래일(금요일) 종가를 현재가로 간주한다.\n"
        "2. 수치 절대 우선: 뉴스 제목의 톤보다 '원천 수급 지표'의 등락 수치(+0.55% 등)를 최우선 팩트로 삼는다.\n"
        "3. 추세와 반등 구분: 며칠간 하락했더라도 마지막 지표가 상승이면 '단기 반등 성공'으로 해석하라.\n"
        "4. 연속성 원칙: '과거 분석 기록'에서 제시했던 주요 전망과 오늘 '원천 수급 지표'를 비교하여 예측 적중 여부를 반드시 언급하라.\n"
        "5. 전략적 수정: 지표 변화에 따라 포트폴리오 비중이나 투자 행동 지침을 유연하게 업데이트하라.\n"
        "6. 뉴스정리: 뉴스가 거시경제나 유동성에 중요한지 판독하여 가중치를 둔다.\n"
    )

    structure_instruction = (
        "### [ 보고서 작성 형식 ]\n"
        "아래 구조를 반드시 엄수하여 작성하라:\n"
        "1. 시황 브리핑 / 2. 주요 뉴스 및 오피니언 / 3. 거시경제 분석 / 4. 자산별 분석 / 5. 산업별 분석 / "
        "6. 주력/미래 산업 전망 / 7. 리스크 분석 / 8. 포트폴리오 및 전략(비중 % 포함) / 8. 뉴스에서 수집한 경제지표들(다음 보고서를 위한)\n"
    )

    # 🎯 STEP 4: 최종 프롬프트 통합
    final_prompt = (
        f"현재 임무: {report_label} 투자 전략 보고서 작성\n\n"
        f"당신은 {base_prompt}\n\n"
        f"{analysis_guideline}\n"
        f"{structure_instruction}\n"
        f"위 '원천 수급 지표'의 수치를 바탕으로 뉴스를 해석하고 보고서를 작성하라."
    )

    # 🎯 STEP 5: API 인증 정보 로드 (config 객체 참조)
    oa_key = config.get("openai_api_key", "")
    gm_key = config.get("gemini_api_key", "")

    # 🎯 STEP 6: 모델 유형별 페이로드 구성 및 호출
    if "googleapis.com" in base_url or "gemini" in model_name.lower():
        # Gemini API 호출 방식
        url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={gm_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": f"지침: {final_prompt}\n\n과거맥락: {historical_context}\n데이터:\n{input_content}"}]
            }]
        }
    else:
        # OpenAI 스타일 API 호출 방식 (GPT 및 호환 모델)
        url = f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if oa_key and ("gpt" in model_name.lower() or "openai" in base_url.lower()):
            headers["Authorization"] = f"Bearer {oa_key}"
        
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": f"기준시각: {now_str}\n{final_prompt}\n{historical_context}"},
                {"role": "user", "content": input_content}
            ],
            "temperature": a_cfg.get("temperature", 0.3)
        }

    # 🎯 STEP 7: 요청 실행 및 결과 처리
    try:
        start_time = time.time()
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        duration = time.time() - start_time
        
        # 응답 구조 파싱
        if "candidates" in result:
            report_content = result['candidates'][0]['content']['parts'][0]['text']
        else:
            report_content = result['choices'][0]['message']['content']
        
        # 결과 파일 저장
        save_path = save_report_to_file(report_content, r_type)
        print(f"✨ [STEP 4] {report_label} 응답 수신 성공! (소요시간: {duration:.1f}초)")
        print(f"💾 [STEP 5] 보고서 저장 완료: {save_path}")
        return True

    except Exception as e:
        print(f"🚨 [에러] AI 엔진 실행 중 오류 발생 ({r_type}): {e}")
        return False


if __name__ == "__main__":
    last_news_time = 0
    last_auto_report_date = ""
    last_weekly_report_date = "" 
    last_monthly_report_date = ""

# 시스템 시작 로그 (초기 설정 로드)
    try:
        init_config = load_data()
        report_time = init_config.get('report_gen_time', '08:00')
        print(f"🚀 [AI Analyst] 시스템 가동 - 기준 시각: {report_time} (KST)")
        print(f"📂 저장 경로: {BASE_PATH} | 뉴스 대기열: {PENDING_PATH}")
    except Exception as e:
        print(f"❌ 초기 설정 로드 실패: {e}")

    while True:
        try:
            # 1. 매 루프마다 최신 설정 및 시각 업데이트
            now_kst = get_now_kst()
            current_config = load_data()
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            
            # 실행 기준 시각 설정 (문자열 공백 제거)
            base_time_str = str(current_config.get("report_gen_time", "08:00")).strip()
            current_time_str = now_kst.strftime("%H:%M")
            
            # 2. 실행 시각 계산 (주간/월간은 순차 처리를 위해 10~20분 간격 배치)
            base_dt = datetime.strptime(base_time_str, "%H:%M")
            weekly_time_str = (base_dt + timedelta(minutes=10)).strftime("%H:%M")
            monthly_time_str = (base_dt + timedelta(minutes=20)).strftime("%H:%M")

            # --- [ 🤖 자동 보고서 생성 섹션 ] ---
            if auto_gen_enabled:
                
                # ① 일간 보고서 (매일 지정 시각)
                if current_time_str == base_time_str:
                    today_str = now_kst.strftime("%Y-%m-%d")
                    if last_auto_report_date != today_str:
                        print(f"🤖 [{now_kst.strftime('%H:%M:%S')}] >>> (1/3) 일간 보고서 생성 시퀀스 진입")
                        if generate_auto_report(current_config, r_type="daily"):
                            last_auto_report_date = today_str

                # ② 주간 보고서 (일요일 & 지정 시각 + 10분)
                elif current_time_str == weekly_time_str and now_kst.weekday() == 6:
                    week_str = now_kst.strftime("%Y-%U")
                    if last_weekly_report_date != week_str:
                        print(f"📅 [{now_kst.strftime('%H:%M:%S')}] >>> (2/3) 주간 보고서 생성 시퀀스 진입")
                        if generate_auto_report(current_config, r_type="weekly"):
                            last_weekly_report_date = week_str

                # ③ 월간 보고서 (매월 1일 & 지정 시각 + 20분)
                elif current_time_str == monthly_time_str and now_kst.day == 1:
                    month_str = now_kst.strftime("%Y-%m")
                    if last_monthly_report_date != month_str:
                        print(f"🏛️ [{now_kst.strftime('%H:%M:%S')}] >>> (3/3) 월간 보고서 생성 시퀀스 진입")
                        if generate_auto_report(current_config, r_type="monthly"):
                            last_monthly_report_date = month_str

            # --- [ 뉴스 수집 섹션 ] ---
            update_interval_min = current_config.get("update_interval", 10)
            update_interval_sec = update_interval_min * 60
            
            # 다음 수집까지 남은 시간 계산 (로그용)
            time_since_last = current_ts - last_news_time
            next_in = max(0, update_interval_sec - time_since_last)

            if time_since_last >= update_interval_sec:
                print(f"📡 [{now_kst.strftime('%H:%M:%S')}] 뉴스 수집 엔진 가동 (주기: {update_interval_min}분)")
                
                feeds = current_config.get("feeds", [])
                g_inc = [k.strip().lower() for k in current_config.get('global_include', "").split(",") if k.strip()]
                g_exc = [k.strip().lower() for k in current_config.get('global_exclude', "").split(",") if k.strip()]
                
                new_saved = 0
                for feed in feeds:
                    try:
                        parsed = feedparser.parse(feed['url'])
                        l_inc = [k.strip().lower() for k in feed.get('include', "").split(",") if k.strip()]
                        l_exc = [k.strip().lower() for k in feed.get('exclude', "").split(",") if k.strip()]
                        
                        feed_new = 0
                        for entry in parsed.entries[:50]:
                            if not check_logic(entry.title, g_inc, g_exc): continue
                            if not check_logic(entry.title, l_inc, l_exc): continue
                            if save_file(entry, feed['name']):
                                feed_new += 1
                                new_saved += 1
                        if feed_new > 0:
                            print(f"   └─ {feed['name']}: {feed_new}개 신규 저장")
                    except Exception as e:
                        print(f"   └─ ❌ {feed.get('name')} 오류: {e}")
                
                print(f"✅ [{now_kst.strftime('%H:%M:%S')}] 수집 완료 (총 {new_saved}개 신규 확보)")
                last_news_time = current_ts
            else:
                # 매 분마다 정기 생존 신고 로그 (선택 사항)
                if now_kst.minute % 5 == 0: # 5분마다 출력
                    print(f"💤 [{now_kst.strftime('%H:%M:%S')}] 대기 중... (다음 뉴스 수집까지 {int(next_in/60)}분 남음)")

        except Exception as e: 
            print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] 루프 치명적 에러: {e}")
            
        time.sleep(60)
















