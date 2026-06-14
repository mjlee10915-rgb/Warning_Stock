import streamlit as st
import requests
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta
import io

st.set_page_config(page_title="투자경고 종목 자동 분석기", layout="wide")

st.title("🚨 투자경고 종목 주가 흐름 자동 분석기")
st.caption("KIND 사이트에서 2026년 4월 이후 지정된 투자경고 종목을 자동으로 가져와 전후 주가 흐름을 보여줍니다.")

# 전역 공통 헤더 설정 (브라우저인 척 위장)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://kind.krx.co.kr/investwarn/investattentwarnrisky.do?method=investattentwarnriskyMain'
}

# 1. KIND 사이트에서 투자경고 종목 데이터 크롤링 함수
@st.cache_data(ttl=3600)  # 1시간 동안 캐싱
def fetch_warn_stocks():
    url = "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do?method=investattentwarnriskySub"
    
    payload = {
        'currentPageSize': '100',
        'pageIndex': '1',
        'orderMode': '0',
        'orderStat': 'D',
        'searchType': '1',  # 투자경고종목 기준
        'fromDate': '2026-04-01',
        'toDate': datetime.today().strftime('%Y-%m-%d')
    }
    
    try:
        response = requests.post(url, data=payload, headers=HEADERS)
        response.raise_for_status() # 에러 발생 시 예외 처리
        
        # StringIO를 사용해 pandas의 경고 방지 및 lxml 파싱
        dfs = pd.read_html(io.StringIO(response.text))
        if dfs:
            df = dfs[0]
            df.columns = [col.strip() for col in df.columns]
            df = df[['종목명', '지정일', '해제일(예정일)']]
            return df
    except Exception as e:
        st.error(f"KIND 투자경고 데이터를 가져오는 중 오류가 발생했습니다. (서버 차단 가능성): {e}")
        return pd.DataFrame()

# 2. KRX 종목코드 마스터 데이터 가져오기 (차단 우회 버전)
@st.cache_data
def get_krx_tickers():
    url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    try:
        # pd.read_html(url)을 쓰면 헤더가 없어 차단되므로 requests를 사용
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        
        # CP949 인코딩 처리하여 한글 깨짐 방지
        df = pd.read_html(io.StringIO(response.content.decode('cp949')))[0]
        df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
        return df[['회사명', '종목코드']]
    except Exception as e:
        st.error(f"KRX 종목 마스터 데이터를 가져오는 중 오류가 발생했습니다: {e}")
        return pd.DataFrame()

# 데이터 로드
warn_df = fetch_warn_stocks()
ticker_master = get_krx_tickers()

if not warn_df.empty and not ticker_master.empty:
    # 종목명 기준으로 종목코드 합치기
    warn_df = pd.merge(warn_df, ticker_master, left_on='종목명', right_on='회사명', how='left')
    warn_df = warn_df.dropna(subset=['종목코드']).reset_index(drop=True)
    
    if not warn_df.empty:
        st.subheader("📌 2026년 4월 이후 투자경고 지정 종목 리스트")
        st.caption("분석하고 싶은 종목을 선택하세요.")
        
        selected_idx = st.selectbox(
            "조회할 종목을 선택하세요:",
            range(len(warn_df)),
            format_func=lambda x: f"[{warn_df.loc[x, '지정일']}] {warn_df.loc[x, '종목명']} ({warn_df.loc[x, '종목코드']})"
        )
        
        selected_stock = warn_df.loc[selected_idx]
        ticker = selected_stock['종목코드']
        ticker_name = selected_stock['종목명']
        warn_date_str = selected_stock['지정일'].replace('.', '-').strip()
        warn_date = datetime.strptime(warn_date_str, '%Y-%m-%d')
        
        # 3. 주가 데이터 수집 및 시각화
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
                
                start_idx = max(0, warn_idx - 5)
                end_idx = min(len(df), warn_idx + 16)
                analysis_df = df.iloc[start_idx:end_idx].copy()
                
                analysis_df['D-Day'] = [f"D{i-warn_idx:+d}" if i != warn_idx else "D-Day" for i in analysis_df.index]
                
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
        st.info("KIND에서 매핑된 매칭 종목이 없습니다.")
else:
    st.info("KIND 사이트에서 투자경고 종목 데이터를 가져오는 중이거나 데이터가 없습니다.")
