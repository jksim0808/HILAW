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

# ⚡ 실전 운영망 주소 고정
URL_BASE = "https://openapi.koreainvestment.com:9443"

# ==========================================
# 2. 사이드바 - Secrets 연동 실패 대비 수동 입력창 전면 배치
# ==========================================
st.sidebar.header("🔑 실전망 자격 증명 설정")
st.sidebar.warning("💡 Secrets 변수 로드에 실패하여 사이드바 직접 입력창을 활성화했습니다. 아래에 실전 키를 넣어주십시오.")

# 안전하게 Secrets 값 긁어오되, 실패하면 빈 칸으로 처리
sec_app_key = st.secrets.get("APP_KEY", "") if st.secrets else ""
sec_app_secret = st.secrets.get("APP_SECRET", "") if st.secrets else ""

# 사이드바 입력창 배치 (보안을 위해 마스킹 처리)
user_app_key = st.sidebar.text_input("한투 APP KEY", value=sec_app_key, type="password", help="한투 실전 APP KEY를 붙여넣으세요.")
user_app_secret = st.sidebar.text_input("한투 APP SECRET", value=sec_app_secret, type="password", help="한투 실전 APP SECRET을 붙여넣으세요.")

APP_KEY = user_app_key if user_app_key else sec_app_key
APP_SECRET = user_app_secret if user_app_secret else sec_app_secret

st.sidebar.markdown("---")
st.sidebar.header("🤖 텔레그램 알림 수신기")
user_token = st.sidebar.text_input("텔레그램 봇 토큰", type="password")
user_chat_id = st.sidebar.text_input("내 채팅방 ID")

sec_tg_token = st.secrets.get("TELEGRAM_TOKEN", "") if st.secrets else ""
sec_chat_id = st.secrets.get("CHAT_ID", "") if st.secrets else ""

TELEGRAM_TOKEN = user_token if user_token else sec_tg_token
CHAT_ID = user_chat_id if user_chat_id else sec_chat_id

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
if 'last_run_time' not in st.session_state:
    st.session_state['last_run_time'] = "아직 조회되지 않음"
if 'engine_status' not in st.session_state:
    st.session_state['engine_status'] = "🔴 대기 중"

# ==========================================
# 4. 핵심 백엔드 기능 함수들
# ==========================================
def get_access_token():
    """OAuth2.0 실전망 토큰 발급 함수"""
    if not APP_KEY or not APP_SECRET:
        st.session_state['engine_status'] = "❌ 입력 대기 (사이드바에 APP KEY와 SECRET을 채워주십시오)"
        return None
        
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials", 
        "appkey": APP_KEY, 
        "secretkey": APP_SECRET
    }
    try:
        res = requests.post(f"{URL_BASE}/oauth2/tokenP", headers=headers, json=body, timeout=5)
        if res.status_code == 200:
            return res.json().get("access_token")
        else:
            st.session_state['engine_status'] = f"❌ 인증 실패 (한투 거절 코드: {res.status_code})"
    except Exception as e:
        st.session_state['engine_status'] = f"💥 토큰 발급 네트워크 통신 예외 발생"
    return None

def send_telegram_msg(token, chat_id, text):
    """동기식 텔레그램 발송 함수"""
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}")

