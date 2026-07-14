# Releasing to PyPI

**현재 상태: 배포 중.** https://pypi.org/project/ui-blackbox-mcp/ —
v0.1.0이 trusted publishing(경로 A)으로 게시됐고(2026-07), 실PyPI에서
`pip install ui-blackbox-mcp` → `ui-blackbox doctor` OK 실측 확인됨.
trusted publisher 등록(최초 1회)은 완료 상태라, 이후 릴리스는 아래
"매 릴리스" 절차만 반복하면 된다.

패키징은 [공식 튜토리얼](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
절차를 따른다(`python -m build` → wheel+sdist, `twine check`, 깨끗한 venv
설치 검증). **경로 A 권장**(토큰을 어디에도 저장하지 않음).

## 경로 A (권장) — GitHub Release → 자동 배포 (Trusted Publishing)

최초 1회 설정(✅ 완료됨 — 새 저장소/프로젝트로 옮길 때만 다시 필요):
1. https://pypi.org 계정 생성(2FA 필수).
2. PyPI → **Publishing** → *Add a new pending publisher*:
   - PyPI Project Name: `ui-blackbox-mcp`
   - Owner: `WindowHyun` / Repository: `blackBoxTesting-MCP`
   - Workflow name: `release.yml` / Environment name: `pypi`

이후 매 릴리스:
1. `blackbox_mcp/__init__.py`의 `__version__` 올리고 커밋.
2. 태그 + GitHub Release 발행:
   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   gh release create v0.1.0 --generate-notes   # 또는 GitHub UI에서 Release 생성
   ```
3. `.github/workflows/release.yml`이 빌드 → `twine check` → **휠 부팅 검증**
   (설치 후 25개 도구 등록 assert) → OIDC로 PyPI 게시까지 자동 수행한다.
   토큰/시크릿 저장이 전혀 없다.

## 경로 B — 로컬에서 twine 업로드 (튜토리얼 방식)

1. PyPI(또는 리허설용 TestPyPI) 계정에서 **API token** 발급.
2. 빌드·검사·업로드:
   ```bash
   python -m pip install --upgrade build twine
   python -m build
   python -m twine check dist/*

   # 리허설(TestPyPI) — 계정/토큰은 test.pypi.org에서 별도 발급
   python -m twine upload --repository testpypi dist/*
   pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ui-blackbox-mcp

   # 실제 업로드
   python -m twine upload dist/*
   # username: __token__ / password: pypi-… 토큰
   ```
   토큰은 셸 히스토리·저장소에 남기지 말 것(프롬프트 입력 또는
   `~/.pypirc`(chmod 600) 사용).

## 배포 후

- 설치가 짧아진다: `uvx ui-blackbox-mcp` · `pip install ui-blackbox-mcp`
  (README Quick start의 git+ URL을 패키지명으로 바꿔도 됨).
- 스모크: `uvx ui-blackbox-mcp@latest --help`가 아닌 **MCP stdio 서버**이므로
  클라이언트 연결로 확인하거나 `uvx --from ui-blackbox-mcp ui-blackbox doctor`.

## 버전 규칙

- 단일 출처: `blackbox_mcp/__init__.py` `__version__` (hatch dynamic).
- 태그는 `v{__version__}` 형식. 같은 버전 재업로드는 PyPI가 거부하므로
  실패 시 버전을 올려 다시 릴리스한다.
