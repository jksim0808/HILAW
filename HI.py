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

# ⚡ [한투 실전 운영망 표준 규격 주소]
URL_TOKEN = "https://openapi.koreainvestment.com"            
URL_DATA = "https://openapi.koreainvestment.com:9443"        

# ==========================================
# 2. 자격 증명 안전 로드 및 유령 공백 제거 (Strip 필터)
# ==========================================
st.sidebar.header("🔑 실전망 자격 증명 설정")
st.sidebar.success("🌐 접속 모드: ⚡ 한투 실전 운영망 (Real Market)")

sec_app_key = st.secrets["APP_KEY"].strip() if "APP_KEY" in st.secrets else ""
sec_app_secret = st.secrets["APP_SECRET"].strip() if "APP_SECRET" in st.secrets else ""

user_app_key = st.sidebar.text_input("한투 APP KEY", value=sec_app_key, type="password")
user_app_secret = st.sidebar.text_input("한투 APP SECRET", value=sec_app_secret, type="password")

APP_KEY = user_app_key.strip() if user_app_key else sec_app_key
APP_SECRET = user_app_secret.strip() if user_app_secret else sec_app_secret

st.sidebar.markdown("---")
st.sidebar.header("🤖 텔레그램 알림 수신기")
user_token = st.sidebar.text_input("텔레그램 봇 토큰", type="password")
user_chat_id = st.sidebar.text_input("내 채팅방 ID")

sec_tg_token = st.secrets["TELEGRAM_TOKEN"].strip() if "TELEGRAM_TOKEN" in st.secrets else ""
sec_chat_id = st.secrets["CHAT_ID"].strip() if "CHAT_ID" in st.secrets else ""

TELEGRAM_TOKEN = user_token.strip() if user_token else sec_tg_token
CHAT_ID = user_chat_id.strip() if user_chat_id else sec_chat_id

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
    st.session_state['engine_status'] = "🔴 초기화 대기 중"

# ==========================================
# 4. 핵심 백엔드 기능 함수들
# ==========================================
def get_access_token():
    """OAuth2.0 실전망 토큰 발급 함수"""
    if not APP_KEY or not APP_SECRET:
        st.session_state['engine_status'] = "❌ 키값 누락 (사이드바 혹은 Secrets를 확인해 주세요)"
        return None
        
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials", 
        "appkey": APP_KEY, 
        "secretkey": APP_SECRET
    }
    try:
        res = requests.post(f"{URL_TOKEN}/oauth2/tokenP", headers=headers, json=body, timeout=5)
        if res.status_code == 200:
            return res.json().get("access_token")
        else:
            err_json = res.json()
            reason_msg = err_json.get('error_description', 'AppKey/AppSecret 조합 불일치')
            st.session_state['engine_status'] = f"❌ 인증 실패 ({reason_msg})"
    except Exception as e:
        st.session_state['engine_status'] = f"💥 토큰 통신 장애: {str(e)}"
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

        api_url = f"{URL_DATA}/uapi/domestic-stock/v1/quotations/volume-rank"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000",
            "custtype": "P"
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
            res_json = res.json()
            output = res_json.get('output', [])
            rt_msg = res_json.get('msg1', '').strip()
            
            if not output:
                st.session_state['engine_status'] = f"⚠️ 한투 응답 비어있음 (사유: {rt_msg if rt_msg else '데이터 없음'})"
                return
                
            df_raw = pd.DataFrame(output)
            
            df_raw['stck_prpr'] = pd.to_numeric(df_raw['stck_prpr'], errors='coerce').fillna(0).astype(int)
            df_raw['acml_tr_pbmn'] = pd.to_numeric(df_raw['acml_tr_pbmn'], errors='coerce').fillna(0).astype(float)
            df_raw['prdy_ctrt'] = pd.to_numeric(df_raw['prdy_ctrt'], errors='coerce').fillna(0).astype(float)
            df_raw['money_ok'] = (df_raw['acml_tr_pbmn'] // 100000000).astype(int) 
            
            # 커트라인 (거래대금 50억 이상 & 등락률 +1.0% 이상)
            target_stocks = df_raw[(df_raw['money_ok'] >= 5) & (df_raw['prdy_ctrt'] >= 1.0)]
            
            if len(target_stocks) < 10:
                target_stocks = df_raw.sort_values(by='money_ok', ascending=False).head(15)
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
                
                if code not in st.session_state['sent_stocks']:
                    msg = (
                        f"🚀 [실전 장중 주도주 포착] 🚀\n\n"
                        f"📌 종목명: {name} ({code})\n"
                        f"📈 현재가: {price:,}원\n"
                        f"⚡ 당일 등락률: {rate}%\n"
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
            st.session_state['engine_status'] = "🟢 실전 데이터 수집 및 연결 성공"
        else:
            st.session_state['engine_status'] = f"❌ 통신 거부 (한투 에러 코드: {res.status_code})"
            
    except Exception as e:
        st.session_state['engine_status'] = f"💥 연산 스크립트 예외 발생: {str(e)}"

# ==========================================
# 5. 프론트엔드 UI 화면 구성 구역 (최초 강제 호출 마운트)
# ==========================================
st.title("🔥 한국투자증권 실전망 전용 장중 주도주 레이더")
st.caption("대기 상태 정체 원인이던 타이머 락을 해제하고 즉시 갱신 구조로 전면 보정한 실전 가동본")

# 🛡️ [치명상 격파]: 화면을 그리기 전, 데이터가 없으면 무조건 '즉시 강제 조회'를 실행하여 대기 상태를 원천 격파합니다.
if st.session_state['last_run_time'] == "아직 조회되지 않음":
    run_monitoring()

# 즉시 새로고침 버튼
if st.button("🔄 실전 서버 강제 호출 및 데이터 새로고침 (Manual Sync)", use_container_width=True):
    run_monitoring()

col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    st.metric(label="최근 실시간 동기화 시간", value=st.session_state['last_run_time'])
with col_m2:
    st.metric(label="오늘 레이더에 검출된 총 종목 수", value=f"{len(st.session_state['detected_list'])} 개")
with col_m3:
    st.metric(label="실전 엔진 가동 현황", value=st.session_state['engine_status'])

st.markdown("---")
st.subheader("🎯 장중 실시간 주도주 레이더 판독 현황")

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
    st.warning("📥 장중 수급 데이터를 수집 중입니다. 계속 대기 상태라면 한투 실전망의 현재 트래픽 차단 여부나 키값을 사이드바에서 재확인해 주십시오.")

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
# ⏱️ [보완 완료]: 시스템을 다운시키던 무한 대기 sleep 루프 전면 제거
# ==========================================
st.caption("⚙️ 정기 관제 가동 중: 시스템 과부하 방지를 위해 페이지 액션 시 실전망 데이터를 스마트 리프레시합니다.")
