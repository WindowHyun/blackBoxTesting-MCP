"""capture_images — put the pictures in front of a human.

Pixel-diff visual regression is out of scope (baseline management, tolerance
tuning, flaky anti-aliasing). But the failure it would catch — "every product
shows the wrong picture" — is common and completely invisible to structural
assertions: the <img> exists, has alt text, loads, and passes every check this
project can make.

So this does the honest thing instead of guessing: it CAPTURES each image and
puts it in the report for a person to look at. Judgement stays with the human;
the tool's job is to make looking cheap.

Two checks are automated because they are facts, not opinions:
  broken   naturalWidth == 0 — the image did not load at all
  same_src several images resolving to ONE url. Legitimate sometimes (a shared
           placeholder), damning often (every product showing one picture).
           Reported as a finding to review, never as a failure.
"""
from __future__ import annotations

import re

from ..browser import get_session
from ..testing import report as report_mod
from ._registry import tool

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")
_MAX_IMAGES = 40

# Read the images' own view of themselves: the resolved src (currentSrc follows
# srcset, which is what the user actually sees) and whether the bitmap arrived.
_COLLECT_JS = """
(root) => {
  const imgs = [...root.querySelectorAll('img')].slice(0, 200);
  return imgs.map((el, i) => ({
    index: i,
    src: el.currentSrc || el.src || '',
    alt: el.getAttribute('alt'),
    natural_width: el.naturalWidth,
    natural_height: el.naturalHeight,
    displayed: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  }));
}
"""


@tool(description="이미지 증거 수집: 페이지의 <img>를 각각 캡처해 리포트에 남긴다. "
                  "'올바른 그림인가'는 자동 판정하지 않는다 — 사람이 보고 확인하도록 "
                  "이미지를 노출하는 것이 목적이다. 다만 사실로 판정 가능한 두 가지는 "
                  "자동 표시한다: 로드 실패(naturalWidth=0)와 여러 이미지가 같은 src를 "
                  "가리키는 경우. selector로 범위를 좁힐 수 있다(기본: 페이지 전체).")
async def capture_images(selector: str | None = None, limit: int = 12,
                         capture: bool = True, name: str = "images") -> dict:
    session = await get_session()
    root = session.root

    scope = root.locator(selector).first if selector else root.locator("body")
    try:
        found = await scope.evaluate(_COLLECT_JS)
    except Exception as exc:
        return {"ok": False, "error": f"이미지를 읽지 못함: {type(exc).__name__}: {exc}"}

    limit = max(1, min(int(limit or 12), _MAX_IMAGES))
    images = found[:limit]

    shots_dir = report_mod.ensure_dirs() / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _SAFE.sub("_", name)[:40] or "images"

    for entry in images:
        entry["broken"] = entry.get("natural_width") == 0
        if not capture:
            entry["screenshot"] = None
            continue
        # Element screenshot, not a page screenshot: the point is to look at
        # THIS picture, and a full page makes a reviewer hunt for it.
        try:
            target = scope.locator("img").nth(entry["index"])
            filename = f"{report_mod.new_run_id()}_{safe_name}_{entry['index']:02d}.png"
            await target.screenshot(path=str(shots_dir / filename), timeout=5000)
            entry["screenshot"] = f"screenshots/{filename}"
        except Exception:
            entry["screenshot"] = None      # off-screen/zero-size; src still recorded

    findings: list[str] = []
    broken = [e for e in images if e["broken"]]
    if broken:
        findings.append(f"로드 실패 {len(broken)}건: "
                        + ", ".join((e["src"] or "?")[-50:] for e in broken[:3]))

    by_src: dict[str, int] = {}
    for e in images:
        if e.get("src"):
            by_src[e["src"]] = by_src.get(e["src"], 0) + 1
    duplicates = {src: n for src, n in by_src.items() if n > 1}
    if duplicates:
        worst = max(duplicates.items(), key=lambda kv: kv[1])
        findings.append(
            f"같은 이미지를 가리키는 <img> {worst[1]}개: …{worst[0][-60:]} "
            "— 공용 플레이스홀더면 정상, 상품 목록이면 결함일 수 있으니 확인할 것")

    missing_alt = [e for e in images if not (e.get("alt") or "").strip()]
    if missing_alt:
        findings.append(f"alt 없음 {len(missing_alt)}건 (접근성)")

    return {
        "ok": True,
        "count": len(images),
        "total_on_page": len(found),
        "images": images,
        "findings": findings,
        # Said plainly so neither a reviewer nor an LLM reads silence as a pass.
        "note": ("이미지가 '올바른 그림인지'는 판정하지 않았다. "
                 "리포트의 이미지 증거 섹션을 사람이 보고 확인할 것."),
    }
