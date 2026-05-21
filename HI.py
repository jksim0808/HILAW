import requests
import json
import pandas as pd
from datetime import datetime
import pytz
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정 (넓은 화면 모드)
# ==========================================
st.set_page_config(page_title="한투 실전망 주도주 레이더", layout="wide")

# 한국 표준시(KST) 타임존 정의
KST = pytz.timezone('Asia/Seoul')

# ⚡ [한투 공식 가이드라인 실전 운영망 주소 이원화 고정]
URL_TOKEN = "https://openapi.koreainvestment.com"            # 🔑 토큰 발급 창구 (포트 없음)
URL_DATA = "https://openapi.koreainvestment.com:9443"        # 📊 시세 조회 창구 (9443 포트)

# ==========================================
# 2. 자격 증명 안전 로드 및 유령 공백 완벽 제거 (Strip)
# ==========================================
st.sidebar.header("🔑 한투 실전망 인증 센터")
st.sidebar.success("🌐 통신 회선: 한국투자증권 실전 운영망 정식 연결")

# Secrets에 등록된 키를 우선으로 읽되, 앞뒤 눈에 안 보이는 공백을 완벽히 잘라냅니다.
sec_app_key = st.secrets["APP_KEY"].strip() if "APP_KEY" in st.secrets else ""
sec_app_secret = st.secrets["APP_SECRET"].strip() if "APP_SECRET" in st.secrets else ""

user_app_key = st.sidebar.text_input("한투 실전 APP KEY", value=sec_app_key, type="password")
user_app_secret = st.sidebar.text_input("한투 실전 APP SECRET", value=sec_app_secret, type="password")

APP_KEY = user_app_key.strip() if user_app_key else sec_app_key
APP_SECRET = user_app_secret.strip() if user_app_secret else sec_app_secret

st.sidebar.markdown("---")
st.sidebar.header("🤖 텔레그램 수신기")
TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"].strip() if "TELEGRAM_TOKEN" in st.secrets else ""
CHAT_ID = st.secrets["CHAT_ID"].strip() if "CHAT_ID" in st.secrets else ""

# ==========================================
# 3. 세션 상태(Session State) 초기화 (토큰 일회성 저장 관리)
# ==========================================
if 'kis_token' not in st.session_state:
    st.session_state['kis_token'] = None         # 한투 세션인증 토큰 보관함
if 'sent_stocks' not in st.session_state:
    st.session_state['sent_stocks'] = set()      # 텔레그램 중복 전송 방지 가드
if 'stock_display_df' not in st.session_state:
    st.session_state['stock_display_df'] = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state['last_update_time'] = "아직 조회되지 않음"
if 'engine_status' not in st.session_state:
    st.session_state['engine_status'] = "🔴 한투 API 인증 대기 중"

# ==========================================
# 4. 핵심 백엔드 기능 함수들 (한투 정석 프로토콜 구현)
# ==========================================
def get_access_token():
    """OAuth2.0 실전 운영망 토큰 발급 (정석 헤더 및 바디 매칭)"""
    if not APP_KEY or not APP_SECRET:
        st.session_state['engine_status'] = "❌ 실전 키값 누락 (사이드바 혹은 Secrets를 확인해 주세요)"
        return None
        
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials", 
        "appkey": APP_KEY, 
        "secretkey": APP_SECRET
    }
    try:
        # 포트가 없는 공식 토큰 주소로 정밀 타격
        res = requests.post(f"{URL_TOKEN}/oauth2/tokenP", headers=headers, json=body, timeout=5)
        if res.status_code == 200:
            token = res.json().get("access_token")
            st.session_state['kis_token'] = token
            return token
        else:
            err_msg = res.json().get('error_description', 'AppKey 조합 혹은 계정 권한 불일치')
            st.session_state['engine_status'] = f"❌ 인증 거절 (사유: {err_msg})"
    except Exception as e:
        st.session_state['engine_status'] = f"💥 토큰 발급 단계 네트워크 장애: {str(e)}"
    return None

