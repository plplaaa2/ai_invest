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


def generate_auto_report(config_data, r_type):
    """자동 보고서 생성 오케스트레이터"""
    # 1. 데이터 준비 (common.py 활용)
    input_content, label = prepare_report_data(r_type, config_data)
    
    if not input_content:
        print(f"⚠️ [Auto] 분석할 데이터가 부족하여 보고서 생성을 건너뜁니다.")
        return False

    print(f"🤖 [Auto] {label} 보고서 생성 시작...")
    
    # 2. AI 생성 (common.py 활용)
    report_content = generate_invest_report(r_type, input_content, config_data)
    
    if report_content and "❌" not in report_content:
        # 3. 저장
        save_path = save_report_to_file(report_content, r_type)
        print(f"✨ [Auto] {label} 생성 완료! 저장됨: {save_path}")
        return True
    else:
        print(f"🚨 [Auto] 보고서 생성 실패: {report_content}")
        return False

# --- [ 3. 메인 루프 (수동 작업에 방해받지 않는 스케줄러) ] ---

if __name__ == "__main__":
    # 💡 자동화(Auto) 전용 상태 관리 변수 (수동 실행 시 이 변수들을 건드리지 않으면 자동 실행됨)
    auto_daily_done_date = ""
    auto_weekly_done_week = ""
    auto_monthly_done_month = ""
    
    last_news_time = 0

    try:
        init_config = load_data()
        print(f"🚀 [AI Analyst] 시스템 가동 - 기준 시각: {init_config.get('report_gen_time', '08:00')} (KST)")
    except Exception as e:
        print(f"❌ 초기 설정 로드 실패: {e}")

    while True:
        try:
            now_kst = get_now_kst()
            current_ts = time.time() # 🚨 NameError 해결
            current_config = load_data()
            
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            base_time_str = str(current_config.get("report_gen_time", "08:00")).strip()
            current_time_str = now_kst.strftime("%H:%M")
            
            # 예약 시각 계산 (10분/20분 간격)
            base_dt = datetime.strptime(base_time_str, "%H:%M")
            weekly_time_str = (base_dt + timedelta(minutes=10)).strftime("%H:%M")
            monthly_time_str = (base_dt + timedelta(minutes=20)).strftime("%H:%M")

            # --- [ 🤖 자동 보고서 생성 섹션 ] ---
            if auto_gen_enabled:
                
                # ① 일간 자동 보고서
                if current_time_str == base_time_str:
                    today_str = now_kst.strftime("%Y-%m-%d")
                    # 💡 수동 보고서 파일이 있어도, '자동 스케줄러'가 오늘 처음이라면 실행합니다.
                    if auto_daily_done_date != today_str:
                        print(f"🤖 [{now_kst.strftime('%H:%M:%S')}] >>> 스케줄러: 자동 일간 보고서 생성 시도")
                        if generate_auto_report(current_config, "daily"):
                            auto_daily_done_date = today_str # 자동 실행 성공 시에만 마킹

                # ② 주간 자동 보고서 (일요일)
                elif current_time_str == weekly_time_str and now_kst.weekday() == 6:
                    week_str = now_kst.strftime("%Y-%U")
                    if auto_weekly_done_week != week_str:
                        print(f"📅 [{now_kst.strftime('%H:%M:%S')}] >>> 스케줄러: 자동 주간 보고서 생성 시도")
                        if generate_auto_report(current_config, "weekly"):
                            auto_weekly_done_week = week_str

                # ③ 월간 자동 보고서 (1일)
                elif current_time_str == monthly_time_str and now_kst.day == 1:
                    month_str = now_kst.strftime("%Y-%m")
                    if auto_monthly_done_month != month_str:
                        print(f"🏛️ [{now_kst.strftime('%H:%M:%S')}] >>> 스케줄러: 자동 월간 보고서 생성 시도")
                        if generate_auto_report(current_config, "monthly"):
                            auto_monthly_done_month = month_str
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