def run_monitoring():
    """한투 실전 운영망 정식 API 연동 및 주도주 정밀 추출 엔진"""
    today = datetime.now(KST).strftime("%Y%m%d")
    
    if today != st.session_state['current_date']:
        st.session_state['current_date'] = today
        st.session_state['sent_stocks'].clear()
        st.session_state['detected_list'] = []

    try:
        token = get_access_token()
        if not token:
            return

        api_url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/volume-rank"
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000",
            "custtype": "P"
        }
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",    # J: 주식 전체 (코스피 + 코스닥)
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
            res_json = res.json()
            output = res_json.get('output', [])
            rt_msg = res_json.get('msg1', '데이터 갱신 완료').strip()
            
            if not output:
                st.session_state['engine_status'] = f"⚠️ 데이터 응답 없음 (한투 메시지: {rt_msg})"
                return
                
            df_raw = pd.DataFrame(output)
            
            # 수치 전형화 안전 형변환 처리
            df_raw['stck_prpr'] = pd.to_numeric(df_raw['stck_prpr'], errors='coerce').fillna(0).astype(int)
            df_raw['acml_tr_pbmn'] = pd.to_numeric(df_raw['acml_tr_pbmn'], errors='coerce').fillna(0).astype(float)
            df_raw['prdy_ctrt'] = pd.to_numeric(df_raw['prdy_ctrt'], errors='coerce').fillna(0).astype(float)
            df_raw['money_ok'] = (df_raw['acml_tr_pbmn'] // 100000000).astype(int)
            
            # 주도주 기본 추출 조건 필터링 (거래대금 50억 이상 & 상승률 +1.0% 이상)
            target_stocks = df_raw[(df_raw['money_ok'] >= 5) & (df_raw['prdy_ctrt'] >= 1.0)]
            
            # 검출량이 너무 적을 경우 실시간 대금 최상위 20개 종목을 무조건 판에 뿌리도록 조치
            if len(target_stocks) < 10:
                target_stocks = df_raw.sort_values(by='money_ok', ascending=False).head(20)
            else:
                target_stocks = target_stocks.sort_values(by='money_ok', ascending=False)
            
            fresh_list = []
            for _, row in target_stocks.iterrows():
                raw_code = row['mkte_ticker'].strip() if 'mkte_ticker' in row else row['stck_shrn_iscd'].strip()
                code = "".join(filter(str.isdigit, raw_code))[-6:]
                
                name = row['hts_kor_isnm'].strip()
                rate = row['prdy_ctrt']
                price = row['stck_prpr']
                money = row['money_ok']
                detect_time = datetime.now(KST).strftime('%H:%M:%S')
                
                # 중복 전송 방지 및 텔레그램 발송
                if code not in st.session_state['sent_stocks']:
                    msg = (
                        f"🚀 [장중 주도주 포착] 🚀\n\n"
                        f"📌 종목명: {name} ({code})\n"
                        f"📈 현재가: {price:,}원\n"
                        f"⚡ 등락률: {rate}%\n"
                        f"💰 거래대금: {money:,}억"
                    )
                    send_telegram_msg(TELEGRAM_TOKEN, CHAT_ID, msg)
                    st.session_state['sent_stocks'].add(code)
                
                fresh_list.append({
                    "포착 시간": detect_time,
                    "종목코드": code,
                    "종목명": name,
                    "현재가(원)": f"{price:,}",
                    "전일대비 등락률": f"{rate}%",
                    "거래대금(억)": money
                })
                
            st.session_state['detected_list'] = fresh_list
            st.session_state['last_run_time'] = datetime.now(KST).strftime('%H:%M:%S')
            st.session_state['engine_status'] = f"🟢 수급 관제 정상 가동 중 ({rt_msg})"
        else:
            st.session_state['engine_status'] = f"❌ 통신 에러 (코드: {res.status_code})"
            
    except Exception as e:
        st.session_state['engine_status'] = f"💥 시스템 연산 예외 발생: {str(e)}"

# ==========================================
# 5. 프론트엔드 UI 화면 구성 구역
# ==========================================
st.title("🔥 한국투자증권 실전망 전용 장중 주도주 레이더")
st.caption("Secrets 변수 미연동 현상을 완벽히 우회하여 실시간 실제 데이터를 바로 받아오는 대시보드")

col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    st.metric(label="최근 실시간 동기화 시간", value=st.session_state['last_run_time'])
with col_m2:
    st.metric(label="오늘 레이더에 검출된 총 종목 수", value=f"{len(st.session_state['detected_list'])} 개")
with col_m3:
    st.metric(label="실전 엔진 가동 현황", value=st.session_state['engine_status'])

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 레이더 판독 현황")

# 최초 1회 기동 제어
if st.session_state['last_run_time'] == "아직 조회되지 않음":
    run_monitoring()

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
    st.warning("📥 장중 수급 데이터를 파싱하고 있습니다. 만약 변수 로드 문제로 표가 비어있다면, 왼쪽 사이드바 입력창에 한투 실전 KEY들을 직접 마우스로 붙여넣어 주십시오.")

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
# ⏱️ 백그라운드 안전 스크립트 타이머 (60초 주기 자동 동기화)
# ==========================================
st.caption("⚙️ 정기 관제 가동 중: 시스템 과부하 및 서버 차단을 방지하기 위해 60초마다 스마트 연동 리프레시를 수행합니다.")
time.sleep(60)
st.rerun()
