import streamlit as st
import pandas as pd
import requests
import time
import os
import json
from datetime import datetime, timezone, timedelta

# =====================================================================
# ⚙️ [최우선] Streamlit 설정 및 세션 초기화
# =====================================================================
st.set_page_config(page_title="장중 실시간 주도주 마스터 스캐너 Pro", layout="wide")

# 🛡️ Secrets 내부 키값으로만 다이렉트 매핑 (유령 공백 제거 포함)
APP_KEY = st.secrets.get("HANTU_APP_KEY", "").strip()
APP_SECRET = st.secrets.get("HANTU_APP_SECRET", "").strip()
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = st.secrets.get("CHAT_ID", "").strip()

if "engine_cache" not in st.session_state: st.session_state.engine_cache = {}
if "last_pool" not in st.session_state: st.session_state.last_pool = []
if "net_log" not in st.session_state: st.session_state.net_log = "🔌 주도주 실시간 파이프라인 대기 중..."

KST = timezone(timedelta(hours=9))
TOKEN_FILE = "hantu_token_cache.json"

st.title("🎯 AI 당일 상승 주도주 실시간 스캐너 (순수 거래대금 대장주 전광판)")
st.warning(f"📡 **실시간 라인 진단 모니터:** {st.session_state.net_log}")
st.write("---")

