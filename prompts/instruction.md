# Imaging Intelligence Daily Briefing — Agent Runbook (instruction.md)

> cs.LG · cs.CV · cs.AI · eess.IV · eess.SP를 매일 훑어 동향 브리핑을 만드는 실행용 프롬프트.
> 실제 실행 시에는 아래 변수를 본인 환경 값으로 채워 사용한다.
>
> ```text
> WORKDIR={WORKDIR}
> SLACK_CHANNEL={SLACK_CHANNEL}
> SLACK_CHANNEL_ID={SLACK_CHANNEL_ID}
> GITHUB_REPO=IIL-SNU/paper-daily-summary
> SITE_URL=https://iilab.io/paper-daily-summary
> ```
---

## [0. 실행 변수]

```text
WORKDIR={WORKDIR}
SLACK_CHANNEL={SLACK_CHANNEL}
SLACK_CHANNEL_ID={SLACK_CHANNEL_ID}
GITHUB_REPO=IIL-SNU/paper-daily-summary
SITE_URL=https://iilab.io/paper-daily-summary
```

이 프롬프트에서 개인 경로, Slack channel id, Slack channel name은 모두 위 변수만 참조한다.
공개 repo에 백업할 때 실제 값을 쓰지 않는다.

---

## [1. 최상위 원칙]

1. **WebFetch 금지.** arXiv `/new` · `/pastweek` 목록은 반드시 `scripts/fetch_arxiv.py`로 파싱한다.
2. **잘못된 배치 발행 금지.** parser가 실패하면 WebFetch로 대체하지 말고 중단하거나 parser/encoding 문제를 고친다.
3. **누락일 복구 우선.** 월요일 weekly보다 지난주 빠진 평일 daily 산출물이 우선이다.
4. **오늘 논문은 `/new`, 주간 해석은 `/pastweek`.** 오늘 논문 요약은 `/new` abstract 기준, 주간 동향과 추천 연구주제는 `/pastweek` 패턴 기준.
5. **산출물은 repo 상태로 검증 후 push.** push 성공 후에만 Slack을 보낸다.
6. **날짜가 맞지 않으면 발행하지 않는다.** `/new`의 실제 `listing_date`와 발행하려는 `post_date`가 다르면 daily mode가 아니라 backfill mode다.
7. **클러스터 표는 템플릿이 아니다.** 직전 daily와 같은 cluster 제목을 재사용하려면 대표 논문과 `왜 중요?`가 실제로 달라야 한다. 같은 제목 4개 이상이 반복되면 미완성 산출물로 본다.

---

## [2. 날짜 개념 분리]

매 실행마다 아래 세 날짜를 분리해 기록한다.

```text
execution_date = agent가 실제 실행되는 날짜
listing_date   = arXiv /new 페이지가 실제로 가리키는 공지 날짜
post_date      = daily HTML 파일명에 쓸 날짜
weekly_date    = weekly HTML 파일명에 쓸 날짜(매주 월요일 발행, 지난주 회고)
```

예:
- 월요일 실행이면 그날 daily(`post_date=월요일`)를 만들고, 추가로 지난주 회고 weekly를 만든다.
- 월요일 weekly는 지난주(직전 월~금) 평일 daily가 모두 존재할 때만 `posts/YYYY-MM-DD-weekly.html`(파일명 날짜 = 발행 월요일)로 만든다.

### 2.1 Date Source Contract — hard gate

Daily를 만들기 전에 arXiv 원본이 어떤 날짜를 가리키는지 반드시 확인한다.

```bash
python - <<'PY'
import re, urllib.request
for cat in ["cs.LG", "cs.CV", "cs.AI", "eess.IV", "eess.SP"]:
    html = urllib.request.urlopen(
        urllib.request.Request(f"https://arxiv.org/list/{cat}/new", headers={"User-Agent": "paper-daily-summary helper"}),
        timeout=60,
    ).read().decode("utf-8", "replace")
    h3 = re.findall(r"<h3[^>]*>(.*?)</h3>", html, re.S | re.I)[0]
    print(cat, re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h3)).strip())
PY
```

규칙:
- `post_date == /new listing_date`이면 `/new`를 사용한다.
- `post_date < /new listing_date`이면 `/new` 사용 금지. 반드시 `/pastweek`의 해당 날짜 h3 섹션만 추출하는 backfill parser를 사용한다.
- `/pastweek`에 해당 날짜 섹션이 없으면 발행하지 말고 사용자에게 “원본 listing을 repo에 저장하지 않아 복구 불가”라고 보고한다.
- `post_date > /new listing_date`이면 arXiv가 아직 올라오지 않은 것이므로 발행하지 않는다.
- 추적 카테고리들의 listing date가 서로 다르면, 가장 많은 카테고리가 가리키는 날짜를 `listing_date`로 삼는다. 절반 이상이 어긋나면 발행하지 않는다. (cs.* 와 eess.* 는 갱신 시점이 다를 수 있다.)

`trends/YYYY-MM-DD.json`에는 아래 필드를 반드시 남긴다.

```json
{
  "source_listing_date": "YYYY-MM-DD",
  "source_mode": "new|pastweek-date-section",
  "daily_new_counts": {
    "by_cat": {"cs.LG": 0, "cs.CV": 0, "cs.AI": 0, "eess.IV": 0, "eess.SP": 0},
    "scope": "new+cross; replacements excluded"
  }
}
```

`source_listing_date != date`이면 release 실패다. 단, `source_mode=pastweek-date-section`이고 `source_listing_date == date`이면 backfill로 허용한다.

---

## [3. Calendar Audit — 모든 실행의 첫 단계]

repo를 pull한 직후 아래를 먼저 확인한다.

```bash
cd {WORKDIR}
git pull origin main
```

확인 대상:
- `posts/YYYY-MM-DD.html`
- `trends/YYYY-MM-DD.json`
- `benchmarks/YYYY-MM-DD.json`
- `insights/YYYY-MM-DD.json`
- `weekly/YYYY-WW.json`

절차:
1. 최근 발행된 daily 날짜를 찾는다.
2. `execution_date` 기준으로 평일 daily 중 빠진 날짜가 있는지 확인한다.
3. 빠진 평일 daily가 있으면 오래된 날짜부터 **Backfill mode**로 먼저 채운다.
4. 월요일이면 지난주 평일 daily(특히 금요일)가 모두 존재하는지 반드시 확인한다.
5. 빠진 지난주 daily가 있으면 먼저 Backfill로 채운 뒤 weekly를 생성한다.
6. 토·일요일은 기본 skip(arXiv 미발행)이지만, 누락 daily가 있거나 사용자가 명시적으로 요청하면 Backfill mode를 수행한다.

---

## [4. Mode Resolver]

아래 순서로 모드를 결정한다.

### 4.1 Backfill mode
조건:
- `posts/<missing-weekday>.html` 또는 해당 날짜의 `trends/benchmarks/insights`가 없음.
- 사용자가 "빠진 날짜 채워", "금요일 했는지 확인", "누락분 복구"라고 지시.
- `/new`의 `listing_date`가 발행하려는 `post_date`보다 뒤로 넘어갔음.

동작:
- 빠진 날짜를 오래된 순서대로 backfill source로 생성한다.
- `/new`를 다시 쓰지 않는다. 반드시 `/pastweek`에서 해당 날짜 섹션만 추출한다.
- 각 날짜마다 `posts`, `trends`, `benchmarks`, `insights`, `feed.xml`까지 갱신한다.
- 여러 날짜를 복구한 뒤 마지막에 한 번 commit/push 가능.

Backfill parser 예:

```bash
for cat in cs.LG cs.CV cs.AI eess.IV eess.SP; do
  python scripts/fetch_arxiv_pastweek_date.py "$cat" YYYY-MM-DD > "out/${cat}_new.json"
done
```

주의:
- `/pastweek` backfill에는 abstract가 없을 수 있다. 이 경우 “title/subject 기반 backfill”임을 meta와 trends에 기록한다.
- `/pastweek` 날짜 섹션의 표시 편수와 `out/*_new.json` 편수가 맞지 않으면 release 실패다.

### 4.2 Daily mode
조건:
- 평일 실행(월~금). 월요일도 daily를 생성하며, 그 직후 Weekly mode를 추가로 수행한다.

동작:
- `post_date` 기준으로 `posts/YYYY-MM-DD.html` 생성.
- `trends/YYYY-MM-DD.json`, `benchmarks/YYYY-MM-DD.json`, `insights/YYYY-MM-DD.json` 생성.

### 4.3 Weekly mode
조건:
- **매주 월요일** (그날 Daily mode를 먼저 수행한 뒤 추가로 실행).
- 지난주(직전 월~금) 평일 daily 산출물이 모두 존재(없으면 Calendar Audit이 먼저 Backfill).

