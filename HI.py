import requests
import json
import pandas as pd
from datetime import datetime
import pytz
import streamlit as st

# 1. 기본 설정 및 한국 표준시(KST) 세팅
st.set_page_config(page_title="한투 주도주 레이더", layout="wide")
KST = pytz.timezone('Asia/Seoul')

# 2. 자격 증명 (Streamlit Secrets 연동)
APP_KEY = st.secrets["APP_KEY"].strip()
APP_SECRET = st.secrets["APP_SECRET"].strip()
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"].strip()
CHAT_ID = st.secrets["CHAT_ID"].strip()

# 실전 운영망 도메인 완전 고정
URL_BASE = "https://openapi.koreainvestment.com:9443"

# 3. 세션 메모리 초기화 (중복 알림 방지 및 마스터 목록 보관)
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set()
if 'master_token' not in st.session_state:
    st.session_state['master_token'] = None
if 'stock_display_df' not in st.session_state:
    st.session_state['stock_display_df'] = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state['last_update_time'] = "아직 조회되지 않음"

# 4. OAuth2.0 실전용 토큰 최초 1회 발급 함수
def fetch_initial_token():
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials", 
        "appkey": APP_KEY, 
        "secretkey": APP_SECRET
    }
    try:
        # 토큰 발급 창구는 포트번호 없이 공통 호출
        res = requests.post("https://openapi.koreainvestment.com/oauth2/tokenP", headers=headers, json=body, timeout=5)
        if res.status_code == 200:
            st.session_state['master_token'] = res.json().get("access_token")
            return True
    except Exception as e:
        st.error(f"🚨 토큰 발급 단계 네트워크 통신 장애: {e}")
    return False

# 5. 동기식 텔레그램 메시지 발송 함수
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=3)
    except:
        pass

