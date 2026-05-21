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

APP_KEY = st.secrets.get("HANTU_APP_KEY", "").strip()
APP_SECRET = st.secrets.get("HANTU_APP_SECRET", "").strip()
TELEGRAM_TOKEN = st.secrets.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = st.secrets.get("CHAT_ID", "").strip()

if "engine_cache" not in st.session_state: st.session_state.engine_cache = {}
if "last_pool" not in st.session_state: st.session_state.last_pool = []
if "net_log" not in st.session_state: st.session_state.net_log = "🔌 주도주 실시간 파이프라인 대기 중..."

# 📡 실시간 수급 세션 기본 안전 정의
if "fut_money" not in st.session_state: st.session_state.fut_money = "데이터 수집 중"
if "fx_rate" not in st.session_state: st.session_state.fx_rate = "데이터 수집 중"
if "kospi_rate" not in st.session_state: st.session_state.kospi_rate = 0.0

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

    def fetch_market_index_radar(self, token):
        """⚡ 오직 한투 오리지널 실물 시세 패킷만 수집하는 순도 100% 가드 루틴"""
        # 1. 코스피 종합 지수 수집
        url_index = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-index-price"
        headers_index = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FJPST41000000", "custtype": "P"
        }
        params_index = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": "0001"}
        try:
            r = self.session.get(url_index, headers=headers_index, params=params_index, timeout=3.0)
            if r.status_code == 200:
                out = r.json().get("output", {})
                if out:
                    st.session_state.kospi_rate = float(out.get("bstp_nmix_prdy_ctrt", 0.0))
        except: pass

        # 2. 실시간 환율 수집 (TR: FHPST04000000 - 실전망 고정)
        url_fx = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-future-price"
        headers_fx = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHPST04000000", "custtype": "P"
        }
        params_fx = {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": "USD@FX"} 
        try:
            r_fx = self.session.get(url_fx, headers=headers_fx, params=params_fx, timeout=3.0)
            if r_fx.status_code == 200:
                out_fx = r_fx.json().get("output", {})
                if out_fx and out_fx.get("stck_prpr"):
                    st.session_state.fx_rate = f"{float(out_fx.get('stck_prpr')):,.1f} 원"
        except: pass

        # 3. 외국인 실시간 선물 매매동향 수집 (TR: HHPST06430000)
        url_fut = "https://openapi.koreainvestment.com:9443/uapi/domestic-future/v1/quotations/investor-trend"
        headers_fut = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "HHPST06430000", "custtype": "P"
        }
        params_fut = {"FID_COND_MRKT_DIV_CODE": "F", "FID_INPUT_ISCD": "00000000"}
        try:
            r_fut = self.session.get(url_fut, headers=headers_fut, params=params_fut, timeout=3.0)
            if r_fut.status_code == 200:
                out_fut = r_fut.json().get("output1", [])
                for row in out_fut:
                    if "외국인" in row.get("invt_vo", "") and row.get("ntby_mbn_amt"):
                        st.session_state.fut_money = int(float(row.get("ntby_mbn_amt")) / 100)
                        break
        except: pass

    def fetch_single_stock_backup(self, token, query_code):
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json; charset=utf-8", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": APP_SECRET, "tr_id": "FHPST01010000", "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": query_code}
        try:
            r = self.session.get(url, headers=headers, params=params, timeout=3.0)
            if r.status_code == 200:
                out = r.json().get("output", {})
                if out:
                    p_str = "".join(filter(str.isdigit, str(out.get("stck_prpr", "0"))))
                    price = int(p_str) if p_str else 0
                    ctrt = float(out.get("prdy_ctrt", 0.0))
                    stat = str(out.get("iscd_stat_cls_code", "00")).strip()
                    v_str = "".join(filter(str.isdigit, str(out.get("acml_tr_pbmn", "0"))))
                    raw_amt = float(v_str) if v_str else 0.0
                    return {"price": price, "ctrt": ctrt, "amt": raw_amt, "stat": stat}
        except: pass
        return None

    def fetch_market_pool_by_indices(self, token):
        pool = []
        rank_map = {}
        
        # 지수/선물/환율 정품 패킷 동기화 가동
        self.fetch_market_index_radar(token)
        
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
            "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_SORT_CLS_CODE": "4",       
            "FID_BLNG_CLS_CODE": "0", "FID_TRGT_CLS_CODE": "00000000", "FID_TRGT_EXCL_CLS_CODE": "00000000",
            "FID_INPUT_PRICE_1": "0", "FID_INPUT_PRICE_2": "0", "FID_VOL_CNT": "", "FID_INPUT_DATE_1": ""          
        }
        
        try:
            r_vol = self.session.get(url_vol, headers=headers_vol, params=params_vol, timeout=5.0)
            if r_vol.status_code == 200:
                vol_output = r_vol.json().get("output", [])
                
                mega_cap_codes = [
                    "005930", "000660", "005380", "000270", "005490", 
                    "035420", "035720", "068270", "207940", "051910", 
                    "006400", "012450", "011200", "000150", "373220"
                ]
                
                for rank_idx, item in enumerate(vol_output):
                    t_code = str(item.get("mksc_shrn_iscd", "")).strip()[-6:]
                    if not t_code.isdigit(): continue
                    
                    name = str(item.get("hts_kor_isnm", item.get("data_name", ""))).strip()
                    if any(k in name for k in ["스팩", "리츠", "인버스", "레버리지", "KODEX", "TIGER"]): continue
                    
                    p_str_raw = "".join(filter(str.isdigit, str(item.get("stck_prpr", "0"))))
                    price = int(p_str_raw) if p_str_raw else 0
                    
                    ctrt = float(str(item.get("prdy_ctrt", "0.0")).strip())
                    stat = str(item.get("iscd_stat_cls_code", "00")).strip()
                    raw_amt = float(str(item.get("acml_tr_pbmn", "0")).strip())
                    
                    is_mega_cap = (t_code in mega_cap_codes or "하이닉스" in name or "삼성전자" in name or "현대차" in name)
                    
                    if price < 5000 and not is_mega_cap: continue
                    if ctrt <= 0.0 and not is_mega_cap: continue 
                    
                    rank_map[t_code] = True
                    pool.append((rank_idx + 1, t_code, name, price, ctrt, raw_amt, stat))
        except Exception as e:
            st.session_state.net_log = f"❌ 데이터 조회망 패킷 통신 무너짐: {str(e)}"

        watchlist_backups = [("000660", "SK하이닉스"), ("005930", "삼성전자")]
        for b_code, b_name in watchlist_backups:
            if b_code not in rank_map:
                time.sleep(0.2) 
                b_res = self.fetch_single_stock_backup(token, b_code)
                if b_res:
                    pool.append((999, b_code, b_name, b_res["price"], b_res["ctrt"], b_res["amt"], b_res["stat"]))

        st.session_state.net_log = f"🟢 한투 실전망 대장주 순수 동기화 완료! ({datetime.now(tz=KST).strftime('%H:%M:%S')})"
        pool.sort(key=lambda x: x[0]) 
        return pool

