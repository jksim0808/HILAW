import requests
import json
import pandas as pd
import time
from datetime import datetime
import pytz
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정 (넓은 화면 모드)
# ==========================================
st.set_page_config(page_title="한투 주도주 감시봇", layout="wide")

# 한국 표준시(KST) 타임존 정의
KST = pytz.timezone('Asia/Seoul')

# ==========================================
# 2. API 자격증명 및 텔레그램 암호 설정 (Secrets 자동 감지)
# ==========================================
# 한국투자증권 API 키는 대표님의 Secrets 저장소에서 안전하게 연동해 옵니다.
APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]
URL_BASE = "https://openapi.koreainvestment.com:9443"

# 텔레그램 설정: 사이드바 입력값을 우선으로 하되, 비어 있으면 Secrets 백업값을 활용합니다.
st.sidebar.header("🤖 나만의 텔레그램 알림 설정")
st.sidebar.markdown("이곳에 본인의 키를 입력하면 개인 알림을 받을 수 있습니다. 비워둘 경우 Secrets에 저장된 채널로 발송됩니다.")

user_token = st.sidebar.text_input("텔레그램 봇 토큰 입력", type="password", help="BotFather에게 받은 토큰을 넣으세요.")
user_chat_id = st.sidebar.text_input("내 채팅방 ID 입력", help="@userinfobot에게 받은 ID(숫자)를 넣으세요.")

TELEGRAM_TOKEN = user_token if user_token else st.secrets["TELEGRAM_TOKEN"]
CHAT_ID = user_chat_id if user_chat_id else st.secrets["CHAT_ID"]

# 🚨 장외 시간 테스트 모드 스위치 추가 (대표님의 완벽한 주말/야간 테스트 지원)
st.sidebar.markdown("---")
st.sidebar.header("🛠️ 시스템 테스트 환경")
market_time_override = st.sidebar.checkbox(
    "🚨 장외 시간 테스트 모드", 
    value=False, 
    help="장 운영 시간 외에도 텔레그램 알림과 실시간 표 연동이 완벽하게 가동되는지 임의로 가상 주도주를 생성해 발송합니다."
)

# 📱 사용자 전용 접이식 텔레그램 가이드북
st.sidebar.markdown("---")
with st.sidebar.expander("ℹ️ 텔레그램 토큰 / ID 만드는 방법"):
    st.markdown("""
    **1. 봇 토큰(TOKEN) 만들기**
    1. 텔레그램에 **@BotFather** 검색 후 **[시작]**
    2. 채팅창에 **`/newbot`** 입력
    3. 봇 이름 입력 (예: `내주식비서`)
    4. 봇 아이디 입력 (영어 필수, 끝이 반드시 **`_bot`**으로 끝나야 함)
    5. 생성 완료 후 **`Use this token...`** 아래의 긴 문자열 복사!
    
    ---
    
    **2. 내 채팅방 ID 찾기**
    1. ⚠️ **중요:** 방금 내가 만든 봇을 검색해 들어가서 **[시작]**을 먼저 꼭 누르세요! (선톡 필수)
    2. 텔레그램에 **@userinfobot** 검색 후 **[시작]**
    3. 즉시 나타나는 정보 중 **`Id: 9~10자리 숫자`**를 복사!
    """)

# ==========================================
# 3. 세션 상태(Session State) 초기화
# ==========================================
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set() 
if 'current_date' not in st.session_state:
    st.session_state['current_date'] = datetime.now(KST).strftime("%Y%m%d")
if 'detected_list' not in st.session_state:
    st.session_state['detected_list'] = []  
if 'clicked_stock' not in st.session_state:
    st.session_state.clicked_stock = None
if 'api_access_token' not in st.session_state:
    st.session_state.api_access_token = None

# ==========================================
# 4. 핵심 백엔드 기능 함수들 (API 캐싱 & 100억 기준 연산)
# ==========================================
def get_access_token():
    """OAuth2.0 접근 토큰(Access Token) 발급 - 세션 캐싱 적용으로 분당 발급 제한 우회"""
    if st.session_state.api_access_token:
        return st.session_state.api_access_token

    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}
    try:
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, data=json.dumps(body), timeout=5)
        if res.status_code == 200:
            token = res.json().get("access_token")
            st.session_state.api_access_token = token
            return token
    except Exception as e:
        st.error(f"한투 서버 토큰 발행 실패: {e}")
    return None

def send_telegram_msg_sync(token, chat_id, text):
    """[동기식 연동] Streamlit 프로세스 락 현상을 완벽하게 방지하는 동기 통신 모듈"""
    if not token or not chat_id:
        return
    url = f"https://api.telegram.com/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def check_market_time():
    """장운영 시간 진입 판별기"""
    now = datetime.now(KST)
    if now.weekday() >= 5: 
        return False
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return start_time <= now <= end_time

