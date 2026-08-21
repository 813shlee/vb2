# 한국 주식 밸류에이션 보드

네이버 증권 현재가와 FnGuide/WiseReport 연간 컨센서스 EPS·BPS를 모아 PER/PBR 목표가를 비교하는 정적 웹페이지입니다. GitHub Pages에서 서버 없이 작동하며, 사용자의 평가 방식·반영률·목표 배수·관심 종목은 브라우저 `localStorage`에 저장됩니다.

## 새 VB2 저장소 설치

1. GitHub에서 이름이 `vb2`인 Public 저장소를 만들고 README 자동 생성 옵션은 선택하지 않습니다.
2. 이 배포 묶음의 내용 전체를 폴더 구조 그대로 저장소 최상위에 업로드하고 커밋합니다. `.github`는 숨김 폴더이므로 압축을 푼 뒤 폴더 구조가 유지되었는지 확인합니다.
3. **Settings → Pages → Build and deployment → Source**를 **GitHub Actions**로 선택합니다.
4. **Settings → Actions → General → Workflow permissions**에서 **Read and write permissions**를 선택하고 저장합니다.
5. **Actions → Update valuation data → Run workflow**에서 `all`을 선택해 최초 데이터를 수집합니다.
6. 배포가 끝나면 `https://813shlee.github.io/vb2/`에서 확인합니다.

새 저장소가 정상 작동하는 것을 확인한 뒤에만 기존 `vb` 저장소를 삭제하세요. 저장소 삭제는 GitHub의 **Settings → General → Danger Zone → Delete this repository**에서 진행하며 되돌리기 어렵습니다.

## 로컬 실행

### Python 없이 확인

`valuation-board-single.html`은 CSS, JavaScript, 초기 데이터가 모두 포함된 단일 파일입니다. 파일을 더블클릭하면 바로 확인할 수 있습니다. 이 파일의 데이터는 생성 시점에 고정되므로 자동 갱신이 필요하면 아래의 일반 버전이나 GitHub Pages를 사용하세요.

단일 파일을 최신 `data/stocks.json`으로 다시 만들려면 Windows PowerShell에서 다음을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_single_file.ps1
```

### 일반 버전

Python 3가 설치된 폴더에서 다음을 실행합니다.

```bash
python -m http.server 8000
```

브라우저에서 `http://localhost:8000`을 엽니다. `index.html`을 파일로 직접 열면 브라우저 보안 정책 때문에 JSON을 읽지 못할 수 있습니다.

데이터를 새로 수집하려면:

```bash
python scripts/collect.py
```

SK하이닉스만 검증하려면:

```bash
python scripts/collect.py --code 000660 --output work/skhynix.json --strict
```

파서 단위 테스트:

```bash
python -m unittest discover -s tests -v
```

## 계산 규칙

- PER 선택: 기준값은 EPS, 목표가 = EPS × 목표 PER
- PBR 선택: 기준값은 BPS, 목표가 = BPS × 목표 PBR
- 2027 보수 기준: 2027 컨센서스 EPS/BPS × 사용자 반영률(기본 90%)
- 상승/하락 여력: 목표가 ÷ 현재가 − 1
- 컨센서스 변화율: 이번 주 EPS/BPS ÷ 직전 주 EPS/BPS − 1
- 투자자별 순매매: 네이버가 제공하는 해당 거래일의 기관·외국인 누적 순매매 수량
- 카드의 강조 목표가와 여력은 세 목표 배수 중 첫 번째 값을 사용

## GitHub Pages 배포

1. 저장소의 기본 브랜치를 `main`으로 둡니다.
2. GitHub의 **Settings → Pages → Source**를 **GitHub Actions**로 선택합니다.
3. 저장소에 push하면 `Deploy GitHub Pages` 워크플로가 배포합니다.
4. `Update hourly prices`는 평일 한국시간 09:05~16:05에 매시간 네이버 현재가만 갱신합니다.
5. `Update weekly consensus`는 매주 토요일 07:30(KST)에 FnGuide 컨센서스를 5개씩 3묶음으로 갱신합니다.

Actions가 데이터를 commit하려면 **Settings → Actions → General → Workflow permissions**에서 Read and write permissions가 허용되어야 합니다.

## 데이터 수집 구조

1. 매시간 네이버 종목 페이지에서 종목명·현재가·기준일과 기관·외국인 누적 순매매 수량을 읽습니다.
2. 주 1회 WiseReport 컨센서스 페이지의 기준일(`hidDT`)을 찾습니다.
3. 페이지가 사용하는 연간 컨센서스 JSON 엔드포인트에서 EPS·BPS를 수집합니다.
4. 갱신 직전 컨센서스를 `previousAnnual`에 보관하고 새 값과의 변화율을 화면에 표시합니다.

## 새로운 종목 추가

공용 종목 목록은 `config/stocks.json`에서 관리합니다. Python 파일을 수정할 필요 없이 다음 형태의 항목을 배열에 추가합니다.

```json
{ "code": "035420", "name": "NAVER", "defaultMetric": "PER" }
```

저장 후 GitHub의 `Actions → Update valuation data → Run workflow`를 실행합니다. 수집이 성공하면 웹페이지의 `종목 추가`에서 해당 6자리 코드를 입력해 카드로 표시할 수 있습니다. `defaultMetric`은 `PER` 또는 `PBR`만 사용할 수 있으며 종목코드는 중복 없이 정확히 6자리여야 합니다.

`Update hourly prices`는 수동 실행하면 현재가만 즉시 갱신합니다. `Update weekly consensus`에서 `all`을 선택하면 3개 묶음을 차례로 수집하며 약 6~12분이 걸릴 수 있습니다. 특정 묶음만 다시 시도하려면 `1`~`3` 중 하나를 선택합니다.

투자자별 순매매 수량은 현재가 작업과 함께 매시간 확인하지만 원천 페이지 반영이 지연될 수 있습니다. 양수는 빨간색 순매수, 음수는 파란색 순매도로 표시합니다. 투자자 데이터만 일시적으로 실패하면 직전 값을 유지하고 가격 업데이트는 계속 진행합니다.

특정 종목의 통신이 일시적으로 실패하면 최대 3회 재시도합니다. 그래도 실패할 경우 직전 정상 데이터를 유지하고 카드에 `이전 데이터 유지`라고 표시하며, 실패 내역은 JSON의 `failures`에 기록합니다. 이전 데이터조차 없는 신규 종목만 화면에서 제외됩니다. 페이지 구조가 바뀌면 `scripts/collect.py`의 선택자/정규식을 조정해야 합니다.

> 이 페이지는 투자 참고용입니다. 원천 데이터는 지연되거나 오류가 있을 수 있으며, 원 데이터 제공자의 이용 조건을 확인해 사용하세요.