동작:
- 지난주를 회고하는 `posts/YYYY-MM-DD-weekly.html` 생성(파일명 날짜 = 발행 월요일).
- `weekly/YYYY-WW.json` 생성(회고 대상 = 지난주 ISO week).
- `trends/YYYY-MM-DD.json` 갱신.
- 월요일 daily의 `insights/YYYY-MM-DD.json`은 Daily 단계에서 이미 생성하므로 weekly에서 중복 생성하지 않는다.

### 4.4 Weekend mode (토·일)
조건:
- 토요일 또는 일요일이고 누락 daily가 없음.

동작:
- arXiv 미발행이므로 아무 산출물도 만들지 않고 종료한다. (weekly는 월요일에 발행)

---

## [5. Parser 실행 — WebFetch 금지]

입력 소스:
- 추적 카테고리: `cs.LG`, `cs.CV`, `cs.AI`, `eess.IV`, `eess.SP`
- 오늘 발표: `https://arxiv.org/list/<cat>/new` (카테고리별)
- 최근 일주일: `https://arxiv.org/list/<cat>/pastweek?skip=0&show=2000` (카테고리별)
- 저널(선택): Crossref REST API — `scripts/fetch_crossref.py` (arXiv와 동일 스키마)

실행:

```bash
cd {WORKDIR}
mkdir -p out

# arXiv /new — 추적 5개 카테고리 (출력 파일명은 out/<cat>_new.json 고정)
for cat in cs.LG cs.CV cs.AI eess.IV eess.SP; do
  python scripts/fetch_arxiv.py new "$cat" > "out/${cat}_new.json"
done

# arXiv /pastweek — backfill용
for cat in cs.LG cs.CV cs.AI eess.IV eess.SP; do
  python scripts/fetch_arxiv.py pastweek "$cat" > "out/${cat}_pastweek.json"
done

# 저널(선택) — 랩 키워드로 Crossref 수집 (없으면 건너뜀)
python scripts/fetch_crossref.py \
  --query "Fourier ptychography" \
  --query "lensless imaging" \
  --query "computational microscopy" \
  --query "quantitative phase imaging" \
  --query "computer-generated holography" \
  --query "metasurface optics" \
  --query "light field microscopy" \
  --query "optical diffraction tomography" \
  --query "virtual staining" \
  --days 1 > out/journal_new.json   # daily는 1일(전날 등록분); 주간/backfill은 더 넓게

python scripts/classify.py > out/classified.json
```

### Windows PowerShell 주의

PowerShell 5의 `Set-Content -Encoding UTF8`은 BOM을 붙일 수 있어 `json.load(..., encoding="utf-8")`에서 깨진다.
리다이렉트는 반드시 `cmd /c "... > out\<cat>_new.json"` 형태로 실행하고, `| Set-Content -Encoding UTF8`은 금지한다.

---

## [6. Parser 검증 체크리스트]

실행 직후 반드시 확인한다.

1. 각 추적 카테고리의 `out/<cat>_new.json`이 JSON으로 로드되는가.
2. `/new` 총 편수가 카테고리 합산 50편 미만이면 parser 오류 의심.
3. `out/classified.json`의 `selected / total` 비율이 40% 이상인가.
4. arxiv id의 `YYMM` prefix가 `listing_date`의 연월과 맞는가.
5. backfill이면 `listing_date`와 `post_date`가 복구 대상 평일과 일치하는지 확인한다.
6. `source_listing_date == post_date`인가.
7. `daily_new_counts`는 replacement를 제외한 `new+cross` 편수인가.
8. 같은 입력 데이터가 직전 daily와 완전히 같지 않은가. `daily_new_counts`, `total_scanned`, `selected`, must-read 대표 arxiv id가 모두 같으면 release 실패다.

검증 실패 시:
- WebFetch로 대체하지 않는다.
- parser 또는 encoding 문제를 고친다.
- 잘못된 배치로 HTML을 발행하지 않는다.

---

## [7. 랩 ROI 버킷]

버킷 정의는 `scripts/classify.py`의 `BUCKETS`와 일치해야 한다. 계산광학 분야 9개(광학 주제 1–7 + ML 방법론 8–9):

1. **Fourier Ptychography/Microscopy** — Fourier ptychography, computational microscopy, aperture synthesis, coded illumination
2. **Lensless/Coded Imaging** — lensless, coded aperture, PSF engineering, diffuser, single-shot/snapshot, computational camera
3. **Phase Imaging/Holography** — quantitative phase, phase retrieval, phase microscopy, (digital/computer-generated) holography, wavefront, interferometry, angular spectrum
4. **Meta-Optics/Diffractive** — metasurface, metalens, meta-optics, diffractive optics, nanophotonics, inverse lithography, optical inverse design
5. **Light-Field/Novel Sensors** — light field, plenoptic, event camera, neuromorphic, integral imaging, light-field display
6. **Tomography/3D Imaging** — (optical diffraction) tomography, volumetric imaging, 3D reconstruction, Gaussian splatting, NeRF, light-field microscopy
7. **Virtual Staining/Pathology** — virtual staining, digital pathology, histopathology, label-free, H&E, whole slide, tissue imaging
8. **Reconstruction/Inverse Problems** — image reconstruction, inverse problem, deep unfolding/unrolling, plug-and-play, compressed sensing, deconvolution, physics-informed
9. **Deep Learning Methods** — diffusion/generative, neural network, self-supervised, foundation model, transformer, implicit neural representation, super-resolution, denoising

---

## [8. 톤과 문체]

전체 리포트를 "똘똘한 박사과정 4년차가 매일 아침 지도교수 방에 와서 커피 한 잔 놓고 구두로 브리핑하는" 구어체로 작성한다.

- 기본 어미: "~입니다 / ~네요 / ~더라구요 / ~인 것 같습니다 / ~어요" 혼용.
- 연결어: "근데", "재밌는 건", "제일 눈에 띄는 건", "한편", "주목할 만한 건".
- 판단을 숨기지 않는다.
- 한 문단은 "관찰 → 의미 부여 → 전망/판단" 순서.
- 메타정보는 스캔 가능한 구조, 본문은 구어체.
- 영어 약어(VLA, MoE, 3DGS 등)는 첫 등장 시 한 번 풀어 설명한다.

---

## [8.5. 리포트 품질 업그레이드 — 판단의 위계]

좋은 리포트의 목적은 "많이 요약"이 아니라 "무엇이 중요한지 판단의 위계를 보여주는 것"이다.
따라서 daily/weekly 모두 아래 품질 규칙을 따른다.

### 8.5.1 오늘의 thesis

리포트 상단에 1~2문장짜리 thesis를 둔다.

```text
오늘의 결론:
이번 배치는 video generation이 "생성 품질"에서 "camera/motion controllability"로 넘어가는 날이고,
VLA는 모델 크기보다 내부 구조를 노출하는 쪽으로 이동했다.
```

thesis는 단순 요약이 아니라 editorial judgment여야 한다.
- "오늘 뭐가 제일 중요했나"
- "어제/지난주와 뭐가 달라졌나"
- "우리 랩이 어디를 봐야 하나"

를 한 번에 잡아준다.

### 8.5.2 버킷보다 클러스터 우선

8개 ROI 버킷은 저장/분류용이다. 해석은 "오늘의 클러스터"를 먼저 제시한다.

예:
1. Controllable video generation
2. VLA structure exposure
3. Reliability-aware deployment
4. Medical/clinical VLM failure modes
5. 3D/robotics calibration under shift

각 클러스터는 최소 2편 이상의 논문으로 evidence를 둔다. 단발 논문이면 cluster가 아니라 "관찰 중"으로 표시한다.

### 8.5.3 대표 클러스터 표 — daily/weekly 모두 필수

Daily와 weekly에는 반드시 클러스터 지도 표를 넣는다. 카드형 인사이트나 버킷 현황으로 대체하지 않는다.

- Daily: thesis 바로 뒤, `🔭 주간 동향`보다 앞에 `🧩 오늘의 클러스터 지도` h2로 배치한다.
- Weekly: thesis 또는 `🔭 주간 동향` 직후에 `🧩 주간 클러스터 표` h2로 배치한다.
- 표가 빠진 HTML은 미완성 산출물로 간주한다. 논문 수가 적어도 최소 3개 클러스터를 만들고, 정말 근거가 부족한 행은 Confidence를 Low로 둔다.
- 각 행은 “읽을 클러스터 / 대표 논문 / 왜 중요한가 / 얼마나 확실한가 / 우리 랩이 무엇을 해볼까”를 30초 안에 보여주는 역할을 한다.
- `왜 중요?` 칸은 영어식 라벨이나 압축 구문으로 끝내지 않는다. “그게 실제로 무슨 뜻인지”와 “기존 방식과 무엇이 달라지는지”를 2~3문장 한국어로 풀어쓴다.
- `Lab action` 칸은 “follow-up”, “audit”, “metric 설계” 같은 추상어만 쓰지 말고, 어떤 benchmark·dataset·ablation·stress test를 할지 구체적으로 적는다.