def inject_mock_leading_stock():
    """장외 시간 테스트를 위한 가상 주도주 데이터 임의 주입 모듈"""
    import random
    mock_names = ["현대로템", "한화에어로스페이스", "알테오젠", "SK하이닉스", "삼성전자", "기아", "현대차", "HD현대일렉트릭"]
    mock_codes = ["064350", "012450", "196170", "000660", "005930", "000270", "005380", "043200"]
    
    idx = random.randint(0, len(mock_names)-1)
    name = mock_names[idx]
    code = mock_codes[idx]
    
    # 이미 오늘 감지된 적이 있으면 주입 방지
    if code in st.session_state['sent_stocks']:
        return
        
    vol = round(random.uniform(3.5, 12.0), 2)
    price = random.randint(15, 250) * 1000
    money = random.randint(105, 380)
    detect_time = datetime.now(KST).strftime('%H:%M:%S')
    
    msg = (
        f"🚨 [가상 주도주 테스트 포착 - 변동폭 3% / 거래대금 100억 돌파] 🚨\n\n"
        f"📌 종목명: {name} ({code})\n"
        f"📈 현재가: {price:,}원\n"
        f"⚡ 당일 고저 변동폭: {vol}%\n"
        f"💰 현재 거래대금: {money:,}억"
    )
    
    # 텔레그램 전송
    send_telegram_msg_sync(TELEGRAM_TOKEN, CHAT_ID, msg)
    st.session_state['sent_stocks'].add(code)
    
    new_item = {
        "포착 시간": detect_time,
        "종목코드": code,
        "종목명": name,
        "현재가(원)": f"{price:,}",
        "하루 변동폭": f"{vol}%",
        "거래대금(억)": money
    }
    st.session_state['detected_list'].insert(0, new_item)

def run_monitoring():
    """실시간 주도주 스크리닝 연산 파이프라인 (100억 원 기준 적용)"""
    today = datetime.now(KST).strftime("%Y%m%d")
    
    # 일자 변경 시 모니터링 기록 안전 리셋
    if today != st.session_state['current_date']:
        st.session_state['current_date'] = today
        st.session_state['sent_stocks'].clear()
        st.session_state['detected_list'] = []

    # 장외 시간 및 오버라이드 유무 판별
    is_market_open = check_market_time()
    
    if not is_market_open and not market_time_override:
        return

    # 만약 테스트 모드이고 장외 시간이라면 실시간 가상데이터 주입
    if market_time_override and not is_market_open:
        inject_mock_leading_stock()
        return

    try:
        token = get_access_token()
        if not token:
            st.sidebar.error("⚠️ 한투 API 토큰을 발급받지 못했습니다. Secrets 설정을 점검하십시오.")
            return

        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000" 
        }
        
        # [정교화 보완] 한국투자증권 거래량 순위(거래대금 포함) TR_ID 공식 규격 파라미터 매칭
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000",
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111",
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": "",
            "FID_INPUT_PRICE_2": "",
            "FID_VOL_CNT": "",
            "FID_INPUT_DATE_1": ""
        }
        
        # 한국투자증권 장중 거래대금 랭킹 데이터 수집 (공식 엔드포인트 수정 완료)
        res = requests.get(f"{URL_BASE}/uapi/domestic-stock/v1/quotations/volume-rank", headers=headers, params=params, timeout=10)
        
        if res.status_code != 200:
            return
            
        res_json = res.json()
        if res_json.get("rt_cd") != "0":
            st.sidebar.error(f"⚠️ KIS API 오류: {res_json.get('msg1')}")
            return
            
        data = res_json.get('output', [])
        
        if not data:
            return

        df = pd.DataFrame(data)
        
        # 문자열로 반환되는 KIS 수치들을 정밀 숫자형으로 캐스팅
        df['stck_prpr'] = pd.to_numeric(df['stck_prpr'], errors='coerce').fillna(0).astype(int)
        df['stck_hgpr'] = pd.to_numeric(df['stck_hgpr'], errors='coerce').fillna(0).astype(int)
        df['stck_lwpr'] = pd.to_numeric(df['stck_lwpr'], errors='coerce').fillna(0).astype(int)
        
        # acml_tr_pbmn (누적거래대금): "원" 단위를 1억 원 단위로 정량 스케일링 보정
        df['acml_tr_pbmn'] = pd.to_numeric(df['acml_tr_pbmn'], errors='coerce').fillna(0).astype(float) / 100000000
        
        # 당일 고저 변동폭 산출
        df['volatility'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)
        
        # 💡 스크리닝 필터 기준: 거래대금 100억 원 이상 & 고저 변동폭 3% 이상
        target_stocks = df[(df['acml_tr_pbmn'] >= 100) & (df['volatility'] >= 3.0)]
        
        # 거래대금 최상위 기조로 정렬
        target_stocks = target_stocks.sort_values(by='acml_tr_pbmn', ascending=False)
        
        for _, row in target_stocks.iterrows():
            raw_code = row.get('mksc_shrn_iscd', row.get('stck_shrn_iscd', row.get('mkte_ticker', '')))
            code = ''.join(filter(str.isdigit, raw_code))[:6] # 6자리 순수 코드로 정제
            name = row.get('hts_kor_isnm', '미확인종목')
            vol = row['volatility']
            price = row['stck_prpr']
            money = int(row['acml_tr_pbmn'])
            detect_time = datetime.now(KST).strftime('%H:%M:%S')
            
            if not code or code in st.session_state['sent_stocks']:
                continue
                
            # 💡 텔레그램 메시지 발송
            msg = (
                f"🚀 [주도주 포착 - 변동폭 3% / 거래대금 100억 돌파] 🚀\n\n"
                f"📌 종목명: {name} ({code})\n"
                f"📈 현재가: {price:,}원\n"
                f"⚡ 당일 고저 변동폭: {vol}%\n"
                f"💰 현재 거래대금: {money:,}억"
            )
            
            # 동기식 안전 전송
            send_telegram_msg_sync(TELEGRAM_TOKEN, CHAT_ID, msg)
            st.session_state['sent_stocks'].add(code)
            
            new_item = {
                "포착 시간": detect_time,
                "종목코드": code,
                "종목명": name,
                "현재가(원)": f"{price:,}",
                "하루 변동폭": f"{vol}%",
                "거래대금(억)": money
            }
            st.session_state['detected_list'].insert(0, new_item)
            
    except Exception as e:
        print(f"데이터 연산 중 에러 발생: {e}")

