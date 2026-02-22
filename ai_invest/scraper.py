import hashlib
from common import *

processed_titles = {}  # {clean_key: timestamp} - 3일 TTL 기반 중복 캐시
CACHE_TTL = 3 * 86400  # 3일 (초)


def init_processed_cache():
    """기존 파일에서 중복 캐시를 복원합니다 (재시작 시 중복 수집 방지)"""
    global processed_titles
    if not os.path.exists(PENDING_PATH):
        return
    
    current_time = time.time()
    count = 0
    
    for f in os.listdir(PENDING_PATH):
        fp = os.path.join(PENDING_PATH, f)
        if not (os.path.isfile(fp) and f.endswith(".json")):
            continue
        
        # 3일보다 오래된 파일은 캐시에 넣지 않음
        mtime = os.path.getmtime(fp)
        if current_time - mtime > CACHE_TTL:
            continue
            
        try:
            with open(fp, "r", encoding="utf-8") as file:
                news_data = json.load(file)
                title = news_data.get("title", "").strip()
                pub_dt_str = news_data.get("pub_dt", "")
                if not title:
                    continue
                
                try:
                    dt_obj = datetime.strptime(pub_dt_str, '%Y-%m-%d %H:%M:%S')
                    date_key = dt_obj.strftime('%Y%m%d')
                except:
                    date_key = "unknown"
                
                clean_key = f"{date_key}_{hashlib.md5(title.encode()).hexdigest()[:12]}"
                processed_titles[clean_key] = mtime
                count += 1
        except:
            continue
    
    print(f"🔄 중복 캐시 복원 완료: {count}개 항목 로드됨 (3일 이내)")



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
    
    # 🎯 2. 중복 체크 키 (날짜 + 제목 MD5 해시 - 충돌 방지)
    clean_key = f"{date_key}_{hashlib.md5(title.encode()).hexdigest()[:12]}"
    
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
        processed_titles[clean_key] = time.time()
        return True
    except Exception as e:
        print(f"❌ 파일 쓰기 실패: {e}") # 에러 로그를 남겨야 경로 문제를 알 수 있습니다.
        return False
        
def cleanup_old_files(retention_days):
    """설정된 기간보다 오래된 파일 및 메모리 캐시 삭제"""
    global processed_titles
    if not os.path.exists(PENDING_PATH): return
    
    current_time = time.time()
    seconds_threshold = retention_days * 86400
    deleted_count = 0
    max_files = 600 # 최대 파일 개수 제한
    
    # 1. 파일 목록 확보 및 정렬 (오래된 순)
    files = []
    for f in os.listdir(PENDING_PATH):
        fp = os.path.join(PENDING_PATH, f)
        if os.path.isfile(fp) and (f.endswith(".json") or f.endswith(".txt")):
            files.append((os.path.getmtime(fp), fp))
            
    files.sort(key=lambda x: x[0]) # 오름차순: 오래된 파일 -> 최신 파일
    
    # 2. 삭제 수행
    total_cnt = len(files)
    for i, (mtime, fp) in enumerate(files):
        # 삭제 조건: 기간 만료 OR 개수 초과 (남은 파일이 1500개보다 많으면 삭제)
        if (current_time - mtime > seconds_threshold) or ((total_cnt - i) > max_files):
            try:
                os.remove(fp)
                deleted_count += 1
            except: pass
        else:
            break # 정렬되어 있으므로 이후 파일은 안전
    
    # 만료된 캐시 항목만 선택적 제거 (3일 TTL)
    expired_keys = [k for k, t in processed_titles.items() if current_time - t > CACHE_TTL]
    for k in expired_keys:
        del processed_titles[k]
    if deleted_count > 0 or expired_keys:
        print(f"🧹 파일 {deleted_count}개 정리, 만료 캐시 {len(expired_keys)}개 제거 (캐시 잔여: {len(processed_titles)}개)")