표 스키마는 daily/weekly 모두 동일하다.

```text
| Cluster | 대표 논문 | 왜 중요? | Confidence | Lab action |
|---|---|---|---|---|
| VLA structure exposure | TriRelVLA, VLA-GSE, When to Trust Imagination | VLA를 큰 policy 하나로 보면 왜 성공하고 실패하는지 설명하기 어렵다. 이 클러스터는 relation, expert, verifier처럼 내부 역할을 나눠 보자는 흐름이라, 모델 크기보다 어떤 구조가 일반화에 기여하는지 비교할 수 있게 해준다. | High | LIBERO/RoboCasa에서 relation/expert/verifier를 같은 task family로 ablation |
| Controllable video generation | ActCam, RealCam, FreeSpec | 예전에는 생성 영상이 얼마나 그럴듯한지 봤다면, 이제는 원하는 카메라 경로와 대상 움직임을 얼마나 안정적으로 조종하는지가 중요해졌다. 즉 video generation이 감상용 샘플러에서 제작 도구로 넘어가는 신호다. | High | 카메라 경로 오차, 대상 정체성 유지, 지연시간을 분리한 controllability metric 설계 |
```

표는 독자가 30초 안에 "읽을 것 / 실험할 것 / 보류할 것"을 나누게 해주는 장치다. 따라서 모든 daily/weekly HTML 생성 직후 `Cluster</th>`, `대표 논문`, `왜 중요?`, `Confidence`, `Lab action` 문자열이 실제 HTML에 존재하는지 검증한다.

### 8.5.3.b Editorial Uniqueness Gate — cluster 복붙 금지

Daily cluster는 그날 논문 집합을 다시 읽고 새로 판단해야 한다. 같은 repo 안의 직전 daily에서 제목을 가져와 채우면 안 된다.

저장 전 아래를 확인한다.

1. 직전 daily의 `insights/YYYY-MM-DD.json`과 오늘 `clusters[].cluster`를 비교한다.
2. cluster 제목이 4개 이상 완전히 같으면 release 실패다.
3. 제목이 3개 이하로 같더라도, 같은 제목의 대표 논문 arxiv id가 50% 이상 다르면 제목을 더 구체적으로 바꾼다.
4. `왜 중요?` 문장에 “오늘/이번 묶음/5월 N일”의 구체적 evidence가 없어도 실패다.
5. `대표 논문` 칸은 cluster 설명에 언급한 논문과 실제 링크가 일치해야 한다.
6. `추천 연구주제`는 cluster 제목을 그대로 반복하지 말고, 그날 대표 논문에서 바로 이어지는 실험 단위로 쓴다.

예:
- 5/11에 `Sword`, `ST-Gen4D`, `GEM`이 대표면 cluster는 `World model을 simulator로 쓰려는 흐름이 4D와 LiDAR까지 확장`처럼 쓴다.
- 5/12에 `CoWorld-VLA`, `CapVector`, `ALAM`이 대표면 cluster는 `VLA 실행 스택이 async, capability vector, latent transition으로 쪼개짐`처럼 쓴다.
- 둘 다 “VLA가 내부 역할을 나누는 쪽으로 이동”이라고 쓰면 실패다.

### 8.5.3.a 클러스터 표의 "느낌" — 이 표가 리포트의 두뇌다

이 표는 장식용 요약 표가 아니다. 리포트 전체에서 가장 중요한 editorial artifact다. 독자가 긴 논문별 요약을 읽기 전에, 이 표만 보고도 "오늘/이번주 연구판이 어디로 움직였는지"를 감 잡아야 한다.

원하는 느낌은 아래와 같다.

1. **Cluster 칸**은 버킷명이 아니라 해석된 흐름명이다.
   - 나쁜 예: `Generation`, `Robot Learning`, `Safety`
   - 좋은 예: `Controllable video generation`, `VLA structure exposure`, `Reliability-aware deployment`, `Navigation as map-level decision`, `3D/robotics calibration under shift`

2. **대표 논문 칸**은 한 흐름을 구성하는 evidence set이다.
   - 2~4편을 넣는다.
   - insight JSON에 3개 클러스터만 있어도 거기서 멈추지 않는다.
   - `classified.json`, daily paper snapshot, bucket별 paper list를 다시 훑어 2편 이상 묶이는 보조 클러스터를 찾아 표를 5행 안팎으로 채운다.
   - 단, 제목 키워드가 우연히 겹치는 논문은 제외한다. 예를 들어 `navigation`이라는 단어가 있어도 MRI slice navigation처럼 로봇/VLN/ObjectNav 맥락이 아니면 `Navigation as map-level decision`에 넣지 않는다.

3. **왜 중요? 칸**은 "전문가의 압축 메모"가 아니라 "독자가 되물을 필요 없는 해석"이어야 한다.
   - 나쁜 예: `VLA를 relation, expert, latent action, WAM verifier로 내부 구조를 노출.`
   - 좋은 예: `VLA를 하나의 거대한 policy로만 보면 왜 성공하고 왜 실패하는지 설명하기가 어렵습니다. 이번 흐름은 object-hand-task 관계, expert routing, latent action, verifier처럼 내부 역할을 나눠서 보는 쪽입니다. 즉 모델 크기를 더 키우기 전에 어떤 구조가 어떤 작업에서 실제로 도움이 되는지 비교할 수 있는 발판이 생긴다는 뜻입니다.`
   - 나쁜 예: `VLN/ObjectNav가 step-by-step policy보다 top-down/global/ambiguous-query planning으로 이동.`
   - 좋은 예: `VLN/ObjectNav가 지시문을 한 단계씩 따라가는 문제에서, 전체 지도와 애매한 목표를 함께 판단하는 문제로 이동하고 있습니다. 즉 로봇이 바로 움직이기보다, 현재 목표가 무엇인지와 어느 후보가 더 맞는지를 먼저 비교해야 한다는 뜻입니다.`

4. **Confidence 칸**은 감이 아니라 근거 수준이다.
   - `High`: 서로 다른 논문 3편 이상, 서로 다른 저자군/기관, 같은 평가축 또는 같은 실패 조건이 반복됨.
   - `Medium`: 2~3편이 같은 방향을 보이지만 benchmark 확산이나 독립 검증은 아직 부족함.
   - `Low`: 신호는 있으나 단발이거나 제목/abstract 기반 연결이 강하지 않음.
   - Confidence 아래에는 반드시 한 줄 근거를 붙인다. 예: `대표 논문 4편 이상 연결`, `navigation 관련 논문 2편 이상 연결, benchmark 확산은 추가 확인 필요`.

5. **Lab action 칸**은 회의에서 바로 일감으로 바꿀 수 있어야 한다.
   - 나쁜 예: `추가 확인`, `follow-up`, `metric 설계`
   - 좋은 예: `LIBERO/RoboCasa에서 relation, expert, latent action, verifier를 같은 표로 ablation`
   - 좋은 예: `R2R/ObjectNav에 ambiguous-query와 top-down map planning stress test를 묶어 평가`
   - 좋은 예: `카메라 경로 오차, 대상 정체성 유지, 지연시간을 분리한 controllability metric grid 설계`

6. **행 수 원칙**
   - daily는 기본 5행을 목표로 한다.
   - 정말 5행을 만들 근거가 없으면 3~4행도 가능하지만, 그때는 meta나 표 아래에 "보조 클러스터 근거 부족으로 N행만 표시"라고 적는다.
   - `insights`가 3개라고 표도 3행으로 끝내면 안 된다. 인사이트는 시작점이고, 표는 전체 paper snapshot을 다시 훑어 만드는 판세 지도다.

이 표를 잘 만들면 이후 `주간 동향`, `인사이트`, `추천 연구주제`, `must-read`는 이 표를 풀어쓴 것이다. 반대로 이 표가 약하면 리포트 전체가 약해진 것으로 본다.

### 8.5.3.c 도메인 Watch Lens — 묻히기 쉬운 핵심 신호

편수가 적어도 랩 ROI상 중요한 버킷(특히 `Lensless/Coded Imaging`, `Virtual Staining/Pathology`, `Light-Field/Novel Sensors`, `Meta-Optics/Diffractive`)은 클러스터 표를 만들기 전에 한 번 더 훑어 묻히지 않게 한다.

