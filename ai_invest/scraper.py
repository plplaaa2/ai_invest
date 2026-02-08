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
    [통합 보고서 엔진] - 단계별 디버그 로그 및 JSON 파싱 강화
    """
    now_kst = get_now_kst()
    now_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"\n[ {now_str} ] 🏛️ {r_type.upper()} 보고서 생성 프로세스 시작...")

    if not os.path.exists(CONFIG_PATH):
        print(f"❌ [에러] 설정 파일 미존재: {CONFIG_PATH}")
        return False

    historical_context = load_historical_contexts()
    print(f"📚 [STEP 1] 과거 맥락 로드 완료 (길이: {len(historical_context)}자)")

    lookback_map = {"daily": 7, "weekly": 30, "monthly": 365}
    lookback_days = lookback_map.get(r_type, 30)
    
    if r_type == "daily":
        news_count = config_data.get("report_news_count", 100)
        raw_news_list = []
        
        if os.path.exists(PENDING_PATH):
            files = sorted([f for f in os.listdir(PENDING_PATH) if f.endswith(".json")], reverse=True)
            print(f"🔍 [STEP 2] {PENDING_PATH}에서 {len(files)}개의 JSON 파일 발견")
            
            seen_keys = set()
            target_date_limit = (now_kst - timedelta(days=3)).date()
            
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

                        clean_key = title.replace("[특징주]", "").replace("[속보]", "").replace(" ", "")[:18]
                        if clean_key not in seen_keys:
                            seen_keys.add(clean_key)
                            raw_news_list.append(f"[{pub_dt_str[5:16]}] {title}")
                            
                        if len(raw_news_list) >= news_count: 
                            print(f"📝 [정보] 목표 뉴스 개수({news_count}개) 도달로 읽기 중단")
                            break
                except Exception as e:
                    parse_fail += 1
                    continue

            print(f"📊 [결과] 뉴스 수집 완료: 최종 {len(raw_news_list)}개 | 제외(날짜/중복): {filter_fail}개 | 파싱실패: {parse_fail}개")
        else:
            print(f"⚠️ [경고] PENDING_PATH 존재하지 않음: {PENDING_PATH}")

        news_ctx = f"### [ 금일 주요 뉴스 {len(raw_news_list)}선 ]\n"
        news_ctx += "\n".join([f"- {t}" for t in raw_news_list])
        input_content = f"{news_ctx}\n"
        report_label = "일간(Daily)"

    else:
        # 주간/월간 로직 로그 (생략)
        print(f"🗓️ [STEP 2] {r_type.upper()} 모드: 과거 리포트 요약 데이터 구성 중...")
        # ... (이전 코드와 동일한 요약 로직 수행) ...
        report_label = r_type.capitalize()
        input_content = "주간/월간 요약 데이터(중략)"

    # 🎯 3. AI 호출 로그
    a_cfg = config_data.get("analyst_model", {})
    model_name = a_cfg.get("name")
    print(f"🤖 [STEP 3] AI 모델 호출 시도: {model_name} (URL: {a_cfg.get('url')})")
    
    # (페이로드 구성 로직 동일 - 중략)
    
    # 🎯 4. 실행 및 저장 로그
    try:
        start_time = time.time()
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        duration = time.time() - start_time
        
        result = resp.json()
        # (결과 추출 로직 동일)
        
        print(f"✨ [STEP 4] AI 응답 수신 성공! (소요시간: {duration:.1f}초)")
        
        save_path = save_report_to_file(report_content, r_type)
        print(f"💾 [STEP 5] 보고서 저장 완료: {save_path}")
        return True
        
    except Exception as e:
        print(f"🚨 [에러] AI 호출 또는 저장 실패: {str(e)}")
        return False

if __name__ == "__main__":
    last_news_time = 0
    last_auto_report_date = ""
    last_weekly_report_date = "" 
    last_monthly_report_date = ""

    print(f"🚀 [AI Analyst] 시스템 가동 - 기준 시각: {data.get('report_gen_time', '08:00')} (KST)")
    print(f"📂 저장 경로: {BASE_PATH} | 뉴스 대기열: {PENDING_PATH}")

    while True:
        try:
            now_kst = get_now_kst()
            current_ts = time.time()
            current_config = load_data() 
            
            # 🕒 1. 시각 설정 로그
            base_time_str = str(current_config.get("report_gen_time", "08:00")).strip()
            current_time_str = now_kst.strftime("%H:%M")
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            
            # 2. 실행 시각 계산 (주간/월간 10~20분 간격)
            base_dt = datetime.strptime(base_time_str, "%H:%M")
            weekly_time_str = (base_dt + timedelta(minutes=10)).strftime("%H:%M")
            monthly_time_str = (base_dt + timedelta(minutes=20)).strftime("%H:%M")

            # --- [ 보고서 생성 섹션 ] ---
            if auto_gen_enabled:
                # 일간 보고서
                if current_time_str == base_time_str and last_auto_report_date != now_kst.strftime("%Y-%m-%d"):
                    print(f"🤖 [{now_kst.strftime('%H:%M:%S')}] >>> (1/3) 일간 보고서 생성 시퀀스 진입")
                    if generate_auto_report(current_config, r_type="daily"):
                        last_auto_report_date = now_kst.strftime("%Y-%m-%d")
                
                # 주간 보고서 (일요일)
                elif current_time_str == weekly_time_str and now_kst.weekday() == 6:
                    print(f"📅 [{now_kst.strftime('%H:%M:%S')}] >>> (2/3) 주간 보고서 생성 시퀀스 진입")
                    if generate_auto_report(current_config, r_type="weekly"):
                        last_weekly_report_date = now_kst.strftime("%Y-%U")

                # 월간 보고서 (1일)
                elif current_time_str == monthly_time_str and now_kst.day == 1:
                    print(f"🏛️ [{now_kst.strftime('%H:%M:%S')}] >>> (3/3) 월간 보고서 생성 시퀀스 진입")
                    if generate_auto_report(current_config, r_type="monthly"):
                        last_monthly_report_date = now_kst.strftime("%Y-%m")

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