def generate_auto_report(config_data, r_type):
    """자동 보고서 생성 오케스트레이터"""
    # 0. 데이터 최신화: 보고서 생성을 위한 시장 데이터 갱신 (마켓 오픈/클로즈 판별)
    print(f"🔄 [Auto] 보고서 생성을 위한 시장 데이터 갱신 점검...")
    try:
        if is_kr_market_open():
            get_krx_summary_raw(ignore_cache=True)
        
        if is_us_market_open():
            get_global_financials_raw(ignore_cache=True, fetch_type="all")
        else:
            get_global_financials_raw(ignore_cache=True, fetch_type="non_equities")
            
        get_fed_liquidity_raw()
    except Exception as e:
        print(f"⚠️ 데이터 갱신 중 오류 발생 (기존 데이터 사용): {e}")

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
    first_run = True
    _config_mtime = 0  # 설정 파일 변경 감지용
    _cached_config = None
    _cached_base_time = None  # 예약 시각 캐시
    _cached_weekly_time = None
    _cached_monthly_time = None

    def _load_config_if_changed():
        """설정 파일이 변경된 경우에만 다시 로드합니다 (디스크 I/O 최소화)"""
        nonlocal _config_mtime, _cached_config, _cached_base_time, _cached_weekly_time, _cached_monthly_time
        try:
            mt = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0
        except:
            mt = 0
        if mt != _config_mtime or _cached_config is None:
            _config_mtime = mt
            _cached_config = load_data()
            # 예약 시각도 설정 변경 시에만 재계산
            base_time_str = str(_cached_config.get("report_gen_time", "08:00")).strip()
            base_dt = datetime.strptime(base_time_str, "%H:%M")
            _cached_base_time = base_time_str
            _cached_weekly_time = (base_dt + timedelta(minutes=10)).strftime("%H:%M")
            _cached_monthly_time = (base_dt + timedelta(minutes=20)).strftime("%H:%M")
        return _cached_config

    try:
        init_config = _load_config_if_changed()
        print(f"🚀 [AI Analyst] 시스템 가동 - 기준 시각: {init_config.get('report_gen_time', '08:00')} (KST)")
    except Exception as e:
        print(f"❌ 초기 설정 로드 실패: {e}")

    init_processed_cache()

    while True:
        try:
            now_kst = get_now_kst()
            current_ts = time.time()
            current_config = _load_config_if_changed()
            
            auto_gen_enabled = current_config.get("report_auto_gen", False)
            current_time_str = now_kst.strftime("%H:%M")
            
            # 예약 시각 (설정 변경 시에만 재계산됨)
            base_time_str = _cached_base_time
            weekly_time_str = _cached_weekly_time
            monthly_time_str = _cached_monthly_time

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

            if time_since_last >= update_interval_sec or first_run:
                print(f"📡 [{now_kst.strftime('%H:%M:%S')}] 뉴스/별도지표 수집 엔진 가동 (주기: {update_interval_min}분)")
                
                # 🎯 [NEW] 시장 데이터(KRX, Global, Fed) 기동 시간 / 휴일 판별 자동 수집
                need_krx = first_run or is_kr_market_open()
                need_us = first_run or is_us_market_open()

                print(f"📊 [{now_kst.strftime('%H:%M:%S')}] 시장 데이터 갱신 점검 (첫실행: {first_run}, KRX수집: {need_krx}, US수집: {need_us})...")
                try:
                    if need_krx:
                        get_krx_summary_raw(ignore_cache=True)
                    
                    if need_us:
                        get_global_financials_raw(ignore_cache=True, fetch_type="all") # 주식 포함 전체
                    else:
                        get_global_financials_raw(ignore_cache=True, fetch_type="non_equities") # 환율/원자재만
                    
                    get_fed_liquidity_raw()     # Fed (FRED)
                except Exception as e:
                    print(f"⚠️ 시장 데이터 자동 수집 중 오류: {e}")

                feeds = current_config.get("feeds", [])
                g_exc_str = current_config.get('global_exclude', "")  # 루프 밖에서 한 번만 가져옴
                
                new_saved = 0
                for feed in feeds:
                    try:
                        parsed = feedparser.parse(feed['url'])
                        
                        feed_new = 0
                        for entry in parsed.entries[:50]:
                            if not check_news_filter(entry.title, g_exc_str):
                                continue
                            if save_file(entry, feed['name']):
                                feed_new += 1
                                new_saved += 1
                        if feed_new > 0:
                            print(f"   └─ {feed['name']}: {feed_new}개 신규 저장")
                    except Exception as e:
                        print(f"   └─ ❌ {feed.get('name')} 오류: {e}")
                
                print(f"✅ [{now_kst.strftime('%H:%M:%S')}] 수집 완료 (총 {new_saved}개 신규 확보)")
                
                # 파일 정리 (기간 만료 및 개수 초과 삭제)
                cleanup_old_files(min(current_config.get("retention_days", 3), 3))
                
                last_news_time = current_ts
                first_run = False
            else:
                # 매 분마다 정기 생존 신고 로그 (선택 사항)
                if now_kst.minute % 5 == 0: # 5분마다 출력
                    print(f"💤 [{now_kst.strftime('%H:%M:%S')}] 대기 중... (다음 뉴스 수집까지 {int(next_in/60)}분 남음)")

        except Exception as e: 
            print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] 루프 치명적 에러: {e}")
            
        time.sleep(60)
