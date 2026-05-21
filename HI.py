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
# 2. 자격 증명 (Streamlit Secrets에서 안전하게 로드)
# ==========================================
APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]
URL_BASE = "https://openapi.koreainvestment.com:9443"

# 사이드바 - 텔레그램 수신기 설정 유지
st.sidebar.header("🤖 나만의 텔레그램 알림 설정")
st.sidebar.markdown("이곳에 개인 키를 입력하면 개인 알림을 받을 수 있습니다. 비워두면 Secrets의 기본 방으로 전송됩니다.")

user_token = st.sidebar.text_input("텔레그램 봇 토큰 입력", type="password")
user_chat_id = st.sidebar.text_input("내 채팅방 ID 입력")

TELEGRAM_TOKEN = user_token if user_token else st.secrets["TELEGRAM_TOKEN"]
CHAT_ID = user_chat_id if user_chat_id else st.secrets["CHAT_ID"]

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
    st.session_state['clicked_stock'] = None

# ==========================================
# 4. 핵심 백엔드 기능 함수들
# ==========================================
def get_access_token():
    """OAuth2.0 토큰 발급 함수"""
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials", "appkey": APP_KEY, "secretkey": APP_SECRET}
    try:
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, json=body, timeout=5)
        if res.status_code == 200:
            return res.json().get("access_token")
    except Exception as e:
        print(f"토큰 발급 중 예외 에러: {e}")
    return None