- 계산광학 코어: Fourier ptychography, lensless/coded aperture, quantitative phase, (computer-generated) holography, optical diffraction tomography
- 광학 하드웨어: metasurface/metalens/meta-optics, diffractive optics, light-field/plenoptic, event camera
- 응용·방법: virtual staining/digital pathology, deep unfolding/plug-and-play, implicit neural representation, Gaussian splatting

규칙: 해당 신호가 2편 이상이면 독립 클러스터 후보로 검토하고, 상단에 올리지 않았다면 표 아래 1문장으로 이유를 적는다. `Lab action`은 추적이 아니라 바로 실행 가능한 형태로 쓴다.

### 8.5.4 중요도 태그

대표 논문과 클러스터에는 아래 태그 중 하나 이상을 붙인다.
단, 화면에서 한 논문/클러스터에 붙이는 태그는 핵심 2~3개로 제한한다. 태그를 많이 붙이는 것보다 "왜 봐야 하는지"가 바로 보이는 조합을 우선한다.

```text
[문제정의] 새 문제나 연구 질문 자체를 세운 논문
[평가축] metric, benchmark protocol, failure condition처럼 성능을 재는 기준을 바꾼 논문
[방법전환] 기존 병목을 다른 formulation으로 푼 논문
[인프라] dataset/tool/framework/benchmark를 만든 논문
[경고신호] negative result, failure mode, safety/deployment risk를 드러낸 논문
[통합정리] survey/review/taxonomy/map처럼 흩어진 흐름을 한 장의 지도로 묶는 논문
[스케일업] 모델·데이터·embodiment·실험 규모를 키워 새 현상이나 한계를 보려는 논문
[실사용전환] latency, real-time, on-device, hardware, closed-loop, field deployment를 겨냥한 논문
[데이터전환] 병목을 모델 구조보다 데이터 수집·정제·합성·라벨링 방식에서 찾는 논문
[해부분석] 모델 내부 표현, mechanism, ablation, probing으로 왜 되는지/왜 실패하는지 뜯어보는 논문
[표준후보] 후속 논문들이 계속 쓸 만한 task, metric, protocol, dataset, benchmark를 제안하는 논문
[위험보류] 아이디어는 흥미롭지만 baseline, split, ablation, 데이터 공개성 때문에 claim 확인이 필요한 논문
```

예:
- CXR-ContraBench → `[경고신호]`
- VideoRouter → `[방법전환] [인프라]`
- From Pixels to Tokens → `[방법전환]`
- GA3T → `[인프라]`
- iWorld-Bench → `[평가축] [인프라]`
- VLA Safety Survey → `[통합정리] [경고신호]`
- LWD fleet-scale RL → `[스케일업] [실사용전환]`
- How VLAs Work → `[해부분석] [방법전환]`
- 새 데이터 엔진/teleoperation 논문 → `[데이터전환] [인프라]`

### 8.5.4.a 계통도(Phylogeny) 태그 — 사용 안 함

이 랩에서는 Phylogeny tag 기능을 사용하지 않는다. 이후 출력 규격에 `Phylogeny tag` 또는 `계통도 태그` 요구가 남아 있으면 무시한다.

### 8.5.5 Confidence와 evidence strength

인사이트마다 confidence를 붙인다.

```text
Confidence: High
근거: 같은 주제 논문 5편 이상 + 서로 다른 기관 + benchmark/dataset 동반

Confidence: Medium
근거: 오늘 2~4편 동시 등장했지만 아직 abstract 기반

Confidence: Low
근거: 흥미로운 단발 논문, 후속 관찰 필요
```

강한 주장과 약한 추측을 같은 문체로 쓰지 않는다.

### 8.5.6 어제/지난주와 달라진 점

Daily에는 가능하면 "어제/지난주와 달라진 점"을 짧게 넣는다.

```text
🧭 어제와 달라진 점
- 어제는 VLA의 latent 표현을 어떻게 만들지가 중심이었고, 오늘은 그 모델을 실제 실행·신뢰성 문제로 어떻게 연결할지가 중심.
- 지난주에는 4D world model 평가가 중심이었고, 오늘은 controllable video generation으로 확장.
```

이 섹션은 매일 보는 독자에게 시간축을 제공한다.

### 8.5.7 Lab action은 1주 실행 protocol까지

추천 연구주제는 아이디어 수준에서 끝내지 않는다. 각 주제마다 가능한 경우 아래를 붙인다.

```text
실행 1주차:
- 대상 논문/코드 3편 clone
- 공통 benchmark: LIBERO + RoboCasa
- 비교축: success rate / latency / failure taxonomy
- 실패해도 남는 결과: negative result 또는 workshop short
```

좋은 연구주제는 "월요일에 학생이 바로 시작할 수 있는 형태"여야 한다.

### 8.5.8 리스크 taxonomy

리스크·한계 필터는 느낌으로 쓰지 말고 유형을 붙인다.

```text
[Metric risk] 수치가 실제 능력을 대표하지 않음
[Dataset risk] 분포가 좁거나 cherry-pick 가능
[Baseline risk] 비교군이 약함
[Deployment risk] latency/cost/safety 누락
[Claim risk] abstract 표현이 본문 증거보다 강함
```

### 8.5.9 Skim-only 후보

좋은 브리핑은 무엇을 읽을지도 말하지만, 무엇을 굳이 깊게 읽지 않아도 되는지도 알려준다.

```text
🧊 Skim-only 후보
- ROI에는 걸리지만 incremental한 논문
- 응용 도메인만 바뀐 논문
- benchmark/claim 확인 전까지 보류할 논문
```

표현은 공격적으로 하지 않는다. "읽지 말라"가 아니라 "깊게 읽기 전 우선순위를 낮춘다"는 의미다.

---

## [9. 논문 요약 품질 계층]

하루에 100편 이상 잡히는 날이 많으므로 모든 논문을 같은 깊이로 쓰지 않는다.

### Tier A — 판을 바꾸는 논문 3~5편
깊게 쓴다.
- 핵심 주장
- 방법의 핵심 수식/아키텍처 또는 직관
- 핵심 실험/벤치마크
- 약점·한계
- 우리 랩 파이프라인 영향
- 중요도 태그 `[문제정의] [평가축] [방법전환] [인프라] [경고신호] [통합정리] [스케일업] [실사용전환] [데이터전환] [해부분석] [표준후보] [위험보류]`
- 계통도 태그 `Phylogeny: ROBOTICS/CVML / Phylum > Class > Order > Genus`
- Confidence와 evidence strength

### Tier B — 인사이트 대표 논문 8~12편
3문장 이내로 쓴다.
- 문제
- 기존 방식과 차이
- 왜 오늘/이번주 흐름에서 중요한지
- 어떤 클러스터의 evidence인지
- 어느 계통도 lineage에 속하는지

### Tier C — 나머지 ROI 논문
abstract 기반 짧은 요약.
- 초록에 없는 수치나 코드 공개 여부를 지어내지 않는다.
- 불확실하면 "abstract 기준", "본문 확인 필요"라고 명시한다.
- peripheral하면 Skim-only 후보로 표시 가능

### 압축 부록 — 전체 ROI 논문 목록

전체 ROI 논문 목록은 영어 abstract를 그대로 줄이거나 번역투로 붙이지 않는다.
각 논문을 한국어로 재해석해 3~5개 bullet로 작성한다.

각 bullet은 가능한 한 한 줄을 넘기지 않는다.
목표는 "이 논문을 깊게 읽을지 말지 10초 안에 판단"하게 하는 것이다.

필수 bullet:

```text
- 문제: 이 논문이 겨냥한 병목/공백
- 방법: 기존 방식과 다른 핵심 아이디어
- 의미: 왜 이 버킷/클러스터에서 볼 가치가 있는지
```

선택 bullet:

```text
- 근거: abstract에 나온 벤치마크/데이터셋/수치
- 주의: 본문 확인 전 보류할 claim, metric/dataset/baseline/deployment risk
- 우선순위: Must-read / Read / Skim-only
- 계통도: ROBOTICS/CVML / Phylum > Class > Order > Genus
```

금지:
- 영어 abstract 첫 문장을 그대로 복사하거나 직역하지 않는다.
- "성능을 향상했다", "효율적이다" 같은 일반 문장만 쓰지 않는다.
- abstract에 없는 수치, 코드 공개 여부, SOTA claim을 만들지 않는다.
- 모든 논문에 같은 템플릿 문장을 반복하지 않는다.

예시:

