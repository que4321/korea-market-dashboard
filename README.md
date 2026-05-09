# 🇰🇷 한국 시장 방향성 대시보드

EWY 옵션 P/C Ratio, 반도체 야간 동향, USD/KRW를 조합한 KOSPI 방향성 참고 대시보드

## 배포 순서

### 1. GitHub 저장소 생성 & 파일 업로드
```bash
git init
git add .
git commit -m "init: 한국 시장 대시보드"
git remote add origin https://github.com/<유저명>/korea-market-dashboard.git
git push -u origin main
```

### 2. GitHub Pages 활성화
- Settings → Pages → Source: **Deploy from a branch**
- Branch: `main` / `/ (root)` 선택 → Save

### 3. GitHub Actions 자동 실행 확인
- Actions 탭 → `시장 데이터 수집` 워크플로 확인
- 첫 실행: Actions 탭에서 수동 실행 (`workflow_dispatch`)

### 4. 접속 주소
```
https://<유저명>.github.io/korea-market-dashboard/
```

---

## 파일 구조

```
├── index.html              # 대시보드 (Yahoo Finance 실시간 + 히스토리)
├── data/
│   └── history.json        # GitHub Actions가 매일 누적 저장 (최대 90일)
├── scripts/
│   └── collect.py          # 데이터 수집 스크립트
└── .github/workflows/
    └── collect.yml         # 매일 KST 07:00 자동 실행
```

---

## 포함 지표

| 지표 | 설명 | 신뢰도 |
|------|------|--------|
| EWY P/C Ratio | 외국인 한국 노출 헤지 방향 | ★★★★ |
| EWY IV (내재변동성) | VKOSPI 추정 대리 지표 | ★★★ |
| Put/Call OI 집중 행사가 | 기관 헤지 하한/상단 레벨 | ★★★ |
| NVDA / SOXX 등락 | 반도체 야간 센티먼트 | ★★★★ |
| USD/KRW | 원화 강약 (외국인 수급 영향) | ★★★ |

---

## 주의사항
- 본 대시보드는 참고용이며 투자 조언이 아닙니다.
- 독일 상장 하이닉스·삼성전자는 유동성 부족으로 방향성만 참고하세요.
