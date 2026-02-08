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
        with open(filepath, "w", encoding='utf-8') as f:
            json.dump(news_data, f, ensure_ascii=False, indent=2)
        processed_titles.add(clean_key)
        return True
    except:
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

def start_scraping():
    print("🚀 뉴스 수집 엔진 가동 중 (타임라인 보존 및 동적 중복 제거)...")
    
    while True:
        # 1. 설정 및 필터링 키워드 로드
        config = {"feeds": [], "update_interval": 10, "retention_days": 7}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config.update(json.load(f))
            except: pass
        
        interval = config.get("update_interval", 10)
        cleanup_old_files(config.get("retention_days", 7))
        
        # 🎯 메모리 캐시(processed_titles)가 너무 커지지 않게 주기적으로 비워주거나 
        # 최근 N개만 유지하는 로직을 고려할 수 있습니다. (현재는 실행 시 유지)
        
        g_inc = [k.strip().lower() for k in config.get('global_include', "").split(",") if k.strip()]
        g_exc = [k.strip().lower() for k in config.get('global_exclude', "").split(",") if k.strip()]

        # 2. 피드 순회
        feeds = config.get("feeds", [])
        total_found, new_saved = 0, 0

        for feed in feeds:
            try:
                parsed = feedparser.parse(feed['url'])
                # 피드별 개별 필터
                l_inc = [k.strip().lower() for k in feed.get('include', "").split(",") if k.strip()]
                l_exc = [k.strip().lower() for k in feed.get('exclude', "").split(",") if k.strip()]
                
                # 상위 50개 뉴스 확인
                for entry in parsed.entries[:50]:
                    total_found += 1
                    # 전역/개별 필터링 로직 (check_logic 함수는 기존 그대로 사용)
                    if not check_logic(entry.title, g_inc, g_exc): continue
                    if not check_logic(entry.title, l_inc, l_exc): continue
                    
                    if save_file(entry, feed['name']):
                        new_saved += 1
            except Exception as e:
                print(f"❌ {feed.get('name')} 수집 중 에러: {e}")
                continue
        
        # 3. 실시간 보고 로그
        now_str = datetime.now().strftime('%H:%M:%S')
        if total_found > 0:
            print(f"[{now_str}] 📊 발견 {total_found}개 | 신규 {new_saved}개 | 필터/중복 제외 {total_found - new_saved}개")
        
        # 💤 수집 주기는 유동적으로 (기본 10분)
        time.sleep(interval * 60)

def generate_auto_report(config_data, r_type="daily"):
    """
    [통합 보고서 엔진] 
    - 일간(daily): 7일 지표 + 당일 뉴스 분석
    - 주간(weekly): 30일 지표 + 지난 7일치 리포트 요약
    - 월간(monthly): 365일 지표 + 지난 30일치 리포트 요약
    """
    # 🎯 0. 기초 데이터 및 안전장치 확인
    if not os.path.exists(CONFIG_PATH):
        print(f"⏳ [대기] 설정 파일({CONFIG_PATH})이 없습니다. UI에서 설정을 저장해주세요.")
        return False

    now_kst = get_now_kst()
    now_str = now_kst.strftime("%Y-%m-%d %H:%M")
    historical_context = load_historical_contexts()

    # 🎯 1. 리포트 타입별 지표 조회 기간 설정 [사령관님 지침 반영]
    lookback_map = {"daily": 7, "weekly": 30, "monthly": 365}
    lookback_days = lookback_map.get(r_type, 30)
    
    
    # 🎯 2. 입력 데이터 구성 (일간 뉴스 vs 주간/월간 과거 리포트)
    if r_type == "daily":
        # --- [기존 뉴스 정제 로직] ---
        news_count = config_data.get("report_news_count", 100)
        raw_news_list = []
        if os.path.exists(PENDING_PATH):
            files = sorted(os.listdir(PENDING_PATH), reverse=True)
            seen_keys = set()
            for f_name in files:
                with open(os.path.join(PENDING_PATH, f_name), "r", encoding="utf-8") as file:
                    title = file.readline().replace("제목:", "").strip()
                    # 제목 18자 기반 중복 제거 로직
                    clean_key = title.replace("[특징주]", "").replace("[속보]", "").replace(" ", "")[:18]
                    if clean_key not in seen_keys:
                        seen_keys.add(clean_key)
                        raw_news_list.append(title)
                    if len(raw_news_list) >= news_count: break

        news_ctx = f"### [ 금일 주요 뉴스 {len(raw_news_list)}선 ]\n"
        news_ctx += "\n".join([f"- {t}" for t in raw_news_list])
        input_content = f"{news_ctx}\n"
        report_label = "일간(Daily)"

    else:
        # --- [주간/월간 전용 과거 리포트 요약 로직] ---
        daily_dir = "/share/ai_analyst/reports/01_daily"
        files = sorted([f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"], reverse=True)
        
        # 주간은 7개, 월간은 30개 파일 참조
        target_count = 7 if r_type == "weekly" else 30
        report_summary = f"### [ 지난 {target_count}일간의 분석 기록 요약 ]\n"
        
        for f_name in files[:target_count]:
            with open(os.path.join(daily_dir, f_name), 'r', encoding='utf-8') as f:
                # 각 일간 리포트의 핵심 500자 발췌
                report_summary += f"\n- {f_name}: {f.read()[:500]}...\n"
        
        input_content = f"{report_summary}\n"
        report_label = "주간(Weekly)" if r_type == "weekly" else "월간(Monthly)"

    # 🎯 3. 하이브리드 AI 설정 (UI 프롬프트 매칭)
    a_cfg = config_data.get("analyst_model", {})
    base_url = a_cfg.get("url", "").rstrip('/')
    model_name = a_cfg.get("name")
    base_prompt = a_cfg.get("prompt", "당신은 전문 금융 분석가입니다.")
    # r_type별 전용 프롬프트 우선 시도, 없으면 기본 프롬프트
    final_prompt = f"현재 임무: {report_label} 투자 전략 보고서 작성\n\n{base_prompt}"
    
    oa_key = config.get("openai_api_key", "")
    gm_key = config.get("gemini_api_key", "")

    # 🎯 4. 페이로드 구성 및 호출
    if "googleapis.com" in base_url or "gemini" in model_name.lower():
        url = f"{base_url}/v1beta/models/{model_name}:generateContent?key={gm_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [{"text": f"지침: {final_prompt}\n\n과거맥락: {historical_context}\n데이터:\n{input_content}"}]
            }]
        }
    else:
        url = f"{base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if oa_key and "gpt" in model_name.lower():
            headers["Authorization"] = f"Bearer {oa_key}"
            
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": f"시각: {now_str}\n{final_prompt}\n{historical_context}"},
                {"role": "user", "content": input_content}
            ],
            "temperature": a_cfg.get("temperature", 0.3)
        }

    # 🎯 5. 실행 및 계층형 저장 (Purge 자동 연동)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        
        report_content = result['candidates'][0]['content']['parts'][0]['text'] if "candidates" in result else result['choices'][0]['message']['content']
        
        # 사령관님의 save_report_to_file을 통해 폴더 분류 및 퍼지 실행
        save_report_to_file(report_content, r_type)
        print(f"[{now_str}] 🏛️ {r_type.upper()} 보고서 생성 완료 (지표기간: {lookback_days}일)")
        return True
    except Exception as e:
        print(f"🚨 [{r_type}] 생성 중단 원인: {str(e)}")
        return False

