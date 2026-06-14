import streamlit as st
import requests
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="투자경고 종목 자동 분석기", layout="wide")

st.title("🚨 투자경고 종목 주가 흐름 자동 분석기")
st.caption("KIND 사이트에서 2026년 4월 이후 지정된 투자경고 종목을 자동으로 가져와 전후 주가 흐름을 보여줍니다.")

# 1. KIND 사이트에서 투자경고 종목 데이터 크롤링 함수
@st.cache_data(ttl=3600)  # 1시간 동안 캐싱하여 속도 향상 및 서버 부하 방지
def fetch_warn_stocks():
    url = "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do?method=investattentwarnriskySub"
    
    # 2026년 4월 1일 이후 데이터를 가져오기 위한 파라미터 설정
    payload = {
        'currentPageSize': '100',
        'pageIndex': '1',
        'orderMode': '0',
        'orderStat': 'D',
        'searchType': '1',  # 투자경고종목 기준
        'fromDate': '2026-04-01',
        'toDate': datetime.today().strftime('%Y-%m-%d')
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.post(url, data=payload, headers=headers)
        # HTML 내의 테이블 읽기
        dfs = pd.read_html(response.text)
        if dfs:
            df = dfs[0]
            # 컬럼명 정제 (공백 제거)
            df.columns = [col.strip() for col in df.columns]
            
            # 필요한 컬럼만 추출 및 정리
            # KIND 테이블 구조에 맞춰 컬럼 인덱스나 이름으로 접근
            df = df[['종목명', '지정일', '해제일(예정일)']]
            
            # 종목코드 매핑을 위해 종목명 뒤에 붙은 코드 추출 또는 yfinance 검색용 데이터 정리
            # KIND는 보통 종목명에 코드가 함께 들어가거나 링크에 숨어있으므로, 
            # 한국거래소(KRX) 상장종목 마스터 데이터를 활용해 코드를 매핑하는 것이 안전합니다.
            return df
    except Exception as e:
        st.error(f"KIND 데이터를 가져오는 중 오류가 발생했습니다: {e}")
        return pd.DataFrame()

# KRX 종목코드 마스터 데이터 가져오기 (종목명 -> 종목코드 변환용)
@st.cache_data
def get_krx_tickers():
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    df = pd.read_html(url)[0]
    df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
    return df[['회사명', '종목코드']]

# 데이터 로드
warn_df = fetch_warn_stocks()
ticker_master = get_krx_tickers()

if warn_df is not None and not warn_df.empty:
    # 종목명 기준으로 종목코드 합치기
    warn_df = pd.merge(warn_df, ticker_master, left_on='종목명', right_on='회사명', how='left')
    # 결측치 제거 및 데이터 정제
    warn_df = warn_df.dropna(subset=['종목코드']).reset_index(drop=True)
    
    # 상단에 추출된 종목 리스트 보여주기
    st.subheader("📌 2026년 4월 이후 투자경고 지정 종목 리스트")
    st.caption("분석하고 싶은 종목을 클릭(선택)하세요.")
    
    # 사용자가 클릭하여 선택할 수 있는 Selectbox 또는 Dataframe 선택 기능
    selected_idx = st.selectbox(
        "조회할 종목을 선택하세요:",
        range(len(warn_df)),
        format_func=lambda x: f"[{warn_df.loc[x, '지정일']}] {warn_df.loc[x, '종목명']} ({warn_df.loc[x, '종목코드']})"
    )
    
    # 선택된 종목 정보 추출
    selected_stock = warn_df.loc[selected_idx]
    ticker = selected_stock['종목코드']
    ticker_name = selected_stock['종목명']
    warn_date_str = selected_stock['지정일'].replace('.', '-').strip() # 날짜 포맷 통일
    warn_date = datetime.strptime(warn_date_str, '%Y-%m-%d')
    
    # 2. 주가 데이터 수집 및 시각화
    # 코스피/코스닥 구분을 위해 우선 양쪽 다 시도하거나 마스터 정보 활용 (여기서는 두 코드 모두 탐색)
    df = pd.DataFrame()
    for suffix in ['.KS', '.KQ']:
        full_ticker = f"{ticker}{suffix}"
        start_date = warn_date - timedelta(days=15)
        end_date = warn_date + timedelta(days=30)
        
        tmp_df = yf.download(full_ticker, start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'), progress=False)
        if not tmp_df.empty:
            df = tmp_df
            break
            
    if not df.empty:
        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        df['Date_str'] = df['Date'].dt.strftime('%Y-%m-%d')
        exact_match = df[df['Date_str'] >= warn_date_str]
        
        if not exact_match.empty:
            warn_idx = exact_match.index[0]
            
            # 전 5일 ~ 후 15일 영업일 슬라이싱
            start_idx = max(0, warn_idx - 5)
            end_idx = min(len(df), warn_idx + 16)
            analysis_df = df.iloc[start_idx:end_idx].copy()
            
            # D-Day 라벨링
            analysis_df['D-Day'] = [f"D{i-warn_idx:+d}" if i != warn_idx else "D-Day" for i in analysis_df.index]
            
            # 시각화 레이아웃
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"📈 {ticker_name} ({ticker}) 주가 흐름 (지정일: {warn_date_str})")
                fig = go.Figure(data=[go.Candlestick(
                    x=analysis_df['D-Day'],
                    open=analysis_df['Open'],
                    high=analysis_df['High'],
                    low=analysis_df['Low'],
                    close=analysis_df['Close'],
                    name="주가"
                )])
                
                fig.add_vline(x="D-Day", line_width=2, line_dash="dash", line_color="red")
                fig.update_layout(xaxis_title="지정일 기준", yaxis_title="주가 (원)", xaxis_rangeslider_visible=False, height=500)
                st.plotly_chart(fig, use_container_width=True)
                
            with col2:
                st.subheader("📋 상세 데이터")
                st.dataframe(
                    analysis_df[['Date_str', 'D-Day', 'Close']].rename(columns={'Date_str':'날짜', 'Close':'종가'}),
                    height=450, hide_index=True
                )
        else:
            st.warning("경고 지정일 이후의 주가 데이터가 아직 존재하지 않습니다.")
    else:
        st.error("yfinance에서 주가 데이터를 불러오지 못했습니다.")
else:
    st.info("KIND 사이트에서 2026년 4월 이후 지정된 투자경고 종목 데이터를 찾지 못했거나 가져오는 중입니다.")
