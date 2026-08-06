"""Ordering assertions, image evidence, and the presence probe.

The probe is the important one: it is what finally separates "the element was
renamed" from "the element is right there and stopped behaving". Before it,
both produced `ui_changed` + `test_fix_allowed=True`, which would let a loop
rewrite a real defect out of the suite.
"""
from __future__ import annotations

import dataclasses

import pytest

from blackbox_mcp.testing import diagnose, report
from blackbox_mcp.tools.assertion import _as_number, _is_sorted, assert_
from blackbox_mcp.tools.images import capture_images


# ── numeric parsing for ordering ─────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("$29.99", 29.99), ("29.99", 29.99), ("₩1,299", 1299.0),
    ("$1,299.00", 1299.0), ("-5", -5.0), ("12개", 12.0),
    ("Sauce Labs Backpack", None), ("", None),
])
def test_number_extraction(text, expected):
    assert _as_number(text) == expected


def test_price_ordering_is_numeric_not_lexicographic():
    """Why prices must be compared as numbers: as TEXT, "$100" sorts before
    "$9", so a naive check calls a badly-ordered price list correctly sorted.
    Comparing the parsed numbers gives the right answer."""
    assert _is_sorted(["$100", "$9"], descending=False), "텍스트로는 정렬로 보인다"
    assert not _is_sorted([100.0, 9.0], descending=False), "숫자로는 아니다"


# ── ordering assertions on a real page ───────────────────────────
async def test_order_asc_passes_on_sorted_prices(session):
    await session.page.set_content(
        "<div class=p>$7.99</div><div class=p>$15.99</div><div class=p>$29.99</div>")
    res = await assert_("order_asc", ".p")
    assert res["passed"], res
    assert res["compared_as"] == "numeric"


async def test_order_asc_fails_on_unsorted_and_shows_the_sequence(session):
    await session.page.set_content(
        "<div class=p>$29.99</div><div class=p>$9.99</div><div class=p>$15.99</div>")
    res = await assert_("order_asc", ".p")
    assert not res["passed"]
    assert "$29.99" in res["actual"] and "$9.99" in res["actual"]


async def test_order_desc(session):
    await session.page.set_content(
        "<div class=p>$49.99</div><div class=p>$15.99</div><div class=p>$7.99</div>")
    assert (await assert_("order_desc", ".p"))["passed"]
    assert not (await assert_("order_asc", ".p"))["passed"]


async def test_text_ordering_when_values_are_not_numbers(session):
    await session.page.set_content(
        "<div class=n>Apple</div><div class=n>Banana</div><div class=n>Cherry</div>")
    res = await assert_("order_asc", ".n")
    assert res["passed"] and res["compared_as"] == "text"


async def test_numeric_mode_rejects_unparseable_values(session):
    await session.page.set_content("<div class=p>$7.99</div><div class=p>무료</div>")
    res = await assert_("order_asc", ".p", "numeric")
    assert not res["passed"]
    assert "숫자로 읽을 수 없는" in res["actual"]


async def test_text_sequence_matches_a_prefix(session):
    await session.page.set_content(
        "<li class=i>Onesie</li><li class=i>Bike Light</li><li class=i>Backpack</li>")
    assert (await assert_("text_sequence", ".i", "Onesie, Bike Light"))["passed"]
    assert not (await assert_("text_sequence", ".i", "Backpack, Onesie"))["passed"]


async def test_text_sequence_needs_an_expected_list(session):
    await session.page.set_content("<li class=i>a</li>")
    res = await assert_("text_sequence", ".i")
    assert not res["passed"] and "expected가 비었다" in res["actual"]


# ── the presence probe ───────────────────────────────────────────
async def test_probe_reports_a_hidden_element_as_present(session):
    """The cart-badge case: in the DOM, not visible. Present → the app's
    behaviour changed, NOT a rename."""
    await session.page.set_content("<span class=badge hidden>1</span>")
    res = await assert_("element_visible", ".badge")
    assert not res["passed"]
    assert res["probe"] == {"element_present": True, "element_count": 1,
                            "visible_count": 0}


async def test_probe_reports_a_renamed_element_as_absent(session):
    await session.page.set_content("<span class=badge-new>1</span>")
    res = await assert_("element_visible", ".badge")
    assert not res["passed"]
    assert res["probe"]["element_present"] is False


