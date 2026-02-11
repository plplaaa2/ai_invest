
# --- [1. 통합 지표 및 API 설정] ---
# A. Polling API 및 일반 API (지수 및 매크로)
MARKET_CONFIG = {
    "KOSPI": "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI",
    "KOSDAQ": "https://polling.finance.naver.com/api/realtime/domestic/index/KOSDAQ",
    "K200_FUT": "https://polling.finance.naver.com/api/realtime/domestic/index/FUT",
    "DJI": "https://polling.finance.naver.com/api/realtime/worldstock/index/.DJI",
    "NASDAQ": "https://polling.finance.naver.com/api/realtime/worldstock/index/.IXIC",
    "SOX": "https://polling.finance.naver.com/api/realtime/worldstock/index/.SOX",
    "SP500": "https://polling.finance.naver.com/api/realtime/worldstock/index/.INX",
    "VIX": "https://polling.finance.naver.com/api/realtime/worldstock/index/.VIX",
    "DXY": "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=.DXY&page=1",
    "US_GOLD": "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=GCcv1&page=1",
    "KOR_GOLD": "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&page=1",
    "WTI": "https://m.stock.naver.com/front-api/marketIndex/prices?category=energy&reutersCode=CLcv1&page=1",
    "NAT_GAS": "https://m.stock.naver.com/front-api/marketIndex/prices?category=energy&reutersCode=NGcv1&page=1",
    "COPPER": "https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=HGcv1&page=1",
    "BTC": "https://m.stock.naver.com/front-api/crypto/otherExchange?nfTicker=BTC&excludeExchange=UPBIT",
    "KOR_RATE": "https://m.stock.naver.com/front-api/marketIndex/standardInterest?category=standardInterest&reutersCode=KOR&page=1",
    "USA_RATE": "https://m.stock.naver.com/front-api/marketIndex/standardInterest?category=standardInterest&reutersCode=USA&page=1",
    "US_2Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=US2YT%3DRR&page=1",
    "US_10Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=US10YT%3DRR&page=1",
    "US_30Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=US30YT%3DRR&page=1",
    "KR_2Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=KR2YT%3DRR&page=1",
    "KR_10Y": "https://m.stock.naver.com/front-api/marketIndex/prices?category=bond&reutersCode=KR10YT%3DRR&page=1"
}

# B. HTML Table 지표 (환율 회차별 시세 - 신규)
TABLE_CONFIG = {
    "USD_KRW": "https://finance.naver.com/marketindex/exchangeDegreeCountQuote.naver?marketindexCd=FX_USDKRW",
    "JPY_KRW": "https://finance.naver.com/marketindex/exchangeDegreeCountQuote.naver?marketindexCd=FX_JPYKRW",
    "CNY_KRW": "https://finance.naver.com/marketindex/exchangeDegreeCountQuote.naver?marketindexCd=FX_CNYKRW"
}

# C. FRED 지표 (기존 지표 + 유동성 정밀 진단 지표 통합본)
FRED_CONFIG = {
    # --- 유동성 및 연준 장부 ---
    "RRP": "RRPONTSYD",          # 역레포 잔고 (유동성 완충지대)
    "RESERVES": "TOTRESNS",      # 지급준비금 (은행 시스템 내 실질 유동성)
    "US_TGA": "WTREGEN",         # 재무부 일반계정 잔액 (TGA)
    "FED_ASSETS": "WALCL",       # 연준 총자산 (QT 현황 확인용)
    "US_SRF": "RPONTSYD",        # 상시 레포 기구(SRF) 이용액
    "BTFP": "H41RESPALDKNWW",    # 은행 기간대출 프로그램 (비상 자금 지원)
    
    # --- 금리 및 통화량 ---
    "SOFR": "SOFR",              # SOFR 금리 (실질 단기자금 금리)
    "EFFR": "FEDFUNDS",          # 실효 연방기금 금리
    "US_M2": "M2SL",             # 미국 통화량 (M2)
    
    # --- 매크로 및 고용/물가 ---
    "US_GDP_NOW": "GDPNOW",      # 애틀랜타 연은 GDP Now
    "US_UNRATE": "UNRATE",       # 미국 실업률
    "US_JTSJOL": "JTSJOL",       # 구인 이직 보고서 (Jolts)
    "US_RETAIL": "RETAILIRSA",   # 소매판매
    "US_INFL_EXP": "T10YIE",     # 10년 기대인플레이션 (BEI)
    "US_CPI": "CPIAUCSL",        # 소비자물가 지수 (CPI)
    "US_CORE_CPI": "CPILFESL",   # 근원 CPI
    "US_PCE": "PCEPILFE",        # 근원 개인소비지출 (PCE)
    "US_PPI": "PPIFIS"           # 생산자물가 지수 (PPI)
}

    # 2. 표시용 이름 딕셔너리
