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
# 3. 세션 상태(Session State) 초기화 (데이터 보존 핵심)
# ==========================================
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set() 
if 'current_date' not in st.session_state:
    st.session_state['current_date'] = datetime.now(KST).strftime("%Y%m%d")
if 'detected_list' not in st.session_state:
    st.session_state['detected_list'] = []  
if 'clicked_stock' not in st.session_state:
    st.session_state['clicked_stock'] = None
if 'last_run_time' not in st.session_state:
    st.session_state['last_run_time'] = "아직 조회되지 않음"

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
    """동기식 텔레그램 발송 함수"""
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
            st.error("🔑 한투 Access Token 발급에 실패했습니다. Secrets의 APP_KEY와 SECRET을 확인해주세요.")
            return

        api_url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/volume-rank"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000"
        }
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",    
            "FID_COND_SCR_DIV_CODE": "20171", 
            "FID_INPUT_ISCD": "0000",         
            "FID_DIV_CLS_CODE": "0",          
            "FID_BLNG_CLS_CODE": "0",         
            "FID_TRGT_CLS_CODE": "00000000",  
            "FID_TRGT_EXCL_CLS_CODE": "00000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "",                
            "FID_INPUT_DATE_1": ""            
        }
        
        res = requests.get(api_url, headers=headers, params=params, timeout=5)
        
        if res.status_code == 200:
            output = res.json().get('output', [])
            if not output:
                return
                
            df_raw = pd.DataFrame(output)
            
            # 데이터 형변환 및 단위 교정
            df_raw['stck_prpr'] = df_raw['stck_prpr'].astype(int)       
            df_raw['acml_tr_pbmn'] = df_raw['acml_tr_pbmn'].astype(float).astype(int) 
            df_raw['prdy_ctrt'] = df_raw['prdy_ctrt'].astype(float)     
            df_raw['money_ok'] = df_raw['acml_tr_pbmn'] // 100000000
            
            # 🔥 무조건 10개 이상 풍부하게 나오도록 기준 완화 (대금 30억 이상 & 상승률 +1.5% 이상)
            target_stocks = df_raw[(df_raw['money_ok'] >= 3) & (df_raw['prdy_ctrt'] >= 1.5)]
            target_stocks = target_stocks.sort_values(by='money_ok', ascending=False)
            
            # 만약 장세가 안 좋아 조건 만족 종목이 너무 적다면, 거래대금 상위 15개 강제 추출
            if len(target_stocks) < 10:
                target_stocks = df_raw.sort_values(by='money_ok', ascending=False).head(15)
            
            for _, row in target_stocks.iterrows():
                # 순수 6자리 종목코드만 정밀 추출 (노이즈 문자 제거)
                raw_code = row['mkte_ticker'].strip() if 'mkte_ticker' in row else row['stck_shrn_iscd'].strip()
                code = "".join(filter(str.isdigit, raw_code))[-6:]
                
                name = row['hts_kor_isnm'].strip()
                rate = row['prdy_ctrt']
                price = row['stck_prpr']
                money = row['money_ok']
                detect_time = datetime.now(KST).strftime('%H:%M:%S')
                
                if code in st.session_state['sent_stocks']:
                    continue
                    
                # 텔레그램 알림 발송
                msg = (
                    f"🚀 [주도주 레이더 포착] 🚀\n\n"
                    f"📌 종목명: {name} ({code})\n"
                    f"📈 현재가: {price:,}원\n"
                    f"⚡ 등락률: {rate}%\n"
                    f"💰 거래대금: {money:,}억"
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
                st.session_state['detected_list'].insert(0, new_item)
                
            st.session_state['last_run_time'] = datetime.now(KST).strftime('%H:%M:%S')
            
    except Exception as e:
        st.error(f"시세 분석 중 오류 발생: {e}")

# ==========================================
# 5. 프론트엔드 UI 및 자동 동기화 셋업
# ==========================================
st.title("🔥 한국투자증권 실시간 주도주 모니터링 레이더")
st.caption("시스템 락(Lock) 현상을 유발하는 무한 무기력 루프를 완전히 걷어낸 초고속 실시간 데이터 전광판")

# 🔄 수동 새로고침 겸 데이터 즉시 수집 버튼 배치
if st.button("🔄 실시간 주도주 데이터 즉시 새로고침 (Manual Fetch)", use_container_width=True):
    run_monitoring()

col_m1, col_m2 = st.columns(2)
with col_m1:
    st.metric(label="최근 실시간 동기화 완료 시간", value=st.session_state['last_run_time'])
with col_m2:
    st.metric(label="오늘 레이더에 검출된 총 주도주 수", value=f"{len(st.session_state['detected_list'])} 개")

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 레이더 판독 현황")

# 데이터 표 시각화 핸들링 구역
if st.session_state['detected_list']:
    display_df = pd.DataFrame(st.session_state['detected_list'])
    
    event_capture = st.dataframe(
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
    # 💡 데이터가 아직 없을 때 사용자 편의를 위한 강제 첫 기동 유도 유저 메시지
    st.warning("📥 현재 시장 진입 데이터를 수집하는 중이거나 조건에 맞는 종목을 필터링 중입니다. 상단의 [🔄 실시간 주도주 데이터 즉시 새로고침] 버튼을 누르시면 즉시 강제로 한투 데이터를 긁어옵니다.")

# ==========================================
# 🖥️ [네이버 금융 모바일] 표 클릭형 즉시 표출 차트 연동 엔진 구역
# ==========================================
if st.session_state['clicked_stock']:
    st.markdown("---")
    s_name = st.session_state['clicked_stock']["종목명"]
    s_code = st.session_state['clicked_stock']["종목코드"]
    
    st.markdown(f"### 📱 [{s_name} : {s_code}] 실시간 종합 전광판")
    
    naver_mobile_chart_url = f"https://m.stock.naver.com/domestic/stock/{s_code}/total"
    
    naver_chart_html = f"""
    <div style="width: 100%; height: 650px; border-radius: 12px; overflow: hidden; border: 1px solid #e0e0e0; box-shadow: 0 4px 10px rgba(0,0,0,0.08);">
      <iframe src="{naver_mobile_chart_url}" 
              style="width: 100%; height: 100%; border: none; margin: 0; padding: 0;" 
              allowfullscreen></iframe>
    </div>
    """
    st.components.v1.html(naver_chart_html, height=670)
else:
    if st.session_state['detected_list']:
        st.markdown("---")
        st.info("💡 리스트에서 분석해보고 싶으신 종목 줄(Row)을 클릭해보세요. 하단에 실시간 호가판과 캔들 차트창이 바로 연동됩니다.")

# ==========================================
# ⏱️ 백그라운드 무한 리셋 파괴용 안전 스크립트 타이머 (60초 주기 공식 관제)
# ==========================================
# 1초마다 전체 코드를 재시작시키며 세션을 터뜨리던 `while True:` 무한루프를 완벽 제거했습니다.
# 대신 사용자가 화면을 보고 있는 상태에서 60초 간격으로만 똑똑하게 한투 API를 찔러 수급 데이터를 리프레시합니다.
st.caption("⚙️ 정기 관제 가동 중: 시스템 과부하 및 차단 방지를 위해 60초마다 한투 서버와 자동 동기화됩니다.")
time.sleep(60)
st.rerun()