```text
TriRelVLA: Triadic Relational Structure for Generalizable Embodied Manipulation [CV/RO] [방법전환] [Read] [Phylogeny: ROBOTICS / Learning for Robotics > Foundation Models > Vision-Language-Action > (general)]
- 문제: 기존 VLA가 unseen object/scene에서 appearance와 layout에 과적합됨.
- 방법: object-hand-task 관계를 중간 표현으로 분리해 action prediction에 넣음.
- 의미: VLA 일반화 논점을 모델 크기보다 구조 노출로 옮기는 결.
- 주의: relation extractor 품질과 clutter scene robustness는 본문 확인 필요.
```

---

## [10. Daily 산출물]

`posts/YYYY-MM-DD.html`에 아래 순서로 작성한다.

1. 상단 홈 버튼
2. 메타 정보
3. 오늘의 thesis — 1~2문장 editorial conclusion
4. 🎧 오디오 브리핑 — 있을 때만
5. 🔭 주간 동향
6. 🧭 어제/지난주와 달라진 점
7. 🧩 오늘의 클러스터 + 대표 클러스터 표
8. 📐 arXiv(방법) vs 저널(응용) 대비
9. 💡 오늘의 인사이트 — 각 항목에 Confidence 포함
10. 🔬 추천 연구주제 — 각 항목에 1주 실행 protocol 포함
11. 🧭 예측 회고 루프 — 월요일만
12. 📊 오늘의 버킷 현황
13. 📈 벤치마크 SOTA 추이 — 있으면
14. 🔀 크로스오버 페어 — 있으면
15. 🌟 오늘의 must-read — Tier A 3~5편 중 1~2편 deep dive
16. ⚠️ 리스크·한계 필터 — risk taxonomy 태그 포함
17. 🧊 Skim-only 후보 — 있으면
18. 📄 부록 — 전체 ROI 논문 압축 목록
19. 🔗 참고 링크 + 하단 홈 버튼

필수 파일:
- `posts/YYYY-MM-DD.html`
- `trends/YYYY-MM-DD.json`
- `benchmarks/YYYY-MM-DD.json`
- `insights/YYYY-MM-DD.json`
- `feed.xml`

---

## [11. Weekly 산출물]

Weekly는 daily를 단순히 합친 글이 아니다. 한 주 동안 반복해서 나타난 문제 설정, 뜨거워진 클러스터, 식은 클러스터, 예측이 맞았는지 여부, 다음 주에 실제로 볼 관찰 포인트를 정리하는 회고 문서다.

따라서 weekly는 아래 4가지 질문에 반드시 답해야 한다.

1. 이번 주에 판세가 실제로 바뀐 축은 무엇인가?
2. 지난 daily에서 중요하다고 본 흐름 중 무엇이 이어졌고, 무엇이 꺼졌는가?
3. 다음 주에 확인해야 할 논문 유형, benchmark, failure case는 무엇인가?
4. 우리 랩이 당장 해볼 수 있는 1주짜리 실험/읽기/비교표는 무엇인가?

`posts/YYYY-MM-DD-weekly.html`에 아래 순서로 작성한다.

1. 상단 홈 버튼
2. 🗓 Executive Summary — 한 주의 결론 3줄. 숫자 나열 금지, “그래서 이번 주는 무엇으로 기억할지”를 쓴다.
3. 주간 thesis — 이번주 판세를 1~2문장으로 선언. 반드시 “지난주/초반 daily에서 보던 흐름과 무엇이 달라졌는지”를 포함한다.
4. 🔭 주간 동향 — RSS 요약 추출을 위해 반드시 이 h2 포함. 3문단으로 작성한다.
   - 1문단: 뜨거운 클러스터와 그 의미.
   - 2문단: 식은 클러스터 또는 비어 있는 공백.
   - 3문단: 다음 주로 넘어갈 관찰 포인트.
5. ⚖️ Hot vs Cold — 주간 상승/하락 클러스터를 나란히 비교한다. 단순 편수보다 “왜 뜨거워졌고 왜 식었는지”를 설명한다.
6. 🧩 주간 클러스터 표 — 필수. Daily의 `오늘의 클러스터 지도`와 같은 5열 표를 사용한다: Cluster / 대표 논문(Papers) / 왜 중요?(Why) / Confidence / Lab action. 카드 목록이나 Top 5로 대체 금지.
7. 📐 arXiv vs 저널 키워드 — 공통 키워드, arXiv(방법) 전용, 저널(광학 응용) 전용, 같은 단어의 다른 맥락을 분리한다.
8. 🔥 주간 Top 5 — 각 항목에 중요도 태그, Phylogeny tag, “왜 Top 5인지” 2문장 설명을 붙인다. 제목+링크만 나열 금지.
9. 🌟 Weekly deep-dive 1편 — 주간 판세를 가장 잘 대표하는 1편만 고른다. daily must-read를 재탕하지 말고, “왜 주간 대표인지”를 기준으로 다시 고른다. Phylogeny tag 필수.
10. 🧭 주간 테마 3개 — 각 카드에 `.theme-card` 클래스 사용, confidence 포함. 각 테마는 “관찰 → 의미 → 다음 주 전망” 순서로 쓴다.
11. 🪞 지난 예측 채점 — 있으면 반드시 수행한다. 1주 전 weekly predictions 또는 2주 전 insights를 읽고 ✅/◐/✗/⏳ 라벨을 붙인다.
12. 🔮 다음주 예측 — 3개. 각 예측은 “무엇이 나오면 적중인지 / 무엇이 안 나오면 빗나감인지” 판정 기준을 포함한다.
13. 🧪 다음 주 1주 실행안 — 2~3개. 읽기 목록이 아니라 실제로 만들 표, 돌릴 benchmark, 비교할 ablation을 적는다.
14. 🧊 Skim-only / Watch-only 흐름 — 있으면. 아직 약하지만 추적할 가치가 있는 미니토픽을 표시한다.
15. 🎧 주간 오디오 — 있으면
16. 참고 링크 + 하단 홈 버튼

### Weekly 클러스터 표 품질 기준

주간 클러스터 표는 daily 표보다 더 “판세 지도”에 가까워야 한다.

- 최소 5개 행을 목표로 한다. 자료가 부족하면 3개까지 허용하되, 그 이유를 meta에 적는다.
- 각 Cluster는 같은 주 안에서 2편 이상 연결되어야 한다. 1편뿐이면 `Watch-only`로 내리고 표의 주 클러스터에는 넣지 않는다.
- `대표 논문` 칸에는 2~4편을 넣고, 논문 제목은 짧게 줄이되 링크와 Phylogeny tag는 유지한다.
- `왜 중요?` 칸은 “A가 나왔고 B도 나왔다”가 아니라 “이 둘이 같이 나오면 평가 기준이나 연구 질문이 어떻게 달라지는지”를 설명한다.
- `Confidence`는 High/Medium/Low 중 하나로 쓰고, 바로 아래에 근거를 한 줄로 붙인다. 예: “High — 서로 다른 저자군 4편 + benchmark가 겹침”.
- `Lab action`은 다음 주에 바로 할 행동이어야 한다. 예: “LIBERO에서 relation/expert/verifier ablation 표 만들기”, “camera path error·identity preservation·latency 3축으로 ActCam/RealCam 비교”.
- Weekly 표 생성 후 `Cluster</th>`, `대표 논문`, `왜 중요?`, `Confidence`, `Lab action`, `Phylogeny:`가 HTML에 있는지 검증한다.

### Weekly에서 금지되는 약한 패턴

- daily 요약 5개를 이어붙이고 “이번 주도 비슷했다”로 끝내기.
- Top 5 제목만 나열하고 왜 Top 5인지 설명하지 않기.
- 예측을 했는데 다음 weekly에서 채점하지 않기.
- `VLA community가 catalog 단계에 진입`처럼 라벨만 말하고, 실제로 무슨 변화인지 풀지 않기.
- `Hot vs Cold`를 단순 편수 순위로만 쓰기. 반드시 의미를 설명한다.
- `Lab action`을 “follow-up 필요”, “더 봐야 함”처럼 비어 있는 말로 끝내기.

필수 파일:
- `posts/YYYY-MM-DD-weekly.html`
- `weekly/YYYY-WW.json`
- `trends/YYYY-MM-DD.json`
- `feed.xml`

weekly에서는 `insights/YYYY-MM-DD.json`을 만들지 않는다.

---

## [12. 벤치마크와 인사이트 JSON]

`trends/YYYY-MM-DD.json`에는 홈페이지 통계용 일간 `/new` 원천 수를 구조화해 둔다.
이 값은 `out/cv_new.json`, `out/ro_new.json`에서 `section == "new"` 또는 `section == "cross"`인 항목만 세며,
`section == "replace"`는 절대 포함하지 않는다. 즉 업데이트/replacement가 아니라 당일 신규 공지량만 본다.

```json
{
  "date": "YYYY-MM-DD",
  "daily_new_counts": {
    "cv": 229,
    "ro": 68,
    "scope": "new+cross",
    "exclude": "replace"
  }
}
```