# =====================================================================
# ⚡ [상시 표출 시스템]
# =====================================================================
def force_sync_load():
    engine = HantuPureSpeedEngine()
    token = engine.get_token()
    if token:
        st.session_state.last_pool = engine.fetch_market_pool_by_indices(token)

if not st.session_state.last_pool:
    force_sync_load()

# =====================================================================
# 📡 실시간 외국인 선물 수급 & 원/달러 환율 모니터링 탑 (정품 규격화)
# =====================================================================
st.markdown("### 📡 실시간 외국인 선물 수급 & 원/달러 환율 모니터링 탑")
mx_col1, mx_col2, mx_col3 = st.columns(3)

with mx_col1:
    fut_val = st.session_state.fut_money
    if isinstance(fut_val, int):
        if fut_val > 0:
            st.metric(label="📈 외국인 장중 선물 순매수 금액", value=f"+{fut_val:,} 억 원", delta="📈 외국인 실물 상방 타격 중")
        else:
            st.metric(label="📉 외국인 장중 선물 순매수 금액", value=f"{fut_val:,} 억 원", delta="📉 프로그램 매도 압박 주의", delta_color="inverse")
    else:
        st.metric(label="📊 외국인 장중 선물 순매수 금액", value=str(fut_val))

with mx_col2:
    st.metric(label="💵 실시간 원/달러 환율 (FX 정품)", value=str(st.session_state.fx_rate))