## --- [5. 메인 루프] ---
if __name__ == "__main__":
    last_prices = {} 
    last_collect_time = 0
    last_news_time = 0
    last_fred_time = 0 
    last_auto_report_date = ""
    last_weekly_report_date = "" 
    last_monthly_report_date = ""

    print(f"🚀 [AI Analyst] 시스템 가동 - 기준 시각: {data.get('report_gen_time', '08:00')} (KST)")

    while True:
        try:
            now_kst = get_now_kst()
            current_ts = time.time()
            current_config = load_data() 
            
            # 🕒 실행 시각 설정 및 계산
            base_time_str = str(current_config.get("report_gen_time", "08:00")).strip()
            base_time = datetime.strptime(base_time_str, "%H:%M")
            
            # 10분, 20분 간격 순차 실행 시각
            weekly_time_str = (base_time + timedelta(minutes=10)).strftime("%H:%M")
            monthly_time_str = (base_time + timedelta(minutes=20)).strftime("%H:%M")
            
            current_time_str = now_kst.strftime("%H:%M")
            auto_gen_enabled = current_config.get("report_auto_gen", False)

            if auto_gen_enabled:
                # 1️⃣ [T+0] 일간 보고서 (매일)
                if current_time_str == base_time_str:
                    if last_auto_report_date != now_kst.strftime("%Y-%m-%d"):
                        print(f"🤖 [{now_kst.strftime('%H:%M:%S')}] (1/3) 일간 보고서 생성...")
                        # r_type을 명시하여 common의 save_report_to_file과 연동
                        if generate_auto_report(current_config, r_type="daily"):
                            last_auto_report_date = now_kst.strftime("%Y-%m-%d")

                # 2️⃣ [T+10분] 주간 보고서 (일요일 & 7일치 데이터 확인)
                elif current_time_str == weekly_time_str and now_kst.weekday() == 6:
                    daily_dir = "/share/ai_analyst/reports/01_daily"
                    daily_files = [f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"]
                    
                    if len(daily_files) >= 7:
                        current_week = now_kst.strftime("%Y-%U")
                        if last_weekly_report_date != current_week:
                            print(f"📅 [{now_kst.strftime('%H:%M:%S')}] (2/3) 주간 결산 리포트 생성...")
                            if generate_auto_report(current_config, r_type="weekly"):
                                last_weekly_report_date = current_week
                    else:
                        print(f"⚠️ 주간 리포트 스킵: 일간 데이터 부족 ({len(daily_files)}/7)")

                # 3️⃣ [T+20분] 월간 보고서 (매월 1일 & 20일치 데이터 확인)
                elif current_time_str == monthly_time_str and now_kst.day == 1:
                    daily_dir = "/share/ai_analyst/reports/01_daily"
                    daily_files = [f for f in os.listdir(daily_dir) if f.endswith(".txt") and f != "latest.txt"]
                    
                    if len(daily_files) >= 20:
                        current_month = now_kst.strftime("%Y-%m")
                        if last_monthly_report_date != current_month:
                            print(f"🏛️ [{now_kst.strftime('%H:%M:%S')}] (3/3) 월간 결산 리포트 생성...")
                            if generate_auto_report(current_config, r_type="monthly"):
                                last_monthly_report_date = current_month
                    else:
                        print(f"⚠️ 월간 리포트 스킵: 일간 데이터 부족 ({len(daily_files)}/20)")

            # --- [T3: 뉴스 수집] ---
            update_interval_sec = current_config.get("update_interval", 10) * 60
            if current_ts - last_news_time >= update_interval_sec:
                # (RSS 수집 로직 호출부)
                last_news_time = current_ts
                
        except Exception as e: 
            print(f"❌ 루프 에러: {e}")
            
        time.sleep(60)