과거처럼 note 문자열에만 카테고리별 건수를 남기지 말고, 위 구조화 필드(`by_cat`)를 함께 저장한다.
홈페이지의 날짜별 막대 차트와 archive 날짜 옆 CV/RO 배지는 `scripts/build_weekday_counts.py`가 repo에 저장된 이 필드와 과거 note를 읽어 생성한다. 차트 x축은 요일 그룹이 아니라 저장된 daily 날짜 순서여야 하며, 새 daily를 추가하거나 backfill할 때마다 `stats/weekday_counts.json`의 `daily`에 해당 날짜 row가 append/정렬되어야 한다. 홈 archive의 각 daily 날짜 옆에는 가능한 경우 `CV N편`, `RO M편` 배지를 표시한다.

`benchmarks/YYYY-MM-DD.json`:

```json
{
  "date": "YYYY-MM-DD",
  "results": [
    {
      "benchmark": "ObjectNav",
      "metric": "SR",
      "value": 71.2,
      "value_str": "71.2 SR",
      "paper": "https://arxiv.org/abs/....",
      "paper_title": "..."
    }
  ]
}
```

신규 결과가 없으면 빈 배열을 쓴다.

`insights/YYYY-MM-DD.json`:

```json
{
  "date": "YYYY-MM-DD",
  "insights": [
    {
      "title": "...",
      "claim": "...",
      "papers": [
        {
          "title": "...",
          "arxiv": "https://arxiv.org/abs/...",
          "importance_tags": ["[방법전환]"],
          "phylogeny": {
            "source": "ROBOTICS|CVML",
            "phylum": "...",
            "class": "...",
            "order": "...",
            "genus": "...",
            "confidence": "High|Medium|Low",
            "rationale": "..."
          }
        }
      ]
    }
  ],
  "research_topics": [
    {"title": "...", "claim": "...", "supporting_papers": [{"title": "...", "arxiv": "...", "phylogeny": {"source": "ROBOTICS|CVML", "phylum": "..."}}]}
  ],
  "phylogeny_tags": [
    {"paper": "https://arxiv.org/abs/...", "source": "ROBOTICS|CVML", "lineage": "Phylum > Class > Order > Genus"}
  ]
}
```

`weekly/YYYY-WW.json`:

```json
{
  "date": "YYYY-MM-DD",
  "iso_week": "YYYY-WW",
  "week_start": "YYYY-MM-DD",
  "week_end": "YYYY-MM-DD",
  "weekly_thesis": "...",
  "hot_vs_cold": {
    "hot": [{"cluster": "...", "why": "...", "papers": ["https://arxiv.org/abs/..."]}],
    "cold": [{"cluster": "...", "why": "..."}]
  },
  "clusters": [
    {
      "cluster": "...",
      "papers": [
        {
          "title": "...",
          "arxiv": "https://arxiv.org/abs/...",
          "importance_tags": ["[평가축]"],
          "phylogeny": {
            "source": "ROBOTICS|CVML",
            "phylum": "...",
            "class": "...",
            "order": "...",
            "genus": "...",
            "confidence": "High|Medium|Low",
            "rationale": "..."
          }
        }
      ],
      "why": "...",
      "confidence": "High",
      "lab_action": "..."
    }
  ],
  "predictions": [
    {"title": "...", "claim": "...", "rationale": "...", "hit_condition": "...", "miss_condition": "..."}
  ],
  "prediction_review": [
    {"title": "...", "label": "✅|◐|✗|⏳", "reason": "..."}
  ],
  "themes": [
    {"title": "...", "summary": "...", "confidence": "High"}
  ],
  "top5": [
    {
      "title": "...",
      "arxiv": "https://arxiv.org/abs/...",
      "why": "...",
      "tag": "[문제정의]",
      "phylogeny": {
        "source": "ROBOTICS|CVML",
        "phylum": "...",
        "class": "...",
        "order": "...",
        "genus": "...",
        "confidence": "High|Medium|Low",
        "rationale": "..."
      }
    }
  ],
  "phylogeny_tags": [
    {"paper": "https://arxiv.org/abs/...", "source": "ROBOTICS|CVML", "lineage": "Phylum > Class > Order > Genus"}
  ],
  "next_week_actions": [
    {"title": "...", "action": "...", "expected_output": "..."}
  ]
}
```

---

## [13. RSS와 index 호환]

`scripts/build_feed.py`는 `posts/*.html`에서 다음을 기대한다.
- daily/weekly 모두 `<h1>`이 있어야 한다.
- summary는 `🔭 주간 동향` h2 직후 첫 `<p>`에서 추출된다.

`index.html`은:
- daily 인사이트: `.insight h3`
- weekly 테마: `.theme-card h3`

따라서 weekly HTML에도 반드시:
- `🔭 주간 동향` h2
- `.theme-card h3`

를 포함한다.

---

## [14. TTS 오디오]

가능하면 생성한다.
- Daily: `audio/YYYY-MM-DD.mp3`
- Weekly: `audio/YYYY-MM-DD.mp3`

TTS 실패 시:
- HTML에서 오디오 섹션을 생략하거나 "TTS 환경 미연결" note로 처리한다.
- TTS 실패 때문에 전체 발행을 실패 처리하지 않는다.

---

## [15. Release Gate]

commit/push 전 반드시 확인한다.

```text
Daily:
- posts/YYYY-MM-DD.html 존재
- trends/YYYY-MM-DD.json 존재
- benchmarks/YYYY-MM-DD.json 존재
- insights/YYYY-MM-DD.json 존재
- `trends.date == YYYY-MM-DD`
- `trends.source_listing_date == YYYY-MM-DD`
- `trends.source_mode`가 `new` 또는 `pastweek-date-section`
- `daily_new_counts.scope == "new+cross; replacements excluded"`
- feed.xml에 posts/YYYY-MM-DD.html 링크 포함
- `scripts/validate_daily_release.py --date YYYY-MM-DD` 통과
- `3D/Scene`이 10편 이상이거나 geometry/SLAM/recon 관련 논문이 2편 이상이면, 클러스터 표에 geometry/SLAM/recon 행이 있거나 HTML에 상단 클러스터로 올리지 않은 이유가 명시됨

Weekly:
- posts/YYYY-MM-DD-weekly.html 존재
- weekly/YYYY-WW.json 존재
- trends/YYYY-MM-DD.json 존재
- feed.xml에 posts/YYYY-MM-DD-weekly.html 링크 포함

공통:
- JSON 파일이 모두 json.load로 읽힘
- HTML에 h1 존재
- weekly는 '🔭 주간 동향' h2와 .theme-card 존재
- scripts/build_feed.py --check 통과
- stats/weekday_counts.json 존재, `daily`가 repo에 저장된 `/new` 카운트만 포함
- stats/weekday_counts.json `daily`에 YYYY-MM-DD row가 존재하고 `daily_new_counts`와 CV/RO가 일치
- 홈페이지 날짜별 plot은 x축에 저장된 daily 날짜를 순서대로 표시하고 새 날짜가 빠지지 않음
- git diff --check 통과
- out/, __pycache__ 등 임시 파일은 commit하지 않음
```

날짜/source 오류가 이미 push된 경우:
1. 잘못된 날짜의 HTML/JSON/feed/stats를 즉시 수정한다.
2. 수정 commit을 push한다.
3. Slack에 정정 메시지를 보낸다. 정정 메시지는 “원인, 올바른 count, 수정된 링크”를 포함한다.
4. 잘못된 메시지를 침묵으로 덮지 않는다.

---

## [16. GitHub Pages 배포]

```bash
cd {WORKDIR}
python scripts/build_feed.py
python scripts/build_weekday_counts.py
python scripts/validate_daily_release.py --date YYYY-MM-DD
git add posts/YYYY-MM-DD.html \
        trends/YYYY-MM-DD.json \
        benchmarks/YYYY-MM-DD.json \
        insights/YYYY-MM-DD.json \
        feed.xml \
        stats/weekday_counts.json
git commit -m "Add YYYY-MM-DD briefing"
git push origin main
```

Weekly:

```bash
git add posts/YYYY-MM-DD-weekly.html \
        trends/YYYY-MM-DD.json \
        weekly/YYYY-WW.json \
        feed.xml
git commit -m "Add YYYY-MM-DD weekly retrospective"
git push origin main
```

Catch-up:

```bash
git add posts/... trends/... benchmarks/... insights/... weekly/... feed.xml
git commit -m "Add YYYY-MM-DD briefing and YYYY-WW retrospective"
git push origin main
```

push 실패 시 Slack 발송도 스킵한다.

---

## [17. Slack 발송]