with mx_col3:
    kp_rate = st.session_state.kospi_rate
    st.metric(label="📊 코스피(KOSPI) 종합 지수 등락률", value=f"{kp_rate:+.2f}%" if kp_rate > 0 else f"{kp_rate:.2f}%")

# ⚡ [마법의 정석 룰 엔진] 장중 시세와 장외 수집 대기 상태 완벽 격리 배너 수술
if isinstance(fut_val, int):
    if fut_val > 1500:
        st.success("🟢 **[단타 최적 기류]** 외국인 선물 실물 매수 유입 중! 주도주 단타 물량 확대 유효합니다.")
    elif fut_val < -1500:
        st.error("🔴 **[지수 급락 경고]** 외국인 선물 매도 폭탄 투하 중! 프로그램 바스켓 매도가 지수를 누르니 단타 방망이를 짧게 잡으십시오.")
    else:
        st.info("🟡 **[수급 관망 구간]** 외국인 선물이 방향성 없이 보합권 눈치보기 중입니다. 하단 분봉 지지선 확인이 필수입니다.")
else:
    st.info("🔵 **[한투 실전망 인증 세션 대기 구역]** 장중(09:00~15:30)에 한투 라이브 회선이 개방되면 외인 선물 수급과 FX 정품 환율 전광판이 초단위로 동기화됩니다.")

st.markdown("---")

# =====================================================================
# 🖥️ 데이터 제어 버튼 파트
# =====================================================================
cc1, cc2 = st.columns([4, 1])
with cc1:
    btn_fetch = st.button("🔄 한투 실전망 당일 주도주 전체 즉시 동기화", type="primary", use_container_width=True)
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
# 🎯 대표님 전용 실시간 최적 단타 타깃 추출 연산부
# =====================================================================
scalping_targets = []
normal_display_list = []

if isinstance(st.session_state.last_pool, list) and len(st.session_state.last_pool) > 0:
    for row in st.session_state.last_pool:
        if isinstance(row, tuple) and len(row) == 7: 
            raw_rank, t, n, price, ctrt, amt, stat = row
            
            stat_prefix = ""
            if stat in ["58", "59"]: stat_prefix = "[🚨VI발동] "
            elif stat == "52": stat_prefix = "[⚠️유의] "
            elif stat == "51": stat_prefix = "[❌관리] "
            elif stat == "57": stat_prefix = "[🔥경고] "

            mega_cap_codes = ["005930", "000660", "005380", "000270", "005490", "035420", "035720", "068270", "207940", "051910", "006400", "012450", "011200", "000150", "373220"]
            is_mega_cap = (t in mega_cap_codes or "하이닉스" in n or "삼성전자" in n or "현대차" in n)
            amt_display = f"{int(amt / 100000000):,}억 원" if amt > 0 else "실시간 집계 중"

            if raw_rank <= 20 and (4.0 <= ctrt <= 12.0) and not is_mega_cap:
                scalping_targets.append({
                    "포착순위": f"🔥 {len(scalping_targets) + 1}순위",
                    "종목코드": t,
                    "종목명": f"🎯[단타타깃] {stat_prefix}{n}",
                    "현재가": f"{price:,}원",
                    "등락률": f"{ctrt:+.2f}%",
                    "당일 거래대금": amt_display,
                    "실전 타격 지침": "🚀 거래대금 상위권 폭발! 등락률 +4%~12% 꿀맛 단타 타점 (하단 분봉 눌림목 관찰)"
                })
            
            if raw_rank == 999:
                d_name, r_grade, a_tag = f"🏛️[순위권밖-강제포획] {stat_prefix}{n}", "📊 지수 연동형 메가크라운 대형주", "⚡ 한투 100위권 밖에 위치함 / 실시간 백업 엔진 자동 연동"
            elif raw_rank <= 20 and ctrt >= 4.0 and not is_mega_cap:
                d_name, r_grade, a_tag = f"🔥[우량주도-최강] {stat_prefix}{n}", "🔥 1단계: A급 (시세 강력 분출)", "🚀 대한민국 시장 자금을 가장 빠르게 빨아들이는 핵심 대장"
            elif is_mega_cap:
                d_name, r_grade, a_tag = f"🏛️[시장지수-대장] {stat_prefix}{n}", "📊 지수 연동형 메가크라운 대형주", "⚡ 대한민국 증시 지수 상위 대장주 (장중 시황 체크용)"
            else:
                d_name, r_grade, a_tag = f"{stat_prefix}{n}", "⚡ 2단계: B급 (견고한 거래량 쏠림)", "🟢 수급 확인 완료 / 하단 차트 패널에서 분봉 파동 추적"

            normal_display_list.append({
                "당일 대금 순위": "100위권 밖" if raw_rank == 999 else f"{raw_rank}위",
                "종목코드": t,
                "종목명": d_name,
                "수급 등급 분류": r_grade,
                "현재가": f"{price:,}원", 
                "등락률": f"{ctrt:+.2f}%" if ctrt > 0 else f"{ctrt:.2f}%",
                "당일 누적대금": amt_display,
                "실전 행동 지침": a_tag
            })

