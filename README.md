# 📈 나의 투자도우미 (My Investment Assistant)

실시간 금융 데이터(네이버 금융 · FinanceDataReader · yfinance), Serper 최신 뉴스, 그리고 Dify AI 챗봇을 결합한 **3탭 통합 주식·ETF 투자 분석 웹 애플리케이션**입니다.

---

## ✨ 주요 기능

### 1. 심층분석 탭 (`1. 심층분석`)
* **국내·미국 주식 & ETF 통합 지원 (`[국내 주식/ETF]` · `[미국 주식/ETF]` 자동 인식)**
  * 국내 주식(`000660`, `SK하이닉스`), 국내 ETF(`KODEX 200`), 미국 주식(`NVDA`, `AAPL`), 미국 ETF(`SPY`, `SCHD`) 모두 지원
* **핵심 요약 & AI 심층분석 채팅**
  * 기업/ETF 개요, 현재가·등락률, 8종 핵심 투자지표(시가총액, PER, 추정PER, PBR, 외인소진율, 배당수익률, 52주 최고/최저) 표시
  * 수집된 JSON 근거만을 바탕으로 답변하는 **Dify 종목분석기 챗봇** 연동 (마크다운 서식 렌더링 & 종목 맞춤 추천 질문 카드 제공)
* **일반 기업 전용: 3대 재무제표 시각화 & 최근 공시(DART)**
  * **재무분석**: 포괄손익계산서 · 재무상태표 · 현금흐름표를 **왼쪽 막대그래프 / 오른쪽 꺾은선 차트**로 나란히 시각화하고, 전체 표 보기/접기 토글 제공
  * **최근 공시**: 정기보고서·실적·자사주 취득/처분·주주환원·임원/주요주주 분류 필터, 기본 5건 표시 + 전체 보기(`1, 2, 3` 페이지네이션), DART 공식 바로가기 링크 제공
* **ETF 전용: 핵심 정보 & 구성종목 TOP 10**
  * 운용사, 기초지수, 순자산총액(AUM), 총보수(수수료), 분배율, 괴리율, 1년 수익률 및 **구성종목 TOP 10 도넛 차트·비중 표** 자동 전환
* **최신 관련 뉴스**: Serper News API로 수집한 최신 기사 5건 (원문 새 창 링크)

### 2. 리밸런싱 도우미 탭 (`2. 리밸런싱 도우미`) — *AI 미사용, 순수 Python 계산*
* 보유 종목/ETF 여러 개를 입력하면 `FinanceDataReader` 최근 1년 일별 주가를 수집
* **3,000회 몬테카를로 시뮬레이션 & 효율적 프론티어**를 계산해 최대 샤프지수 기준 추천 비중, 연 기대수익률, 변동성, MDD 산출
* 추천 비중 도넛 차트 & 효율적 프론티어 산점도 시각화

### 3. 기술지표 차트 + 채팅 탭 (`3. 기술지표 차트 + 채팅`)
* `FinanceDataReader`로 **이동평균선(MA 5/20/60), 볼린저밴드(20, 2), RSI(14), MACD(12, 26, 9)**를 Python으로 계산 및 차트 2종 렌더링
* 계산된 최신 지표 숫자를 **Dify 지표해석기 챗봇**에 자동 주입해 초보자 눈높이로 설명

### 4. 1차 수집기 단독 테스트 화면 (`/test`)
* 기존 1차 종목 데이터 수집/브리핑 화면을 `/test` 경로에 보존하여 독립 테스트 가능

---

## 🛠️ 기술 스택 (Tech Stack)
* **Backend**: Python, Flask, Requests, python-dotenv
* **Financial Data & Quant**: `FinanceDataReader`, `yfinance`, `Pandas`, `NumPy`
* **AI & Search**: Dify Chatbot API (`종목분석기`, `지표해석기`), Serper News API
* **Frontend**: Vanilla JavaScript, HTML5, CSS3 (Slate-Blue 금융 대시보드 UI), `Chart.js`
* **Deployment**: Vercel (`vercel.json`)

---

## 📁 프로젝트 구조
```text
investment-assistant/
├── app.py               # Flask 서버 및 모든 웹/API 라우트
├── collector.py         # 국내·미국 주식/ETF, 재무제표, 공시, Serper 뉴스 수집기
├── portfolio.py         # FDR 최근 1년 주가 기반 몬테카를로 리밸런싱 계산기
├── technical.py         # FDR 기반 MA, RSI, MACD, 볼린저밴드 계산기
├── dify_client.py       # Dify 챗봇 API (/chat-messages) 호출 모듈
├── run.bat              # Windows 원클릭 실행 배치 파일
├── vercel.json          # Vercel 배포 설정
├── requirements.txt
├── templates/
│   ├── index.html       # 3탭 통합 메인 화면
│   └── test.html        # 1차 수집기 테스트 화면 (/test)
└── static/
    ├── style.css        # 슬레이트 그레이 & 딥 네이비 블루 금융 테마
    ├── app.js           # 3탭 프론트엔드 로직 및 Chart.js 시각화
    └── test.js          # /test 화면 전용 JS
```

---

## 🚀 로컬 실행 방법 (Getting Started)

1. **가상환경 활성화**
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
2. **패키지 설치**
   ```powershell
   pip install -r requirements.txt
   ```
3. **환경변수 설정 (`.env`)**
   `.env.example`을 복사하여 `.env`를 생성하고 API 키를 입력합니다.
   ```text
   SERPER_API_KEY=...
   DIFY_BASE_URL=https://api.dify.ai/v1
   DIFY_ANALYSIS_API_KEY=...
   DIFY_TECH_API_KEY=...
   FLASK_DEBUG=true
   ```
4. **앱 실행**
   * Windows에서는 **`run.bat`** 을 더블클릭하거나, 터미널에서 아래 명령어를 실행한 뒤 `http://127.0.0.1:5000`으로 접속합니다.
   ```powershell
   python app.py
   ```