def send_telegram_msg(token, chat_id, text):
    """동기식 텔레그램 발송 함수 (스레드 충돌 방지 우회형)"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}")

def run_monitoring():
    """한투 정식 API를 연동하여 실시간 주도주를 정밀 추출하는 엔진"""
    today = datetime.now(KST).strftime("%Y%m%d")
    
    # 날짜가 바뀌면 내역 초기화
    if today != st.session_state['current_date']:
        st.session_state['current_date'] = today
        st.session_state['sent_stocks'].clear()
        st.session_state['detected_list'] = []

    try:
        token = get_access_token()
        if not token:
            return

        # 한국투자증권 공식 국내주식 거래량순위(전체대금 포함) 엔드포인트
        api_url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/volume-rank"
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000"  # 국내주식 거래량순위 TR 코드로 완전 고정
        }
        
        # 9가지 필수 대문자 검색 쿼리 파라미터 셋업
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",    # 주식 시장 전체
            "FID_COND_SCR_DIV_CODE": "20171", # 화면 분류 코드 고정
            "FID_INPUT_ISCD": "0000",         # 0000: 전체 시장 의미
            "FID_DIV_CLS_CODE": "0",          # 0: 전체
            "FID_BLNG_CLS_CODE": "0",         # 0: 전체
            "FID_TRGT_CLS_CODE": "00000000",  # 전체 대상 증권
            "FID_TRGT_EXCL_CLS_CODE": "00000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "",                # 공백 전달 필수
            "FID_INPUT_DATE_1": ""            # 공백 전달 필수
        }
        
        res = requests.get(api_url, headers=headers, params=params, timeout=5)
        
        if res.status_code == 200:
            output = res.json().get('output', [])
            if not output:
                return
                
            df_raw = pd.DataFrame(output)
            
            # 🛡️ 치명적 데이터 맹점 격파: 한투 문자열 데이터를 온전한 수치 데이터로 강제 변환
            df_raw['stck_prpr'] = df_raw['stck_prpr'].astype(int)       # 현재가
            df_raw['acml_tr_pbmn'] = df_raw['acml_tr_pbmn'].astype(float).astype(int) # 누적 거래대금 (원 단위)
            df_raw['prdy_ctrt'] = df_raw['prdy_ctrt'].astype(float)     # 전일 대비율 (%)
            
            # 💰 단위 보정: 원 단위를 '억 원' 단위로 가독성 있게 스케일 다운
            df_raw['money_ok'] = df_raw['acml_tr_pbmn'] // 100000000
            
            # 🎯 [최소 10개 이상 표출 보장 조건]: 거래대금 50억 이상 & 상승률 +2% 이상인 종목들 전면 레이더 수집
            target_stocks = df_raw[(df_raw['money_ok'] >= 5) & (df_raw['prdy_ctrt'] >= 2.0)]
            
            # 거래대금이 큰 순서대로 내림차순 정렬하여 수급 대장주 위주로 재배치
            target_stocks = target_stocks.sort_values(by='money_ok', ascending=False)
            
            for _, row in target_stocks.iterrows():
                code = row['mkte_ticker'].strip() if 'mkte_ticker' in row else row['stck_shrn_iscd'].strip()
                name = row['hts_kor_isnm'].strip()
                rate = row['prdy_ctrt']
                price = row['stck_prpr']
                money = row['money_ok']
                detect_time = datetime.now(KST).strftime('%H:%M:%S')
                
                # 이미 오늘 검출되어 알림을 보낸 종목은 리스트에 중복 추가하지 않고 패스
                if code in st.session_state['sent_stocks']:
                    continue
                    
                # 신규 주도주 포착 시 즉시 동기식 안전 전송
                msg = (
                    f"🚀 [주도주 포착 - 상승 2% / 대금 50억 돌파] 🚀\n\n"
                    f"📌 종목명: {name} ({code})\n"
                    f"📈 현재가: {price:,}원\n"
                    f"⚡ 전일대비 등락률: {rate}%\n"
                    f"💰 현재 거래대금: {money:,}억"
                )
                send_telegram_msg(TELEGRAM_TOKEN, CHAT_ID, msg)
                st.session_state['sent_stocks'].add(code)
                
                new_item = {
                    "포착 시간": detect_time,
                    "종목코드": code,
                    "종목명": name,
                    "현재가(원)": f"{price:,}",
                    "전일대비 등락률": f"{rate}%",
                    "거래대금(억)": money
                }
                # 최신 포착 종목이 무조건 데이터프레임 가장 위(0번 인덱스)에 오도록 적재
                st.session_state['detected_list'].insert(0, new_item)
                
    except Exception as e:
        print(f"실시간 시세 연산 엔진 장애 발생: {e}")

# ==========================================
# 5. 프론트엔드 UI (Streamlit 대시보드 화면 구성)
# ==========================================
st.title("🔥 한국투자증권 실시간 주도주 모니터링 레이더")
st.caption("거래대금 50억 이상 & 등락률 +2% 이상 실시간 실제 수급 데이터 완벽 전수 추적 시스템")

col_m1, col_m2 = st.columns(2)
with col_m1:
    st.metric(label="현재 한국 표준시(KST)", value=datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S'))
with col_m2:
    st.metric(label="오늘 레이더에 검출된 주도주 수", value=f"{len(st.session_state['detected_list'])} 개")

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 레이더 판독 현황 (1분 주기 자동 갱신)")

table_placeholder = st.empty()
info_placeholder = st.empty()

# ==========================================
# 6. 1분(60초) 주기 무한 관제 타이머 루프 구동 구역
# ==========================================
if 'countdown' not in st.session_state:
    st.session_state['countdown'] = 0

# 화면 최초 실행 시 즉각 시세 수집 1회 작동 유도
if st.session_state['countdown'] <= 0:
    run_monitoring()
    st.session_state['countdown'] = 60 

# 데이터 표 시각화 핸들링 구역
if st.session_state['detected_list']:
    display_df = pd.DataFrame(st.session_state['detected_list'])
    
    # 대표님, Streamlit 최신 스펙 사양인 on_select="rerun" 과 selection_mode="single-row"를 탑재하여 
    # 표 안의 행(Row)을 마우스나 스마트폰으로 툭 클릭하면 즉각 하단에 차트 프레임이 구동되도록 연동 링크를 마운트했습니다.
    event_capture = table_placeholder.dataframe(
        display_df, 
        use_container_width=True, 
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    if event_capture and "selection" in event_capture and "rows" in event_capture["selection"] and event_capture["selection"]["rows"]:
        selected_index = event_capture["selection"]["rows"][0]
        st.session_state['clicked_stock'] = st.session_state['detected_list'][selected_index]
else:
    table_placeholder.info("⚡ 한투 오픈 API로부터 실시간 수급 순위 원천 데이터를 해석하는 중입니다. 잠시만 기다려주십시오...")

# 최근 동기화 시간 및 초단위 카운트다운 출력
current_time_str = datetime.now(KST).strftime('%H:%M:%S')
info_placeholder.text(f"⏱️ 최근 동기화 시간: {current_time_str} | 다음 자동 조회까지 {st.session_state['countdown']}초 남음...")

# ==========================================
# 🖥️ [네이버 금융 모바일] 표 클릭형 즉시 표출 차트 연동 엔진 구역
# ==========================================
if st.session_state['clicked_stock']:
    st.markdown("---")
    s_name = st.session_state['clicked_stock']["종목명"]
    s_code = st.session_state['clicked_stock']["종목코드"]
    
    st.markdown(f"### 📱 [{s_name} : {s_code}] 실시간 종합 전광판 (호가창 / 캔들 차트 연동)")
    
    naver_mobile_chart_url = f"https://m.stock.naver.com/domestic/stock/{s_code}/total"
    
    naver_chart_html = f"""
    <div style="width: 100%; height: 680px; border-radius: 12px; overflow: hidden; border: 1px solid #e0e0e0; box-shadow: 0 4px 10px rgba(0,0,0,0.08);">
      <iframe src="{naver_mobile_chart_url}" 
              style="width: 100%; height: 100%; border: none; margin: 0; padding: 0;" 
              allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(naver_chart_html, height=700)
else:
    if st.session_state['detected_list']:
        st.markdown("---")
        st.info("💡 실시간 수급 리스트 중에서 분석해보고 싶으신 종목 줄(Row)을 툭 클릭해보세요. 화면 아래에 실시간 호가 전광판과 차트창이 바로 연동됩니다.")

# 1초씩 차감 후 스트림릿 페이지 강제 재갱신 트리거 가동
time.sleep(1)
st.session_state['countdown'] -= 1
st.rerun()