df_scalping = pd.DataFrame(scalping_targets)
df_normal = pd.DataFrame(normal_display_list)

selected_ticker = None
selected_name = None

# =====================================================================
# 🖥️ 상단 전광판 렌더링 구역
# =====================================================================
st.markdown("## 🎯 [대표님 전용] AI 장중 변동성 실시간 단타 최우선 타깃")
if not df_scalping.empty:
    df_scalping.insert(0, "선택", False)
    df_scalping.loc[0, "선택"] = True
    
    edited_sc_df = st.data_editor(
        df_scalping, use_container_width=True, hide_index=True,
        column_config={"선택": st.column_config.CheckboxColumn(required=True)},
        disabled=["포착순위", "종목코드", "종목명", "현재가", "등락률", "당일 거래대금", "실전 타격 지침"],
        height=200
    )
    sc_selected = edited_sc_df[edited_sc_df["선택"] == True]
    if not sc_selected.empty:
        selected_ticker = sc_selected.iloc[0]["종목코드"]
        selected_name = sc_selected.iloc[0]["종목명"].split("]")[-1].strip()
else:
    st.info("💡 지금 이 순간에는 거래대금 상위 20위 내에서 등락률 +4% ~ +12% 규격에 맞는 안전한 단타 주도주가 없습니다. 무리한 진입 금지 / 하단 마스터 시황판을 점검해 주십시오.")

st.markdown("### 📊 당일 실시간 주도주 마스터 종합 순위표 (시황 전광판)")
if not df_normal.empty:
    if not selected_ticker:
        df_normal.insert(0, "선택", False)
        df_normal.loc[0, "선택"] = True
        
        edited_nm_df = st.data_editor(
            df_normal, use_container_width=True, hide_index=True,
            column_config={"선택": st.column_config.CheckboxColumn(required=True)},
            disabled=["당일 대금 순위", "종목코드", "종목명", "수급 등급 분류", "현재가", "등락률", "당일 누적대금", "실전 행동 지침"],
            height=350
        )
        nm_selected = edited_nm_df[edited_nm_df["선택"] == True]
        if not nm_selected.empty:
            selected_ticker = nm_selected.iloc[0]["종목코드"]
            selected_name = nm_selected.iloc[0]["종목명"].split("]")[-1].strip()
    else:
        st.dataframe(df_normal, use_container_width=True, hide_index=True, height=350)
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
