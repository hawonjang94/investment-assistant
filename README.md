# 📈 AI 주식 투자 보조 비서 (Investment Assistant)

AI(Google Gemini 및 Dify)와 실시간 금융/뉴스 검색 API를 결합한 스마트 주식 지표 분석 및 투자 인사이트 웹 애플리케이션입니다.

---

## 🛠️ 기술 스택 (Tech Stack)
- **Backend / Web**: Python, Flask
- **AI Engine**: Google Gemini API, Dify AI Agent
- **News / Search**: Serper API
- **Deployment**: Vercel

---

## 🚀 로컬 실행 방법 (Getting Started)

1. **가상환경 활성화**
   ```bash
   # Windows (PowerShell)
   .\venv\Scripts\Activate.ps1
   ```

2. **패키지 설치**
   ```bash
   pip install -r requirements.txt
   ```

3. **환경변수 설정**
   `.env.example`을 복사하여 `.env`를 생성하고 API 키를 입력합니다.
   ```bash
   cp .env.example .env
   ```

4. **앱 실행**
   ```bash
   python app.py
   ```