# 6. 한투 정식 API 연동 및 데이터 필터링 엔진
def execute_radar_screening():
    # 토큰이 유실되었거나 없을 때만 딱 1번 새로 받아옴 (무한 재발급 방지)
    if not st.session_state['master_token']:
        success = fetch_initial_token()
        if not success:
            st.error("❌ 한투 실전 토큰 인증에 거절당했습니다. Secrets의 APP_KEY 조합을 확인하십시오.")
            return

    # 공식 거래량/거래대금 순위 엔드포인트
    api_url = f"{URL_BASE}/uapi/domestic-stock/v1/quotations/volume-rank"
    
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {st.session_state['master_token']}",
        "appkey": APP_KEY,
        "secretkey": APP_SECRET,
        "tr_id": "FHPST01710000",
        "custtype": "P"
    }
    
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",    # J: 주식 전체 (코스피 + 코스닥)
        "FID_COND_SCR_DIV_CODE": "20171", # 화면 분류 코드
        "FID_INPUT_ISCD": "0000",         # 0000: 전체
        "FID_DIV_CLS_CODE": "0",          # 0: 전체 순위
        "FID_BLNG_CLS_CODE": "0",         
        "FID_TRGT_CLS_CODE": "00000000",  
        "FID_TRGT_EXCL_CLS_CODE": "00000000",
        "FID_INPUT_PRICE_1": "0",
        "FID_INPUT_PRICE_2": "0",
        "FID_VOL_CNT": "",                # 한투 표준 규격 공백 필수
        "FID_INPUT_DATE_1": ""            # 한투 표준 규격 공백 필수
    }
    
    try:
        res = requests.get(api_url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            res_data = res.json()
            output = res_data.get('output', [])
            server_msg = res_data.get('msg1', '데이터 수집 완료').strip()
            
            st.info(f"📡 한투 인포메이션 메인 프레임 응답 상태: {server_msg}")
            
            if not output:
                return
                
            df = pd.DataFrame(output)
            
            # 자료형 안전 수치 형변환
            df['stck_prpr'] = pd.to_numeric(df['stck_prpr'], errors='coerce').fillna(0).astype(int)
            df['acml_tr_pbmn'] = pd.to_numeric(df['acml_tr_pbmn'], errors='coerce').fillna(0).astype(float)
            df['prdy_ctrt'] = pd.to_numeric(df['prdy_ctrt'], errors='coerce').fillna(0).astype(float)
            df['money_billion'] = (df['acml_tr_pbmn'] // 100000000).astype(int) # 억 단위 절사
            
            # 🎯 주도주 수급 타겟 필터링 (거래대금 50억 이상 & 등락률 +1.0% 이상)
            filtered_df = df[(df['money_billion'] >= 5) & (df['prdy_ctrt'] >= 1.0)]
            
            # 만약 장세 소강으로 검출 종목이 너무 적으면 거래대금 상위 20개 자동 인계 강제 표출
            if len(filtered_df) < 10:
                final_target = df.sort_values(by='money_billion', ascending=False).head(20)
            else:
                final_target = filtered_df.sort_values(by='money_billion', ascending=False)
                
            processed_rows = []
            for _, row in final_target.iterrows():
                raw_code = row['mkte_ticker'].strip() if 'mkte_ticker' in row else row['stck_shrn_iscd'].strip()
                code = "".join(filter(str.isdigit, raw_code))[-6:] # 순수 6자리 종목코드 추출
                
                name = row['hts_kor_isnm'].strip()
                rate = row['prdy_ctrt']
                price = row['stck_prpr']
                money = row['money_billion']
                detect_time = datetime.now(KST).strftime('%H:%M:%S')
                
                # 중복 알림 방지 가드 가동 후 텔레그램 실시간 발송
                if code not in st.session_state['sent_stocks']:
                    msg = (
                        f"🚀 [실전 주도주 포착]\n\n"
                        f"📌 종목명: {name} ({code})\n"
                        f"📈 현재가: {price:,}원\n"
                        f"⚡ 등락률: {rate}%\n"
                        f"💰 거래대금: {money:,}억"
                    )
                    send_telegram(msg)
                    st.session_state['sent_stocks'].add(code)
                    
                processed_rows.append({
                    "포착시간": detect_time,
                    "종목코드": code,
                    "종목명": name,
                    "현재가(원)": f"{price:,}",
                    "전일대비 등락률": f"{rate}%",
                    "거래대금(억)": money
                })
                
            st.session_state['stock_display_df'] = pd.DataFrame(processed_rows)
            st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        else:
            st.error(f"❌ 한투 서버가 통신을 거부했습니다. (에러 코드: {res.status_code})")
    except Exception as e:
        st.error(f"💥 시세 분석 스크립트 실행 오류: {e}")

# ==========================================
# 7. 대시보드 레이아웃 UI 구역
# ==========================================
st.title("⚡ 한국투자증권 실전망 직통 주도주 레이더")
st.caption("복잡하게 꼬인 내부 스레드와 타이머를 싹 비우고 오직 실시간 데이터 정밀 매칭에만 집중한 베이직 최종본")

# 수동 새로고침 버튼 배치
if st.button("🔄 실전 서버 실시간 주도주 데이터 즉시 조회", use_container_width=True):
    execute_radar_screening()

# 현황 스코어 보드 배치
col_t1, col_t2 = st.columns(2)
with col_t1:
    st.metric(label="📊 최근 실전망 동기화 시간 (KST)", value=st.session_state['last_update_time'])
with col_t2:
    st.metric(label="🎯 검출된 수급 주도주 라인업", value=f"{len(st.session_state['stock_display_df'])} 개")

st.markdown("---")

# 데이터 중앙 표 표출 구역
if not st.session_state['stock_display_df'].empty:
    # 최신 Streamlit 사양의 단순 노출형 데이터프레임 마운트 (중복 오류 완전 제거)
    st.dataframe(st.session_state['stock_display_df'], use_container_width=True, hide_index=True)
else:
    st.warning("📥 상단의 [🔄 실전 서버 실시간 주도주 데이터 즉시 조회] 버튼을 툭 누르시면 한투 실전망 파이프라인을 열어 실제 주도주 20선을 즉각 로드해옵니다.")
