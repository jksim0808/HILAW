import streamlit as st
import requests
import json
from datetime import datetime, timezone, timedelta

st.set_page_config(page_title="한투 실전망 파이프라인 결속 검증기", layout="centered")

st.title("📡 한국투자증권 Open API 실전망 연결성 진단 패널")
st.write("대표님 시스템 내부의 가상 터널과 한투 인프라의 물리적 결속 상태를 실시간 검증합니다.")
st.write("---")

# ⚙️ Secrets 바인딩 상태 점검
APP_KEY = st.secrets.get("HANTU_APP_KEY", "").strip()
APP_SECRET = st.secrets.get("HANTU_APP_SECRET", "").strip()

if not APP_KEY or not APP_SECRET:
    st.error("❌ [위험] Streamlit Secrets 내부에 HANTU_APP_KEY 또는 HANTU_APP_SECRET 설정이 유실되었습니다.")
    st.stop()

# 통신 세션 초기화
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
})

# =====================================================================
# 🔓 1단계: OAuth2 정품 실전 인증 토큰 발급 테스트
# =====================================================================
st.markdown("### 🔑 1단계: 실전망 인증 게이트웨이 돌파 테스트")
token_url = "https://openapi.koreainvestment.com/oauth2/tokenP"
token_body = {
    "grant_type": "client_credentials",
    "appkey": APP_KEY,
    "appsecret": APP_SECRET
}

token = None
try:
    with st.spinner("한투 인증 서버 문 두드리는 중..."):
        r_auth = session.post(token_url, json=token_body, timeout=4.0)
    
    if r_auth.status_code == 200:
        auth_data = r_auth.json()
        token = auth_data.get("access_token")
        expire_in = auth_data.get("expires_in", 0)
        
        st.success(f"🔓 [인증 성공] OAuth2 정품 액세스 토큰이 칼같이 발급되었습니다!")
        st.info(f"⏱️ **토큰 유효 기간:** {int(expire_in)/3600}시간 정상 확보 완료")
    else:
        st.error(f"❌ [인증 실패] 한투 서버가 접속을 거부했습니다. (에러코드: {r_auth.status_code})")
        st.json(r_auth.json())
except Exception as e:
    st.error(f"💥 [통신 장애] 한투 인증 서버로 가는 가상 터널 경로에 방해물이 감지되었습니다: {e}")

# =====================================================================
# 🏹 2단계: 발급된 정품 토큰으로 실시간 주가 패킷 소싱 테스트
# =====================================================================
if token:
    st.write("---")
    st.markdown("### 🎯 2단계: 실전 시세 서버 패킷 소싱 검증 (타깃: 삼성전자)")
    
    price_url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
    price_headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHPST01010000",  # 국내주식 현재가 상세 TR
        "custtype": "P"
    }
    price_params = {
        "FID_COND_MRKT_DIV_CODE": "J",  # 주식 종목 구분
        "FID_INPUT_ISCD": "005930"      # 삼성전자 종목코드
    }
    
    try:
        with st.spinner("삼성전자 실시간 틱 데이터 낚아채는 중..."):
            r_price = session.get(price_url, headers=price_headers, params=price_params, timeout=4.0)
            
        if r_price.status_code == 200:
            output = r_price.json().get("output", {})
            if output:
                st.success("🟢 [연결 성공] 한국투자증권 실전망 파이프라인 완벽 결속 완료!")
                
                # 찐 한투 서버 전광판 데이터 바인딩 표출
                st.balloons()
                
                raw_price = int(output.get("stck_prpr", 0))
                raw_ctrt = float(output.get("prdy_ctrt", 0.0))
                raw_vol = int(output.get("acml_vol", 0))
                raw_amt = int(output.get("acml_tr_pbmn", 0))
                
                # 가시성 극대화 매핑 대시보드
                c1, c2 = st.columns(2)
                with c1:
                    st.metric(label="🏛️ 삼성전자 장중 실시간 현재가", value=f"{raw_price:,} 원", delta=f"{raw_ctrt:+.2f}%")
                with c2:
                    st.metric(label="📊 당일 누적 거래대금 (한투 집계)", value=f"{int(raw_amt/100000000):,} 억 원", delta=f"{raw_vol:,} 주 체결")
                    
                with st.expander("🔍 수신된 한투 순정 원본 데이터셋 패킷 확인", expanded=False):
                    st.json(output)
            else:
                st.warning("⚠️ 통신은 성공했으나 한투 서버가 빈 데이터를 보냈습니다. 장외 시간이거나 계정 권한을 확인하십시오.")
                st.json(r_price.json())
        else:
            st.error(f"❌ [패킷 차단] 시세 서버 문턱에서 거부되었습니다. (상태코드: {r_price.status_code})")
            st.json(r_price.json())
    except Exception as e:
        st.error(f"💥 [소켓 에러] 주가 수신 서버와의 패킷 동기화 중 에러 발생: {e}")

# =====================================================================
# 🔄 테스트 강제 리프레시 제어 버튼
# =====================================================================
st.write("---")
if st.button("🔄 한투 실전망 파이프라인 무중단 재연결 테스트", type="primary", use_container_width=True):
    st.rerun()
