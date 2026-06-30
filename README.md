# paper-daily-summary

arXiv 신규 논문(및 Crossref 저널 논문)을 매일 자동으로 수집·분류·요약해
HTML 브리핑과 RSS 피드로 발행하는 파이프라인입니다.
GitHub Actions가 정해진 시간에 스스로 실행하므로 **상시 켜둘 서버가 필요 없습니다.**

> 이 프로젝트는 [gisbi-kim/arxiv-daily-summary](https://github.com/gisbi-kim/arxiv-daily-summary)를 기반으로
> IIL-SNU 환경에 맞게 정리·재구성한 버전입니다.

배포 사이트: `https://iilab.io/paper-daily-summary`

---

## 목차

1. [개요](#개요)
2. [전체 아키텍처](#전체-아키텍처)
3. [코드 구조](#코드-구조)
4. [데이터 스키마](#데이터-스키마)
5. [관심 버킷 (ROI 분류)](#관심-버킷-roi-분류)
6. [Instruction(런북) 상세](#instruction런북-상세)
7. [자동화 셋업](#자동화-셋업-서버리스-api-키-없이)
8. [로컬 실행](#로컬-실행)
9. [주제(관심 분야) 바꾸기](#주제관심-분야-바꾸기)
10. [크레딧](#크레딧)

---

## 개요

- **수집**: arXiv `/new`·`/pastweek` 목록을 Python 표준 라이브러리만으로 직접 파싱합니다.
  (LLM에게 논문 ID를 묻지 않아 환각으로 인한 잘못된 ID를 원천 차단합니다.)
  추가로 Crossref REST API로 저널 논문도 같은 스키마로 가져옵니다. 저널 수집은 **arXiv 발행 여부와 무관**하게 동작하며(arXiv 공백일엔 `journal-only` 발행), OpenAlex로 인용수·concepts·초록을 **보강(enrich)**합니다.
- **분류**: 키워드 매칭으로 논문을 관심 버킷(ROI)에 자동 배정합니다. (LLM·API 키 불필요)
- **요약**: Claude Code 에이전트가 분류 결과를 읽고, `prompts/`의 instruction 런북을 따라
  자연어 브리핑 HTML과 구조화 JSON(trends/insights/benchmarks/weekly)을 작성합니다.
- **발행**: RSS(`feed.xml`)·랜딩 페이지(`index.html`)를 생성하고 GitHub Pages로 배포합니다.

핵심 설계 원칙: **수집·분류는 키 없는 결정론적 코드**, **요약만 LLM**. 즉 API 키가 필요한 단계는
자연어 브리핑을 쓰는 Claude Code 호출 한 곳뿐입니다.

---

## 전체 아키텍처

```
매일 정해진 시각 (GitHub Actions cron)
  └─ 러너 기동
      │
      ├─ [수집] fetch_arxiv.py new/pastweek cs.XX  ─→ out/*_new.json, out/*_pastweek.json
      │         fetch_crossref.py --query/--issn   ─→ out/journal_new.json (선택)
      │
      ├─ [분류] classify.py                         ─→ out/classified.json (버킷별 그룹)
      │
      ├─ [요약] Claude Code 에이전트
      │         (prompts/instruction.md 런북 기반)
      │         ─→ posts/YYYY-MM-DD.html
      │            trends/ benchmarks/ insights/ weekly/ *.json
      │            index.html
      │
      ├─ [검증] validate_daily_release.py           ─→ Release Gate 통과 시 out/release_ok.txt
      │
      ├─ [피드] build_feed.py                        ─→ feed.xml
      │
      └─ [발행] git commit & push (release_ok.txt 있을 때만)
                  └─ pages.yml 이 push 감지 → GitHub Pages 배포
```

`fetch` → `classify` → `build`는 전부 stdlib라 키 없이 동작하고, 가운데 `[요약]`만 Claude Code를 씁니다.

---

## 코드 구조

| 경로 | 역할 |
|------|------|
| `.github/workflows/arxiv-daily-summary.yml` | 매일 실행되는 메인 자동화 워크플로우(cron + 수동 실행) |
| `.github/workflows/pages.yml` | `main` push 시 GitHub Pages 배포 |
| `prompts/instruction.md` | Claude Code 에이전트용 instruction 런북(권위 실행 문서) |
| `scripts/` | 수집·분류·빌드·검증 스크립트 (아래 표 참고) |
| `posts/` `trends/` `benchmarks/` `insights/` `weekly/` | 일별 산출물(초기엔 비어 있고 `.gitkeep`만 존재) |
| `feed.xml` `index.html` | 발행 결과물(파이프라인이 생성) |

### scripts/ 상세

**수집(fetch)**

| 스크립트 | 역할 |
|----------|------|
| `fetch_arxiv.py` | arXiv `/new`·`/pastweek` 목록 페이지를 stdlib로 파싱. `new`는 초록 포함, `pastweek`는 미포함. 출력은 JSON 배열 |
| `fetch_crossref.py` | Crossref REST API로 최근 저널 논문 수집. `--query`(키워드)·`--issn`(특정 저널) 모드 지원. `fetch_arxiv.py`와 **동일 스키마** + 저널 필드(`source`,`doi`,`journal`,`url`,`published`). `classify.py`가 `out/journal_new.json`을 자동으로 함께 분류(저널은 `JNL` badge) |
| `fetch_openalex.py` | OpenAlex 보강 레이어(무키). `enrich`: Crossref 저널에 `cited_by_count`·`concepts`를 붙이고 빠진 초록(~50%)을 백필. `works`: 저널 보충 소스 수집(`source=openalex`, `OAX` badge, `out/openalex_new.json`). created_date 필터 대신 `publication_date` 사용 |
| `fetch_arxiv_pastweek_date.py` | 과거 특정 날짜를 `/pastweek`에서 추출(backfill 전용) |

**분류(classify)**

| 스크립트 | 역할 |
|----------|------|
| `classify.py` | `out/*_new.json`을 읽어 `BUCKETS` 키워드 매칭으로 ROI 버킷 배정. dedup·badge 부여 후 `classified.json` 출력. **관심 주제를 바꾸는 핵심 파일** |

**빌드/발행(build)**

| 스크립트 | 역할 |
|----------|------|
| `build_feed.py` | `posts/*.html`에서 제목·요약을 추출해 RSS 2.0 `feed.xml` 생성. `SITE_URL`은 환경변수 우선 |
| `build_preview.py` | `classified.json`을 정적 HTML(`out/preview.html`)로 렌더링하는 결정론적 미리보기(LLM 미사용) |
| `build_weekday_counts.py` | 요일별 통계(`stats/`) 산출 |
| `reconcile_index.py` | **안전망** — `index.html`이 모든 `posts/*.html`을 링크하는지 점검하고, 에이전트가 빠뜨린 daily/weekly를 자동 삽입(누락 없으면 무동작). 릴리스 단계에서 실행 |

**검증/유틸**

| 스크립트 | 역할 |
|----------|------|
| `validate_daily_release.py` | Release Gate 검증(`--date YYYY-MM-DD`). 통과해야 발행 |

---

## 데이터 스키마

**논문 객체** (fetch 단계 출력, classify 입력) — arXiv 기준:

```jsonc
{
  "arxiv_id": "2606.01234",
  "title": "...",
  "authors": ["...", "..."],
  "first_author": "...",
  "subjects": "Machine Learning (cs.LG); Image and Video Processing (eess.IV)",
  "primary_cat": "cs.LG",
  "section": "new",            // "new" | "cross" | "replace"
  "abstract": "..."            // /new 만 포함
}
```

Crossref(저널)는 위에 더해 `source:"crossref"`, `doi`, `journal`, `url`, `published`를 갖고,
`arxiv_id` 대신 `id:"doi:..."`를 dedup 키로 씁니다.

**classify.py 출력** (`classified.json`):

```jsonc
{
  "total": 312,                 // dedup 후 전체 논문 수
  "selected": 88,               // 버킷에 배정된 수
  "categories": ["cs.LG", "cs.CV", "cs.AI", "eess.IV", "eess.SP"],
  "buckets": {
    "Phase Imaging/Holography": {
      "total": 24,
      "by_badge": { "LG": 9, "CV": 4, "IV": 3, "JNL": 8 },   // 카테고리/저널별 분포
      "papers": [ /* 논문 객체 + bucket, badge 필드 추가 */ ]
    }
    // ... 버킷별
  }
}
```

---

## 관심 버킷 (ROI 분류)

`classify.py`는 각 논문을 제목·초록·subject의 **키워드 매칭**으로 아래 9개 버킷 중 가장 많이 맞는 곳에 배정합니다(매칭 0이면 미분류 → 브리핑 제외). 버킷은 **계산광학(Imaging Intelligence Lab)** 기준으로, 광학 주제(1–7)와 arXiv에서 소비하는 ML 방법론(8–9)을 함께 둡니다.

| # | 버킷 | 대표 키워드 |
|---|------|-------------|
| 1 | **Fourier Ptychography/Microscopy** | Fourier ptychography, computational microscopy, aperture synthesis, coded illumination |
| 2 | **Lensless/Coded Imaging** | lensless, coded aperture, PSF engineering, diffuser, single-shot, computational camera |
| 3 | **Phase Imaging/Holography** | quantitative phase, phase retrieval, (digital/CG) holography, wavefront, interferometry |
| 4 | **Meta-Optics/Diffractive** | metasurface, metalens, meta-optics, diffractive optics, inverse lithography |
| 5 | **Light-Field/Novel Sensors** | light field, plenoptic, event camera, neuromorphic, integral imaging |
| 6 | **Tomography/3D Imaging** | optical diffraction tomography, volumetric, 3D reconstruction, Gaussian splatting, NeRF |
| 7 | **Virtual Staining/Pathology** | virtual staining, digital pathology, histopathology, label-free, H&E |
| 8 | **Reconstruction/Inverse Problems** | image reconstruction, inverse problem, deep unfolding, plug-and-play, compressed sensing |
| 9 | **Deep Learning Methods** | diffusion/generative, neural network, self-supervised, foundation model, super-resolution |

동작 규칙:
- **순서가 우선순위** — 키워드 매칭 수가 같으면 위쪽(광학 전용) 버킷이 이깁니다. 광학 논문이 일반 ML 용어 때문에 8–9번으로 새지 않게 하기 위함.
- **저널도 동일 분류** — Crossref 저널 논문(`JNL` badge)도 같은 버킷 로직으로 arXiv와 함께 배정됩니다. (실측: 저널 분류율 약 83%)
- **badge** — 논문 출처 표시: arXiv 카테고리(`LG`/`CV`/`AI`/`IV`/`SP`) 또는 저널(`JNL`).

버킷·키워드는 `scripts/classify.py`의 `BUCKETS`에서 수정합니다. 현재 키워드는 lab 출판물과 추적 문헌(*Literature Review List*) 제목 503건의 빈도 분석에서 도출했습니다.

---

## Instruction(런북) 상세

`prompts/instruction.md`는 Claude Code 에이전트가 따르는 **권위 실행 문서**입니다.
워크플로우는 `out/ci_prompt.md`로 이 파일을 런북으로 지정합니다. 주요 섹션:

| 섹션 | 내용 |
|------|------|
| `[0] 실행 변수` | `WORKDIR`, `SITE_URL`, `GITHUB_REPO`, `SLACK_CHANNEL(_ID)` 등 환경값 |
| `[1] 최상위 원칙` | **WebFetch 금지** — 목록은 반드시 parser 스크립트로. parser 실패 시 중단(오발행 금지) |
| `[2] 날짜 개념 분리` | `execution_date` / `listing_date` / `post_date`를 구분. `/new`의 실제 날짜와 발행일이 다르면 중단하는 **hard gate** |
| `[3] Calendar Audit` | 모든 실행의 첫 단계. 빠진 평일 daily를 먼저 복구 |
| `[4] Mode Resolver` | `Backfill` / `Daily` / `Weekly` / `Sunday` 모드를 명시적으로 결정 |
| `[5~6] Parser 실행·검증` | 카테고리별 fetch 명령, Windows UTF-8 주의, 파싱 검증 체크리스트 |
| `[7] 랩 ROI 버킷` | 관심 버킷 정의(분류 기준) |
| `[8] 톤·문체 / [8.5] 품질 위계` | 오늘의 thesis → 클러스터 우선 → 대표 클러스터 표 → Watch Lens → 중요도 태그 → confidence |
| `[9] 요약 품질 계층` | Tier A(판 바꾸는 3~5편) / Tier B(대표 8~12편) / Tier C(나머지) |
| `[10~11] Daily/Weekly 산출물` | 일간·주간 HTML 구성 규칙 |
| `[12] 벤치마크·인사이트 JSON` | `benchmarks/`·`insights/` 구조화 데이터 규격 |
| `[13] RSS·index 호환` | `feed.xml`·`index.html` 정합 규칙 |
| `[14] TTS 오디오` | 음성 요약(선택) |
| `[15] Release Gate` | `validate_daily_release.py` 포함 발행 전 검증 게이트 |
| `[16] GitHub Pages 배포` | commit·push 규칙 |
| `[17] Slack 발송` | Daily/Weekly/Catch-up 알림 템플릿 |
| `[18] 프롬프트 백업 / [19] 국문 자연성 게이트` | 프롬프트 버전 관리, 한국어 표현 품질 검사 |

> 런북은 `prompts/instruction.md` 하나이며, 워크플로우의 ci_prompt가 이를 권위 문서로 지정합니다.

---

## 자동화 셋업 (서버리스, API 키 없이)

요약 단계는 Anthropic **API 키(종량 과금)** 대신 **Claude Pro/Max 구독 기반 OAuth 토큰**으로 인증합니다.

1. 로컬에서 토큰을 1회 발급합니다. (Claude Pro/Max 구독 필요)
   ```bash
   claude setup-token
   ```
2. GitHub repo → **Settings → Secrets and variables → Actions** 에 시크릿 등록:
   - `CLAUDE_CODE_OAUTH_TOKEN` (필수)
   - `SLACK_BOT_TOKEN` (선택 — Slack 알림 사용 시. Slack 앱의 *Bot User OAuth Token* `xoxb-…`, `chat:postMessage` 스코프 필요)
   - 워크플로우 env의 `SLACK_CHANNEL_ID`에 게시할 채널 ID(예: `C0XXXXXXX`)를 넣고 **봇을 해당 채널에 초대**해야 합니다(`/invite @봇이름`).
3. **Settings → Actions → General → Workflow permissions** 를 *Read and write* 로 설정
4. **Settings → Pages → Source** 를 *GitHub Actions* 로 설정

스케줄은 두 가지입니다(`arxiv-daily-summary.yml`의 `cron`으로 조정): **daily 보고서**는 매일 `02:00 UTC`(= `11:00 KST`)에 생성하고 같은 실행에서 Slack까지 보냅니다(arXiv `/new`가 오전 9~10시 KST에 올라오므로 11시면 안전; 주말 포함 매일 실행, 새 글 없으면 no-op). **weekly 회고**는 매주 월요일 `01:00 UTC`(= `10:00 KST`)에 **별도 실행**으로 생성+Slack합니다. 추가로 **2시간마다 가벼운 폴**(`0 */2 * * *`)이 도는데, Claude를 돌리기 전에 *journal-only로 발행된 날짜의 arXiv가 `/pastweek`에 떴는지*만 싸게 확인하고, 떴을 때만 `backfill`로 그 날짜를 완성본으로 업그레이드합니다(평소엔 무동작).
**weekly 회고는 매주 월요일 오전 10시 KST의 독립 실행**으로 발행됩니다(지난주 회고, daily와 분리). daily는 매일(주말 포함) 11시에 돌며 arXiv에 새 글이 없으면 no-op.
Slack 알림은 각 실행의 마지막 단계가 보냅니다 — **daily 실행은 daily 요약**, **월요일 weekly 실행은 weekly 요약**, **실행 실패 시 실패 알림**(모두 push 성공 직후 `chat.postMessage`로 `SLACK_CHANNEL_ID` 채널에). 발행도 실패도 아닌 **no-op(주말 daily 등)은 미발송**(`out/release_ok.txt` 기준)입니다.
워크플로우는 `mode`(auto/daily/backfill/weekly/sunday)·`target_date`·`send_slack`을 수동 실행 입력으로 받습니다.

> ⚠️ **첫 실행은 `auto` 모드를 피하세요.** `auto`는 빠진 평일을 과거로 거슬러 채우는 Calendar Audit을 수행합니다.
> 산출물이 비어 있는 초기에는 **Actions 탭 → 수동 실행(`workflow_dispatch`) → `mode: daily`** 로 당일분만 생성하길 권장합니다.

### 워크플로우 동작 요약 (`arxiv-daily-summary.yml`)

1. Python 3.11 · Node 20 설정 → `CLAUDE_CODE_OAUTH_TOKEN` 존재 확인
2. `npm install -g @anthropic-ai/claude-code` 후 `out/ci_prompt.md` 생성
3. `claude -p "$(cat out/ci_prompt.md)"` — 에이전트가 런북대로 수집·분류·요약·검증 수행
4. `out/release_ok.txt`가 있으면(=검증 통과) commit & push → `pages.yml`이 배포
5. (선택) Slack 알림, 실행 아티팩트 업로드

---

## 로컬 실행

현재 추적 카테고리: **`cs.LG` · `cs.CV` · `cs.AI` · `eess.IV` · `eess.SP`** (영상·신호 기반 ML)

```bash
mkdir -p out

# 1) 수집 (arXiv) — 출력 파일명은 out/<cat>_new.json 고정
for cat in cs.LG cs.CV cs.AI eess.IV eess.SP; do
  python scripts/fetch_arxiv.py new      "$cat" > "out/${cat}_new.json"
  python scripts/fetch_arxiv.py pastweek "$cat" > "out/${cat}_pastweek.json"
done

# 1-b) 수집 (저널, 선택) — Crossref, mailto=imaging.snu@gmail.com
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
  --days 1 > out/journal_new.json
# 기준: Crossref 등록일(created-date) · daily는 1일(전날 등록분), 주간/backfill은 더 넓게 · 키워드 관련도순

# 2) 분류
python scripts/classify.py > out/classified.json

# 3) 피드 (요약 HTML 생성 후)
python scripts/build_feed.py
```

요약(HTML) 단계는 `prompts/instruction.md` 런북을 Claude Code에 전달해 수행합니다.

---

## 주제(관심 분야) 바꾸기

본인 연구 주제로 바꾸려면 다음을 수정합니다.

1. **추적 카테고리** — `scripts/classify.py` 상단 `CATEGORIES` 리스트 교체
   (그리고 런북 `[5]`의 fetch 명령 카테고리도 함께. [arXiv category taxonomy](https://arxiv.org/category_taxonomy) 참고)
2. **관심 버킷/키워드** — `scripts/classify.py`의 `BUCKETS` 딕셔너리 교체. badge가 필요하면 `CAT_BADGE`도 갱신
3. **런북** — `prompts/instruction.md`의 카테고리·버킷·분석 렌즈를 본인 주제에 맞게 조정
4. **저널 쿼리** — `fetch_crossref.py`의 `--query`/`--issn` 값(런북 `[5]`의 호출 포함)을 본인 분야로
5. **RSS 메타** — `build_feed.py`의 `FEED_TITLE`/`FEED_DESC`

---

## 크레딧

- 원본 프로젝트: [gisbi-kim/arxiv-daily-summary](https://github.com/gisbi-kim/arxiv-daily-summary)
