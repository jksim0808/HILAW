import requests
import json
import pandas as pd

# 1. 한투 API 인증 정보 설정 (본인의 키를 입력하세요)
APP_KEY = "YOUR_APP_KEY_HERE"
APP_SECRET = "YOUR_APP_SECRET_HERE"
URL_BASE = "https://openapi.koreainvestment.com:9443"  # 실전투자 기준 (모의투자는 8443)


def get_access_token():
    """한투 API 접근 토큰 발급"""
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "secretkey": APP_SECRET
    }
    PATH = "oauth2/tokenP"
    res = requests.post(f"{URL_BASE}/{PATH}", headers=headers, data=json.dumps(body))
    return res.json()["access_token"]


def get_high_volatility_stocks(token):
    """국내 주식 당일 변동폭 상위 종목 조회"""
    # 전일대비 등락 및 당일 고저폭을 볼 수 있는 거래대금 상위/거래량 상위 API 활용
    PATH = "uapi/domestic-stock/v1/ranking/trade-vol"  # 거래량/거래대금 상위 순위 API

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "secretkey": APP_SECRET,
        "tr_id": "FHPST01710000"  # 거래대금/거래량 순위 TR ID
    }

    # API 요청 파라미터 (전체 시장, 거래대금 순)
    params = {
        "user_id": "",
        "seq": "",
        "data_cnt": "",
        "ranking_option": "1",  # 1: 거래대금 순
        "market_div": "0000",  # 0000: 전체 시장 (코스피 + 코스닥)
        "industry_div": "0000"  # 전체 업종
    }

    res = requests.get(f"{URL_BASE}/{PATH}", headers=headers, params=params)
    data = res.json()['output']

    # 데이터프레임으로 변환
    df = pd.DataFrame(data)

    # 필요한 컬럼 숫자로 형변환 (한투 API는 기본적으로 문자열로 반환함)
    df['stck_prpr'] = df['stck_prpr'].astype(int)  # 현재가
    df['stck_hgpr'] = df['stck_hgpr'].astype(int)  # 고가
    df['stck_lwpr'] = df['stck_lwpr'].astype(int)  # 저가
    df['acml_tr_pbmn'] = df['acml_tr_pbmn'].astype(int) // 100000000  # 거래대금 (억원 단위 변환)

    # 2. 당일 변동폭(고저차 비율) 계산 공식 적용
    # 공식: (고가 - 저가) / 현재가 * 100
    df['변동폭(%)'] = ((df['stck_hgpr'] - df['stck_lwpr']) / df['stck_prpr'] * 100).round(2)

    # 3. 데이터 필터링 및 정렬
    # - 거래대금 50억 원 이상인 종목 중
    # - 변동폭이 큰 순서대로 정렬
    filtered_df = df[df['acml_tr_pbmn'] >= 50]
    result = filtered_df[['hts_kor_isnm', 'stck_prpr', '변동폭(%)', 'acml_tr_pbmn']].sort_values(by='변동폭(%)',
                                                                                              ascending=False)

    # 컬럼명 깔끔하게 변경
    result.columns = ['종목명', '현재가', '하루 변동폭(%)', '거래대금(억)']

    return result.head(20)  # 상위 20개 종목 반환


# 실행부
if __name__ == "__main__":
    try:
        token = get_access_token()
        print("💡 한투 API 토큰 발급 성공! 데이터 분석을 시작합니다...\n")

        top_volatile_stocks = get_high_volatility_stocks(token)
        print("🔥 [오늘의 하루 변동폭 TOP 20 종목 리스트] 🔥")
        print(top_volatile_stocks.to_string(index=False))

    except Exception as e:
        print(f"❌ 오류 발생: {e}\nAPI Key 입력 상태나 장마감 후 서버 상태를 확인하세요.")