def send_telegram(text):
    """동기식 텔레그램 메시지 푸시 발송"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=3)
    except:
        pass

def run_radar_screening():
    """한국투자증권 실전망 다이렉트 연동 및 주도주 스크리닝 엔진"""
    try:
        # 토큰이 없거나 만료되었을 때만 딱 1번 새로 받아와서 락을 겁니다.
        if not st.session_state['kis_token']:
            token = get_access_token()
            if not token:
                return
        else:
            token = st.session_state['kis_token']

        # ⚡ 데이터 조회는 포트번호가 붙은 실전망 공식 엔드포인트 타격
        api_url = f"{URL_DATA}/uapi/domestic-stock/v1/quotations/volume-rank"
        
        # 🛡️ 한투 실전망 표준 규격 거래량 순위 헤더 셋업
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY,
            "secretkey": APP_SECRET,
            "tr_id": "FHPST01710000",       # 거래량 순위 조회 공식 TR ID
            "custtype": "P"                  # P: 개인 실전망 고정
        }
        
        # 🛡️ 공식 명세서 상의 빈칸 필수 전송 파라미터 매칭
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",    # J: 주식 전체 (코스피 + 코스닥 통합)
            "FID_COND_SCR_DIV_CODE": "20171", # 화면 분류 코드 고정
            "FID_INPUT_ISCD": "0000",         # 0000: 전체 시장 대상
            "FID_DIV_CLS_CODE": "0",          # 0: 전체 순위
            "FID_BLNG_CLS_CODE": "0",         
            "FID_TRGT_CLS_CODE": "00000000",  
            "FID_TRGT_EXCL_CLS_CODE": "00000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "",                # ⚠️ 필수: 공백 문자열 전달
            "FID_INPUT_DATE_1": ""            # ⚠️ 필수: 공백 문자열 전달
        }
        
        res = requests.get(api_url, headers=headers, params=params, timeout=5)
        
        if res.status_code == 200:
            res_json = res.json()
            output = res_json.get('output', [])
            server_msg = res_json.get('msg1', '데이터 수집 완료').strip()
            
            if not output:
                st.session_state['engine_status'] = f"⚠️ 한투 응답 성공했으나 비어있음 (사유: {server_msg})"
                return
                
            df_raw = pd.DataFrame(output)
            
            # 수치 데이터 안전 형변환 공정
            df_raw['stck_prpr'] = pd.to_numeric(df_raw['stck_prpr'], errors='coerce').fillna(0).astype(int)
            df_raw['acml_tr_pbmn'] = pd.to_numeric(df_raw['acml_tr_pbmn'], errors='coerce').fillna(0).astype(float)
            df_raw['prdy_ctrt'] = pd.to_numeric(df_raw['prdy_ctrt'], errors='coerce').fillna(0).astype(float)
            df_raw['money_billion'] = (df_raw['acml_tr_pbmn'] // 100000000).astype(int) # 억 원 단위 변환
            
            # 🎯 [대표님 오리지널 주도주 커트라인]: 당일 거래대금 100억 이상 & 상승률 +1.5% 이상 대장주 스크리닝
            filtered_df = df_raw[(df_raw['money_billion'] >= 10) & (df_raw['prdy_ctrt'] >= 1.5)]
            
            # 만약 장세 소강 상태로 종목이 너무 적으면 거래대금 상위 20개 자동 인계 강제 표출
            if len(filtered_df) < 10:
                final_target = df_raw.sort_values(by='money_billion', ascending=False).head(20)
            else:
                final_target = filtered_df.sort_values(by='money_billion', ascending=False)
                
            processed_rows = []
            detect_time = datetime.now(KST).strftime('%H:%M:%S')
            
            for _, row in final_target.iterrows():
                raw_code = row['mkte_ticker'].strip() if 'mkte_ticker' in row else row['stck_shrn_iscd'].strip()
                code = "".join(filter(str.isdigit, raw_code))[-6:] # 순정 6자리 종목코드 발라내기
                
                name = row['hts_kor_isnm'].strip()
                rate = row['prdy_ctrt']
                price = row['stck_prpr']
                money = row['money_billion']
                
                # 중복 전송 제어 가드 작동 후 텔레그램 실시간 신호 푸시
                if code not in st.session_state['sent_stocks']:
                    msg = (
                        f"🚀 [한투 실전망 - 주도주 포착]\n\n"
                        f"📌 종목명: {name} ({code})\n"
                        f"📈 현재가: {price:,}원\n"
                        f"⚡ 당일 등락률: +{rate}%\n"
                        f"💰 현재 거래대금: {money:,}억 돌파!"
                    )
                    send_telegram(msg)
                    st.session_state['sent_stocks'].add(code)
                    
                processed_rows.append({
                    "포착시간": detect_time,
                    "종목코드": code,
                    "종목명": name,
                    "현재가(원)": f"{price:,}",
                    "전일대비 등락률": f"+{rate}%" if rate > 0 else f"{rate}%",
                    "당일 거래대금(억)": money
                })
                
            st.session_state['stock_display_df'] = pd.DataFrame(processed_rows)
            st.session_state['last_update_time'] = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
            st.session_state['engine_status'] = f"🟢 한투 실전 통신 성공 ({server_msg})"
        else:
            st.session_state['engine_status'] = f"❌ 한투 통신 거부 (에러 코드: {res.status_code})"
            
    except Exception as e:
        st.session_state['engine_status'] = f"💥 시스템 연산 예외 장애 발생: {str(e)}"

# ==========================================
# 5. 대시보드 레이아웃 UI 구역 (정석 컴팩트 디자인)
# ==========================================
st.title("⚡ 한국투자증권 실전망 직통 장중 주도주 레이더")
st.caption("우회 창구를 전부 폐쇄하고 오직 한투 정식 API 명세서 규격 프로토콜만 다이렉트로 관통시킨 정석 최종 마스터본")

# 수동 즉시 호출 및 새로고침 버튼 배치
if st.button("🔄 한투 실전망 실시간 주도주 데이터 즉시 동기화", use_container_width=True):
    run_radar_screening()

# 관제 메트릭 스코어보드 배치
col_m1, col_m2, col_m3 = st.columns(3)
with col_m1:
    st.metric(label="📊 최근 실전망 동기화 완료 시간 (KST)", value=st.session_state['last_update_time'])
with col_m2:
    st.metric(label="🎯 현재 레이더 감지 종목 수", value=f"{len(st.session_state['stock_display_df'])} 개")
with col_m3:
    st.metric(label="🛡️ 실전 엔진 가동 현황", value=st.session_state['engine_status'])

st.markdown("---")

# 실시간 모니터링 데이터 표 렌더링 구역
if not st.session_state['stock_display_df'].empty:
    st.dataframe(st.session_state['stock_display_df'], use_container_width=True, hide_index=True)
else:
    # 켜자마자 최초 1회 묻지도 따지지도 않고 직통 강제 호출
    run_radar_screening()
    if not st.session_state['stock_display_df'].empty:
        st.rerun()
    else:
        st.warning("📥 상단의 [🔄 한투 실전망 실시간 주도주 데이터 즉시 동기화] 버튼을 툭 누르시면 꼬임 없는 순정 통신망을 열어 실제 실시간 주도주들을 즉각 로드해옵니다.")
