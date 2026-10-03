# 다른 PC(회사 등)에서 이어서 작업하기

이 프로젝트는 GitHub(`Hyyyyk/stock-screener`)에 있고, 배포 앱은
`https://stock-screener-9qe42kwt7kpjrakv3z6ilt.streamlit.app/` 에서 돈다.
아래대로 하면 다른 PC에서도 Claude Code로 이어서 개발할 수 있다.

## 0. 준비물 (한 번만 설치)
- **Claude 데스크톱 앱** — 설치 후 본인 계정 로그인. Code 탭에서 이 폴더를 연다.
- **GitHub Desktop** — 설치 후 `Hyyyyk` 계정 로그인. (터미널 git 인증이 번거로워 이걸 쓴다.)
- **Python 3** — 설치 확인:
  ```bash
  python --version
  ```

## 1. 저장소 내려받기 (clone)
GitHub Desktop → File → **Clone repository** → `Hyyyyk/stock-screener` 선택 → 로컬 폴더로.
(또는 터미널: `git clone https://github.com/Hyyyyk/stock-screener.git`)

`stocks.db`가 같이 딸려오므로 앱은 바로 실행된다. `cache/`(75MB)·`.env`는 안 온다.

## 2. 파이썬 패키지
```bash
pip install streamlit pandas
```

## 3. DART 키 넣기 (.env)  — 수집·한국 상세를 쓸 때만 필요
프로젝트 폴더에 `.env` 파일을 만들고 한 줄:
```
DART_API_KEY=발급받은40자리키
```
키는 opendart.fss.or.kr 에서 발급/재발급. (`.env`는 GitHub에 안 올라간다.)

## 4. 실행
```bash
streamlit run app.py
```
→ http://localhost:8501

## 5. 작업 흐름 (두 PC 오갈 때)
- **시작 전**: GitHub Desktop에서 **Fetch/Pull** 로 최신 받기 (충돌 방지)
- 코드 고치고 → **Commit** → **Push origin**
- push하면 배포 앱(streamlit.app)이 자동으로 다시 뜬다

## 6. 데이터 갱신 (원할 때)
```bash
python collect_price.py && python collect_flow.py     # 시세·수급 (매일)
# 분기·연도가 바뀌면: python collect_us.py / collect_kr.py / collect_sic.py
```
갱신 후 `stocks.db`를 Commit → Push 하면 배포 앱에도 반영된다.

## 참고
- 회사 네트워크가 SEC·DART·Yahoo·네이버 API를 막으면 수집이 안 될 수 있다(앱을 브라우저로 보는 건 대개 됨).
- 각 파일 첫 줄 주석에 역할이 적혀 있다: collect_us(SEC 재무) · collect_kr(DART 재무·주식수·업종) ·
  collect_price(Yahoo 시세·환율) · collect_sic(미국 업종) · collect_flow(네이버 수급) ·
  data.py(합쳐서 화면에 넘김) · app.py(화면) · test_*.py(점검).