async def test_no_probe_on_a_passing_assertion(session):
    await session.page.set_content("<span class=badge>1</span>")
    res = await assert_("element_visible", ".badge")
    assert res["passed"] and "probe" not in res


async def test_no_probe_for_url_assertions(session):
    res = await assert_("url_contains", "definitely-not-in-the-url")
    assert not res["passed"] and "probe" not in res


# ── the probe drives the classification ──────────────────────────
def test_present_element_classifies_as_app_behavior():
    step = {"action": "assert", "selector_input": ".badge", "actual": "False",
            "severity": "assertion", "passed": False,
            "probe": {"element_present": True, "element_count": 1, "visible_count": 0}}
    v = diagnose.classify(step)
    assert v["cause"] == diagnose.APP_BEHAVIOR
    assert v["test_fix_allowed"] is False, "동작 결함을 테스트 수정으로 덮으면 안 된다"
    assert any("보이지 않음" in e for e in v["evidence"])


def test_absent_element_classifies_as_ui_changed():
    step = {"action": "assert", "selector_input": ".badge", "actual": "False",
            "severity": "assertion", "passed": False,
            "probe": {"element_present": False, "element_count": 0, "visible_count": 0}}
    v = diagnose.classify(step)
    assert v["cause"] == diagnose.UI_CHANGED
    assert v["test_fix_allowed"] is True
    assert v["confidence"] == "high"


def test_app_broken_still_outranks_a_present_element():
    """A page that threw is an app defect even though the element is there."""
    step = {"action": "assert", "selector_input": ".badge", "actual": "False",
            "severity": "assertion", "passed": False,
            "console_errors": [{"source": "pageerror", "text": "boom"}],
            "probe": {"element_present": True, "element_count": 1, "visible_count": 0}}
    assert diagnose.classify(step)["cause"] == diagnose.APP_BROKEN


def test_run_verdict_mentions_behaviour_change():
    step = {"action": "assert", "selector_input": ".b", "actual": "False",
            "severity": "assertion", "passed": False,
            "probe": {"element_present": True, "element_count": 2, "visible_count": 2}}
    d = diagnose.diagnose_result({"name": "s", "steps": [step]})
    assert "동작 변경/결함" in d["verdict"]


# ── image evidence ───────────────────────────────────────────────
@pytest.fixture
def shots(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))
    return tmp_path


async def test_images_are_captured_with_their_metadata(session, shots):
    await session.page.set_content(
        '<img src="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 '
        'width=%2210%22 height=%2210%22/>" alt="첫번째">'
        '<img src="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 '
        'width=%2210%22 height=%2210%22/>" alt="두번째">')
    await session.page.wait_for_timeout(200)

    res = await capture_images(limit=5)
    assert res["ok"] and res["count"] == 2
    assert all(i["screenshot"] for i in res["images"])
    assert [i["alt"] for i in res["images"]] == ["첫번째", "두번째"]
    for i in res["images"]:
        assert (shots / i["screenshot"]).exists()


async def test_identical_sources_are_flagged_for_review(session, shots):
    """The defect-lab D-1 signature — reported as something to look at, never
    as a verdict."""
    src = ('data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 '
           'width=%2210%22 height=%2210%22/>')
    await session.page.set_content(
        f'<img src="{src}" alt=a><img src="{src}" alt=b><img src="{src}" alt=c>')
    await session.page.wait_for_timeout(200)

    res = await capture_images()
    assert any("같은 이미지" in f for f in res["findings"])
    assert res["ok"] is True, "판정이 아니라 관찰이므로 ok는 유지된다"
    assert "판정하지 않았다" in res["note"] and "사람이 보고 확인" in res["note"]


async def test_broken_image_is_detected(session, shots):
    await session.page.set_content('<img src="/definitely-missing.png" alt=x>')
    await session.page.wait_for_timeout(300)
    res = await capture_images()
    assert res["images"][0]["broken"] is True
    assert any("로드 실패" in f for f in res["findings"])


async def test_missing_alt_is_reported(session, shots):
    await session.page.set_content('<img src="/a.png">')
    await session.page.wait_for_timeout(200)
    assert any("alt 없음" in f for f in (await capture_images())["findings"])


async def test_capture_can_be_skipped(session, shots):
    await session.page.set_content('<img src="/a.png" alt=x>')
    res = await capture_images(capture=False)
    assert res["images"][0]["screenshot"] is None
    assert res["images"][0]["src"]