display_names = {
    # --- 주요 지수 및 자산 ---
    "KOSPI": "코스피", "KOSDAQ": "코스닥", "NASDAQ": "나스닥", "DJI": "다우존스", "SP500": "S&P 500", 
    "SOX": "🔌 반도체(SOX)", "K200_FUT": "📉 K200 선물", "BTC": "₿ 비트코인", 

    # --- 환율 및 원자재 ---
    "USD_KRW": "💵 달러/원", "JPY_KRW": "💴 엔/원", "USD/JPY": "💴 달러/엔", "CNY_KRW": "🉐 위안/원", "DXY": "💹 달러인덱스", "KRW_NDF": "💵 역외 환율(NDF)",
    "WTI": "🛢️ 유가(WTI)", "NAT_GAS": "🔥 천연가스", "COPPER": "🏗️ 구리선물",
    "US_GOLD": "🇺🇸 국제금", "KOR_GOLD": "🇰🇷 국내금",

    # --- 금리 및 자금 시장 ---
    "KOR_RATE": "한국 기준금리", "USA_RATE": "미국 기준금리", 
    "KR_2Y": "국채 2Y", "KR_10Y": "국채 10Y", 
    "US_2Y": "🇺🇸 2Y", "US_10Y": "🇺🇸 10Y", "US_30Y": "🇺🇸 30Y", "US_10Y_FUT": "📉 미 10년국채 선물",
    "SOFR": "🏦 SOFR 금리", "EFFR": "🏛️ 실효연방금리",

    # --- 증시 수급 및 잔고 ---
    "KOR_NET_IND": "👤 개인순매수", "KOR_NET_FOR": "🌍 외인순매수", "KOR_NET_INST": "🏢 기관순매수",
    "KOR_DEPOSIT": "💰 예탁금", "KOR_CREDIT_LOAN": "💳 신용잔고",

    # --- 🏛️ 연준 유동성 (핵심 감시 지표) ---
    "FED_ASSETS": "🏦 연준 총자산", "RRP": "🌊 역레포(RRP)", "RESERVES": "💵 지급준비금",
    "US_TGA": "🛡️ 재무부(TGA)", "US_SRF": "🚨 상시레포(SRF)", "BTFP": "🚑 비상대출(BTFP)",
    "US_M2": "💸 미 M2 통화량", "VIX": "😨 공포지수(VIX)", "US_GDP_NOW": "📈 GDP Now",

    # --- 🛒 물가 및 고용 ---
    "US_UNRATE": "👷 미 실업률", "US_JTSJOL": "💼 미 구인인원", "US_RETAIL": "🛒 미 소매판매",
    "US_INFL_EXP": "🔮 기대인플레", "US_CPI": "🎯 미 CPI", "US_CORE_CPI": "💎 근원 CPI",
    "US_PCE": "🛍️ 미 PCE", "US_PPI": "🏭 미 PPI"
}

# --- 파일 상단 display_names 아래에 배치 ---
CAT_INDICES = ["KOSPI", "KOSDAQ", "DJI", "NASDAQ", "SP500", "SOX", "BTC"]
CAT_FX_CMD  = ["USD_KRW", "JPY_KRW", "DXY", "WTI", "NAT_GAS", "COPPER", "US_GOLD", "KOR_GOLD"]
CAT_RATES   = ["KOR_RATE", "USA_RATE", "KR_2Y", "KR_10Y", "US_2Y", "US_10Y", "US_30Y", "SOFR", "EFFR"]
CAT_FUNDS   = ["KOR_NET_IND", "KOR_NET_FOR", "KOR_NET_INST", "KOR_DEPOSIT", "KOR_CREDIT_LOAN"]
CAT_MACRO_1 = ["FED_ASSETS", "RRP", "RESERVES", "US_TGA", "US_SRF", "BTFP", "US_M2", "VIX", "US_GDP_NOW"]
CAT_MACRO_2 = ["US_UNRATE", "US_JTSJOL", "US_RETAIL", "US_INFL_EXP", "US_CPI", "US_CORE_CPI", "US_PCE", "US_PPI"]
CAT_MACRO   = CAT_MACRO_1 + CAT_MACRO_2
ALL_SYMBOLS = CAT_INDICES + CAT_FX_CMD + CAT_RATES + CAT_FUNDS + CAT_MACRO