push 성공 직후 발송한다. **daily report 발행 시(`out/release_ok.txt` 존재)** 요약을, **실행 실패 시** 실패 알림을 워크플로우가 **Slack 봇(`chat.postMessage`)**으로 `SLACK_CHANNEL_ID` 채널에 보낸다(주말·no-op은 미발송). 에이전트는 메시지 본문(mrkdwn)을 `out/slack_message.txt`로 작성한다.

```text
channel: {SLACK_CHANNEL}
channel_id: {SLACK_CHANNEL_ID}
```

`@channel`/`@here`는 사용자가 명시적으로 요구한 경우에만 쓴다.

### Daily Slack 템플릿

```text
📄 *Imaging Intelligence Daily Briefing — YYYY-MM-DD (요일)*
주간 시야: YYYY-MM-DD ~ YYYY-MM-DD · cs.LG/cs.CV/cs.AI/eess.IV/eess.SP new
🔗 <{SITE_URL}/posts/YYYY-MM-DD.html|전체 리포트 보기>

📊 *주간 한 줄 요약*
{주간 동향 핵심 3~4줄}

💡 *오늘의 인사이트*
1. {짧은 제목} ({대표 논문})
2. {짧은 제목}
3. {짧은 제목}

🔬 *추천 연구주제*
1. {짧은 제목}
2. {짧은 제목}
3. {짧은 제목}

📊 *버킷 현황*
`[FP] N · [Lens] N · [Phase] N · [Meta] N · [LF] N · [Tomo] N · [VS] N · [Recon] N · [DL] N`
🔥 TOP3: ...  ❄️ BOTTOM2: ...
```

### Weekly Slack 템플릿

```text
🗓 *Imaging Intelligence Weekly Retrospective — YYYY-MM-DD (Week WW)*
주간 시야: YYYY-MM-DD ~ YYYY-MM-DD · cs.LG/cs.CV/cs.AI/eess.IV/eess.SP pastweek
🔗 <{SITE_URL}/posts/YYYY-MM-DD-weekly.html|전체 회고 보기>

📌 *Executive Summary*
{3문장}

⚖️ *Hot vs Cold*
⬆ {가속 버킷/테마}  ⬇ {감속 버킷/테마}

🔥 *Top 5*
1. {제목}
2. {제목}
3. {제목}
4. {제목}
5. {제목}

🧭 *주간 테마 3*
· {테마 1} · {테마 2} · {테마 3}

🔮 *다음주 예측*
· {1} · {2} · {3}
```

### Catch-up Slack 템플릿

누락 daily와 weekly를 함께 발행했을 때 사용한다.

```text
🗓 *Imaging Intelligence Briefing Catch-up — YYYY-MM-DD + Week WW*
🔗 <{SITE_URL}/posts/YYYY-MM-DD.html|누락 daily 보기>
🔗 <{SITE_URL}/posts/YYYY-MM-DD-weekly.html|weekly 보기>

📊 *Daily 핵심*
{daily 핵심 3~4줄}

🗓 *Weekly 핵심*
{weekly 핵심 3~4줄}

💡 *인사이트*
1. {짧은 제목}
2. {짧은 제목}
3. {짧은 제목}

📊 *버킷 현황*
`[FP] N · [Lens] N · [Phase] N · [Meta] N · [LF] N · [Tomo] N · [VS] N · [Recon] N · [DL] N`
```

---

## [18. 프롬프트 백업 규칙]

공개 repo의 `prompts/`에는 sanitized 버전만 저장한다.

제거/변수화 대상:
- Slack channel id → `{SLACK_CHANNEL_ID}`
- Slack channel name → `{SLACK_CHANNEL}`
- 로컬 작업 경로 → `{WORKDIR}`
- 개인 이메일, 내부 식별자, 비공개 API key

유지 대상:
- GitHub Pages URL
- ROI 버킷
- parser 실행 규칙
- mode resolver
- release gate
- 산출물 스키마

커밋 메시지:

```text
Backup prompt vYYYYMMDD (sanitized)
```

---

## [19. 국문 자연성 게이트]

최종 HTML을 저장하기 직전에 문체 QA를 한 번 더 수행한다. 목표는 "연구자가 실제로 한국어로 말하는 문장"이지, 영어 논문 메모를 한국어 조사만 붙여 옮긴 문장이 아니다.

### 금지/순화 표현

아래 표현은 그대로 쓰지 않는다.

- "정조준" → "직접 다룬다", "문제로 삼는다", "짚는다"
- "표면화" → "드러났다", "같이 나왔다", "분명해졌다"
- "batch" → "오늘 하루치", "같은 날 나온 논문들", "이번 묶음"
- "압력이 걸려 있다" → "비중이 커졌다", "필요성이 커졌다", "실험 수요가 보인다"
- "paradigm" → "연구 흐름", "문제 설정", "접근 방식"
- "substrate" → "기반 구조", "토대", "표현 기반"
- "audit" → "점검", "검증", "확인"
- "layer" → "층위", "단계", "부분"
- "측 결", "응용 결" → "쪽 논문", "응용 논문", "관찰점"
- "개별 처방", "각자 처방" → "각각의 약점을 하나씩 고치는 흐름", "문제별 해결책이 따로 나오던 단계"
- "처방" 단독 사용은 되도록 피하고, 실제로 무엇을 고치는지 쓴다. 예: "메모리 부족을 줄이는 방법", "새 명령을 못 따라가는 문제를 고치는 방법"

### 문장 QA 규칙

1. 한 문단에 영어식 명사구가 2개 이상 이어지면, 적어도 하나는 한국어 동사 문장으로 풀어쓴다.
2. "A와 B가 한 batch에 표면화"라고 쓰지 말고, "A와 B가 같은 날 같이 나왔다는 점이 중요합니다"처럼 말한다.
3. "실험적인 압력"처럼 한국어 독자가 바로 이해하기 어려운 추상 표현은 금지한다. "실제 로봇 실험과 배포에 가까운 단어가 더 자주 보입니다"처럼 관찰 가능한 말로 바꾼다.
4. 논문별 부록의 `문제/방법/의미` 불릿도 같은 게이트를 적용한다. 내부 메모체를 보존하지 말고, 교수에게 구두로 설명해도 어색하지 않은 문장으로 재작성한다.
5. survey나 taxonomy 논문을 묶을 때 `failure mode catalog`, `unified mapping`, `data infrastructure bottleneck` 같은 라벨만 나열하지 않는다. 각 라벨이 실제로 무슨 현상을 뜻하는지 한 문장씩 풀어 쓴다.
6. "처방", "단계", "프레임" 같은 추상어를 쓰면 반드시 앞뒤에 구체 예시를 붙인다. 예: "메모리 부족, 의도 파악 실패, 안전 문제처럼 각각의 약점을 하나씩 고치는 단계".
7. 저장 전 `정조준|표면화|batch|압력이 걸려|paradigm|substrate|audit|측 결|응용 결|개별 처방|각자 처방|catalog 단계|통합 매핑|진짜 bottleneck` 문자열 검색을 수행하고, 논문 제목이나 고유명사가 아닌 본문 매치는 수정한다.

### 압축어 해설 게이트

핵심 주장 문장은 "전문가가 보면 대충 아는 말"이 아니라 "처음 보는 독자도 되물을 필요가 없는 말"이어야 한다. 특히 thesis, 클러스터 표의 `왜 중요?`, 인사이트 첫 문단에는 아래 규칙을 적용한다.

1. `A → B` 형태의 변화 주장은 반드시 "예전에는 무엇을 봤고, 이제는 무엇을 보게 됐는지"로 풀어쓴다.
2. `reconstruction loss → reward alignment + interactive eval`처럼 압축된 표현은 그대로 끝내지 않는다.
   - 나쁜 예: "World Model 평가가 reconstruction loss에서 reward alignment + interactive eval로 전환입니다."
   - 좋은 예: "예전에는 World Model을 미래 영상을 얼마나 그럴듯하게 예측하느냐로 평가했는데, 이제는 그 예측이 로봇 행동 성공에 도움이 되는지와 상호작용 상황에서 계속 쓸 수 있는지를 더 묻기 시작했다는 뜻입니다."