# =====================================================================
# 🏹 대한민국 시장 돈의 흐름을 1위부터 긁어오는 정순위 수급 엔진
# =====================================================================
class HantuPureSpeedEngine:
    def __init__(self):
        self.session = requests.Session()
        
    def get_token(self):
        if not APP_KEY or not APP_SECRET:
            st.session_state.net_log = "❌ Secrets 내부에 HANTU_APP_KEY 또는 HANTU_APP_SECRET 설정이 유실되었습니다."
            return None

        now_utc = datetime.now(tz=timezone.utc)

        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r") as f:
                    cache = json.load(f)
                expire_time = datetime.fromisoformat(cache["expires_at"])
                if expire_time > now_utc and cache.get("token"):
                    return cache["token"]
            except:
                pass

        url = "https://openapi.koreainvestment.com/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials", 
            "appkey": APP_KEY, 
            "appsecret": APP_SECRET
        }
        try:
            r = self.session.post(url, json=body, timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                token = data.get("access_token")
                if token:
                    expires_at = (datetime.now(tz=timezone.utc) + timedelta(hours=5)).isoformat()
                    with open(TOKEN_FILE, "w") as f:
                        json.dump({"token": token, "expires_at": expires_at}, f)
                    return token
            else:
                err_json = r.json()
                reason_msg = err_json.get('error_description', f"HTTP 오류: {r.status_code}")
                st.session_state.net_log = f"❌ 토큰 발급 실패 ({reason_msg})"
        except Exception as e:
            st.session_state.net_log = f"❌ 인증 연결 실패 -> {str(e)}"
        return None

    def fetch_market_pool_by_indices(self, token):
        pool = []
        
        # 한투 실전망 공식 거래량/거래대금 상위 창구 타격
        url_vol = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/volume-rank"
        headers_vol = {
            "content-type": "application/json; charset=utf-8", 
            "authorization": f"Bearer {token}",
            "appkey": APP_KEY, 
            "appsecret": APP_SECRET, 
            "tr_id": "FHPST01710000", 
            "custtype": "P"
        }
        
        params_vol = {
            "FID_COND_MRKT_DIV_CODE": "J", 
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000", 
            "FID_DIV_CLS_CODE": "0", 
            "FID_SORT_CLS_CODE": "4",       # 4: 거래대금 순위 정렬 고정
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "00000000",
            "FID_TRGT_EXCL_CLS_CODE": "00000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "",              
            "FID_INPUT_DATE_1": ""          
        }
        
        try:
            r_vol = self.session.get(url_vol, headers=headers_vol, params=params_vol, timeout=5.0)
            if r_vol.status_code == 200:
                vol_output = r_vol.json().get("output", [])
                for rank_idx, item in enumerate(vol_output):
                    t_code = str(item.get("mksc_shrn_iscd", "")).strip()[-6:]
                    if not t_code.isdigit(): continue
                    
                    name = str(item.get("hts_kor_isnm", item.get("data_name", ""))).strip()
                    # 단타 효율 극대화를 위해 거래 패널티를 가진 우회 자산(스팩, 리츠 등) 필터링
                    if any(k in name for k in ["스팩", "리츠", "인버스", "레버리지", "KODEX", "TIGER"]): continue
                    
                    p_str_raw = "".join(filter(str.isdigit, str(item.get("stck_prpr", "0"))))
                    price = int(p_str_raw) if p_str_raw else 0
                    
                    ctrt = float(str(item.get("prdy_ctrt", "0.0")).strip())
                    stat = str(item.get("iscd_stat_cls_code", "00")).strip()
                    raw_amt = float(str(item.get("acml_tr_pbmn", "0")).strip())
                    
                    # 단타 진입 시 호가 공백이 심한 초소형 동전주(5,000원 이하) 필터링 탈락
                    if price < 5000: continue
                    if ctrt <= 0.0: continue # 마이너스 및 보합 종목 전면 파쇄 (오직 양봉만)
                    
                    pool.append((rank_idx + 1, t_code, name, ctrt, raw_amt, stat))
        except Exception as e:
            st.session_state.net_log = f"❌ 데이터 조회망 패킷 통신 무너짐: {str(e)}"

        st.session_state.net_log = f"🟢 한투 실전망 실시간 대장주 순수 동기화 완료! ({datetime.now(tz=KST).strftime('%H:%M:%S')})"
        pool.sort(key=lambda x: x[0]) # 한투 공식 순위 우선 정렬
        return pool

# =====================================================================
# ⚡ [상시 표출 시스템]: 사용자가 들어오자마자 무조건 라이브 수급 데이터 로드
# =====================================================================
def force_sync_load():
    engine = HantuPureSpeedEngine()
    token = engine.get_token()
    if token:
        st.session_state.last_pool = engine.fetch_market_pool_by_indices(token)

if not st.session_state.last_pool:
    force_sync_load()

# =====================================================================
# 🖥️ 데이터 제어 버튼 파트
# =====================================================================
cc1, cc2 = st.columns([4, 1])
with cc1:
    btn_fetch = st.button("🔄 한투 실전망 당일 플러스(+) 상승 주도주 전체 즉시 동기화", type="primary", use_container_width=True)
with cc2:
    btn_clear = st.button("⚠️ 시스템 세션 초기화", type="secondary", use_container_width=True)

if btn_clear:
    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    st.session_state.last_pool = []
    st.session_state.net_log = "♻️ 한투 실전망 인증 세션 초기화 완료."
    st.rerun()

if btn_fetch:
    st.session_state.last_pool = []
    with st.spinner("한투 실전망 게이트웨이 동기화 중..."):
        force_sync_load()
        st.rerun()

# =====================================================================
# 📊 [상단 구역] 플러스 상승 우량주 전용 종합 수급 표
# =====================================================================
st.markdown("### 📊 당일 실시간 상승(+) 주도주 마스터 종합 순위표 (순수 수급 관제 모드)")

display_list = []
if isinstance(st.session_state.last_pool, list) and len(st.session_state.last_pool) > 0:
    for row in st.session_state.last_pool:
        if isinstance(row, tuple) and len(row) == 6:
            raw_rank, t, n, ctrt, amt, stat = row
            
            stat_prefix = ""
            if stat in ["58", "59"]: stat_prefix = "[🚨VI발동] "
            elif stat == "52": stat_prefix = "[⚠️유의] "
            elif stat == "51": stat_prefix = "[❌관리] "
            elif stat == "57": stat_prefix = "[🔥경고] "

            # ⚡ [수술 완료]: 특정 종목 조건문을 완전히 폐기하고 순수 대금 크기로 등급 부여
            if raw_rank <= 20 and ctrt >= 4.0:
                display_name = f"🔥[우량주도-최강] {stat_prefix}{n}"
                rank_grade = "🔥 1단계: A급 (시세 강력 분출)"
                action_tag = "🚀 대한민국 시장 자금을 가장 빠르게 빨아들이는 핵심 대장 (최우선 타깃)"
            else:
                display_name = f"{stat_prefix}{n}"
                rank_grade = "⚡ 2단계: B급 (견고한 거래량 쏠림)"
                action_tag = "🟢 수급 확인 완료 / 하단 차트 패널에서 당일 분봉 실시간 파동 추적"

            amt_display = f"{int(amt / 100000000):,}억 원" if amt > 0 else "실시간 집계 중"

            display_list.append({
                "당일 대금 순위": f"{raw_rank}위",
                "종목코드": t,
                "종목명": display_name,
                "수급 등급 분류": rank_grade,
                "현재가": f"⬇️ 하단 실시간 오리지널 차트에서 정품 가격 즉시 연동",
                "등락률": f"{ctrt:+.2f}%",
                "당일 누적대금": amt_display,
                "실전 행동 지침": action_tag
            })

df_final = pd.DataFrame(display_list)

selected_ticker = None
selected_name = None

if not df_final.empty:
    df_final.insert(0, "선택", False)
    
    # ⚡ 첫 줄 종목에 기본 무조건 체크 가동 (초기 차트 표출 세팅)
    df_final.loc[0, "선택"] = True

    edited_df = st.data_editor(
        df_final,
        use_container_width=True,
        hide_index=True,
        column_config={"선택": st.column_config.CheckboxColumn(required=True)},
        disabled=["당일 대금 순위", "종목코드", "종목명", "수급 등급 분류", "현재가", "등락률", "당일 누적대금", "실전 행동 지침"],
        height=450
    )
    
    selected_rows = edited_df[edited_df["선택"] == True]
    if not selected_rows.empty:
        selected_ticker = selected_rows.iloc[0]["종목코드"]
        raw_selected_name = selected_rows.iloc[0]["종목명"]
        selected_name = raw_selected_name.split("]")[-1].strip()
    else:
        selected_ticker = df_final.iloc[0]["종목코드"]
        raw_selected_name = df_final.iloc[0]["종목명"]
        selected_name = raw_selected_name.split("]")[-1].strip()
else:
    st.info("📥 한투 실전망 파이프라인을 연동하는 중입니다. 잠시만 기다려주십시오.")

st.write("---")

# =====================================================================
# 📈 [하단 구역] 네이버 실시간 차트 스튜디오
# =====================================================================
st.markdown("### 📈 네이버 페이 증권 실시간 오리지널 차트 패널")

if selected_ticker:
    st.success(f"🔍 현재 분석 동기화 차트: **{selected_name} ({selected_ticker})**")
    
    tab1, tab2 = st.tabs(["⚡ 단타 필수: 실시간 당일 분봉 차트", "📅 추세 확인: 일봉 차트"])
    time_seed = int(time.time())
    
    with tab1:
        naver_minute_chart = f"https://ssl.pstatic.net/imgfinance/chart/item/area/day/{selected_ticker}.png?v={time_seed}"
        st.image(naver_minute_chart, caption=f"[{selected_name}] 네이버 실시간 분봉 및 당일 세력 거래량 분석", use_container_width=True)
        
    with tab2:
        naver_day_chart = f"https://ssl.pstatic.net/imgfinance/chart/item/candle/day/{selected_ticker}.png?v={time_seed}"
        st.image(naver_day_chart, caption=f"[{selected_name}] 네이버 실시간 일봉 캔들 추세 지지선", use_container_width=True)

# =====================================================================
# ⏱️ [장중 상시 자동 관제]: 60초 무중단 리프레시 엔진
# =====================================================================
st.caption("⚙️ **자동 감시 시스템 가동 중:** 장중 최신 거래대금 파싱을 위해 60초마다 백그라운드 리프레시를 자동 수행합니다.")
time.sleep(60)
st.rerun()