# ==========================================
# 5. 프론트엔드 UI 및 대시보드 출력 구역
# ==========================================
st.title("🔥 한국투자증권 실시간 주도주 대시보드 (3% / 100억)")
st.caption("실시간 수급 모니터링 관제반 + 텔레그램 동기식 무유출 알림 연동")

col1, col2 = st.columns(2)
with col1:
    st.metric(label="현재 한국 표준시(KST)", value=datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
with col2:
    st.metric(label="오늘 레이더에 걸린 총 종목 수", value=f"{len(st.session_state['detected_list'])} 개")

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 포착 리스트 (1분 주기)")
st.caption("💡 아래 리스트에서 관심 있는 **종목의 행(Row)을 툭 클릭**하시면 화면 이동 없이 즉시 하단에 네이버 호가/차트 전광판이 실시간으로 연동됩니다.")

table_placeholder = st.empty()
info_placeholder = st.empty()

# ==========================================
# 6. 1분(60초) 주기 백그라운드 타이머 루프 및 인터랙티브 뷰포트
# ==========================================
if 'countdown' not in st.session_state:
    st.session_state['countdown'] = 0

# 타이머 마진 진입에 따른 모니터링 가동
if st.session_state['countdown'] <= 0:
    run_monitoring()
    st.session_state['countdown'] = 60 

# 데이터프레임 렌더링 및 선택 이벤트 바인딩
if st.session_state['detected_list']:
    display_df = pd.DataFrame(st.session_state['detected_list'])
    
    # 💡 고정된 위젯 키(Key)를 입력하여, 새로고침 루프 중에도 마우스 선택 상태가 풀려 증발하지 않도록 보정
    event = table_placeholder.dataframe(
        display_df, 
        use_container_width=True, 
        hide_index=True, 
        on_select="rerun", 
        selection_mode="single-row",
        key="detected_stocks_table_viewer"
    )
    
    if event and event.get("selection") and event["selection"].get("rows"):
        selected_row_idx = event["selection"]["rows"][0]
        st.session_state.clicked_stock = display_df.iloc[selected_row_idx].to_dict()
else:
    table_placeholder.info("아직 조건(변동폭 3% 이상 & 거래대금 100억 이상)을 만족하는 주도주가 없습니다. 시장을 실시간 감시 중입니다...")

info_placeholder.text(f"⏱️ 최근 동기화 시간: {datetime.now(KST).strftime('%H:%M:%S')} | 다음 자동 조회까지 {st.session_state['countdown']}초 남음...")

# ==========================================
# 7. 하단 실시간 네이버 모바일 종합 전광판 상시 표출 구역
# ==========================================
if st.session_state.clicked_stock:
    st.markdown("---")
    s_name = st.session_state.clicked_stock["종목명"]
    s_code_raw = st.session_state.clicked_stock["종목코드"]
    s_code = ''.join(filter(str.isdigit, s_code_raw))[:6] # 오직 숫자로만 구성된 6자리 코드 보정
    
    st.markdown(f"### 📊 [{s_name} : {s_code}] 실시간 종합 차트")
    
    naver_mobile_chart_url = f"https://m.stock.naver.com/domestic/stock/{s_code}/total"
    
    # 클릭과 즉시 대시보드 내부에 직접 임베딩하여 튕김과 거부 현상을 완전 정화합니다.
    naver_chart_html = f"""
    <div style="width: 100%; height: 650px; border-radius: 12px; overflow: hidden; border: 1px solid #e0e0e0; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
      <iframe src="{naver_mobile_chart_url}" 
              style="width: 100%; height: 100%; border: none; margin: 0; padding: 0;" 
              allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(naver_chart_html, height=670)

# 자동 카운트다운 리런 루프 작동
time.sleep(1)
st.session_state['countdown'] -= 1
st.rerun()