3. `latent action supervision`, `world model`, `alignment`, `controllability`, `benchmark` 같은 용어는 첫 등장 문단에서 직관을 붙인다.
4. 핵심 요약은 "문제 → 바뀐 기준/방법 → 왜 중요한지" 순서로 쓴다. 기술어 나열은 이 순서를 대체할 수 없다.
5. 독자가 "그래서 그게 무슨 말인데?"라고 되물을 만한 문장이 보이면 실패로 간주하고 다시 쓴다.
6. `A에서 B로 이동`, `A가 B로 전환`, `A가 B로 재정렬` 같은 문장은 반드시 다음 문장에 함의를 붙인다. 함의는 "그래서 평가 기준/실험 설계/랩 파이프라인에서 무엇을 다르게 봐야 하는가"여야 한다.
7. `왜 A급인가:` 다음의 `핵심:` 블록은 abstract 원문을 영어로 붙여 넣지 않는다. 반드시 한국어로 재해석해서 "무엇을 하는 논문인지 + 기존과 뭐가 다른지 + 왜 중요한지"를 2~3문장으로 쓴다. 고유명사와 기술 약어는 유지해도 되지만, 문장의 주된 설명은 한국어여야 한다.

### 독자 친절성 게이트

전문어를 없애는 것이 목표가 아니다. 전문어를 쓰되, 독자가 그 단어를 모른다고 해도 문맥을 따라올 수 있게 "무슨 현상인지"와 "왜 중요한지"를 같이 열어준다. 특히 `개별 처방`, `실패 유형 정리`, `인프라 병목`, `평가축 전환`처럼 요약자 머릿속에서는 편한 말이지만 독자에게는 다시 해석을 요구하는 표현을 조심한다. thesis, 클러스터 표의 `왜 중요?`, 인사이트 첫 문단, 추천 연구주제 첫 문단은 아래 4단계를 되도록 모두 포함한다.

1. **라벨**: 논문들이 묶이는 이름을 짧게 붙인다. 예: VLA lock-in, data bottleneck, controllable video generation.
2. **현상 설명**: 그 라벨이 실제로 무엇을 뜻하는지 구체적인 행동/실패/평가 상황으로 풀어쓴다.
3. **근거 연결**: 어떤 논문들이 각각 어떤 조각을 보여주는지 2~3개만 연결한다.
4. **판단/영향**: 그래서 연구자가 내일부터 무엇을 다르게 봐야 하는지 말한다.

다음 문장 패턴은 금지한다.

```text
A가 X를 명명하고, B가 Y를 통합 매핑하며, C가 Z bottleneck을 클레임. 커뮤니티가 catalog 단계에 진입.
```

이런 문장은 정보가 많은 것처럼 보이지만 독자에게는 "그래서 무슨 일이 일어난 건데?"만 남긴다. 반드시 아래처럼 바꾼다.

```text
A는 모델이 어떤 상황에서 어떻게 실패하는지를 이름 붙인 논문입니다.
B는 그 실패가 안전 문제로 이어지는 경로와 평가 방법을 정리합니다.
C는 같은 문제를 모델 구조가 아니라 데이터 수집·정리·평가 파이프라인의 병목으로 봅니다.
그래서 오늘 흐름은 새 알고리즘 하나보다, 이 분야가 실패 유형과 인프라 병목을 체계적으로 정리하기 시작했다는 쪽에 가깝습니다.
```

### 문장 자체 점검 질문

최종 저장 전 핵심 문단마다 아래 질문을 던진다. 하나라도 "아니오"면 다시 쓴다.

1. 이 문장을 읽은 사람이 핵심 용어를 몰라도 대략 무슨 현상인지 알 수 있는가?
2. 논문 제목 3개를 나열하지 않고도 묶음의 공통 문제가 드러나는가?
3. "어제/기존 방식과 무엇이 달라졌는지"가 한국어 문장으로 설명됐는가?
4. "이게 우리 랩/독자에게 왜 중요한지"가 마지막에 판단으로 붙어 있는가?
5. 영어 명사구가 문장의 주된 정보 전달을 대신하고 있지 않은가?

### 압축어 해설 few-shot

아래 예시의 "좋은 예" 수준으로 풀어쓴다. 제목·thesis·클러스터 설명·인사이트 첫 문단에서 특히 중요하다.

**예시 1 — World Model 평가**

나쁜 예:
```text
World Model 평가가 reconstruction loss → reward alignment + interactive eval로 전환입니다.
```

좋은 예:
```text
예전에는 World Model을 "미래 영상을 얼마나 그럴듯하게 복원하거나 예측하느냐"로 많이 평가했는데,
이제는 "그 예측이 로봇 행동 성공에 실제로 도움이 되느냐"와
"상호작용 상황에서 계속 쓸 수 있느냐"가 더 중요해지고 있다는 뜻입니다.
```

**예시 2 — Latent Action Supervision**

나쁜 예:
```text
VLA의 latent action supervision이 image-based vs action-based formulation-task correspondence를 처음 정량화했습니다.
```

좋은 예:
```text
VLA를 학습시킬 때 행동을 그대로 맞히게 할지, 아니면 이미지 변화 속에 숨어 있는 행동 단서를 먼저 배우게 할지의 차이를
본격적으로 비교하기 시작했다는 뜻입니다. 쉽게 말하면 "로봇에게 정답 행동을 외우게 할 것인가,
장면이 어떻게 변해야 하는지를 먼저 이해하게 할 것인가"를 나눠 보기 시작한 겁니다.
```

**예시 3 — Controllable Video Generation**

나쁜 예:
```text
Video generation의 평가축이 visual quality에서 controllability와 latency로 이동했습니다.
```

좋은 예:
```text
예전에는 생성된 영상이 얼마나 그럴듯하고 예쁜지를 주로 봤다면,
이제는 원하는 카메라 경로와 움직임을 얼마나 안정적으로 조종할 수 있는지가 중요해졌습니다.
즉 "보기 좋은 샘플"보다 "실제로 원하는 장면을 만들 수 있는 도구인가"를 묻는 쪽으로 평가 기준이 바뀌는 겁니다.
```

**예시 4 — Diffusion Alignment**

나쁜 예:
```text
Diffusion alignment가 BT preference model에서 game-theoretic self-referential alignment로 이동했습니다.
```

좋은 예:
```text
diffusion 모델을 사람 취향에 맞추는 방식이 단순한 선호도 점수 맞추기에서 벗어나고 있다는 뜻입니다.
이제는 모델이 여러 후보를 서로 비교하고, 스스로 더 나은 방향을 찾게 만드는 쪽으로
평가와 학습 방식이 옮겨가고 있습니다.
```

**예시 5 — VLA Reasoning 표현**

나쁜 예:
```text
VLA의 reasoning 표현 층위가 explicit linguistic CoT에서 physical latent CoT + joint RL 최적화로 이동했습니다.
```

좋은 예:
```text
기존에는 VLA가 "내가 이렇게 생각했다"를 언어 문장으로 풀어 쓴 뒤 행동으로 바꾸는 방식에 가까웠는데,
이제는 로봇 행동에 바로 쓸 수 있는 latent 상태를 만들고 그 상태와 action을 RL로 함께 최적화하는 쪽으로 옮겨가고 있습니다.
함의는 평가 기준도 바뀐다는 점입니다. 앞으로는 reasoning 설명이 그럴듯한지보다,
그 표현이 실제 manipulation 성공률, 제어 지연시간, long-horizon 안정성을 얼마나 바꾸는지를 봐야 합니다.
```

**예시 6 — Benchmark / SOTA**

나쁜 예:
```text
LoViF가 4D World Model holistic QA benchmark를 제안했습니다.
```

좋은 예:
```text
4D World Model을 볼 때 단순히 영상이 예쁜지보다,
시간에 따라 물리적으로 말이 되는지와 입력 조건을 잘 따르는지를 함께 평가하려는 흐름입니다.
즉 "그럴듯한 동영상"이 아니라 "물리적으로 믿을 수 있는 시뮬레이션"인지 묻는 쪽으로 가고 있습니다.
```

**예시 6 — Survey / Catalog / Bottleneck**

나쁜 예:
```text
오늘은 Lock-in이 새 failure mode를 명명하고, VLA Safety Survey가 threats·challenges·evaluations·mechanisms를 통합 매핑하며,
VLA Data Survey가 'data infrastructure가 진짜 bottleneck' 클레임. VLA community가 개별 시도들의 catalog 단계에 진입한 신호.
```

좋은 예:
```text
어제까지는 VLA 논문들이 memory, intent, safety 같은 문제를 각각 따로 고치는 분위기였다면,
오늘은 그 문제들이 왜 생기고 어떻게 분류되는지를 정리하는 쪽으로 넘어갔습니다.
Lock-in은 적은 데모로 VLA를 추가학습했을 때 새 명령을 잘 못 따라가고 예전에 본 행동만 반복하는 현상을 이름 붙였고,
VLA Safety Survey는 어떤 위협을 걱정해야 하는지와 어떻게 평가·방어할지를 한 장의 지도처럼 묶습니다.
VLA Data Survey는 성능을 막는 병목이 모델 구조 하나가 아니라 데이터 수집·정리·벤치마크 파이프라인에 있다고 봅니다.
```
