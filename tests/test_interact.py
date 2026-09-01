"""T2.3 / T2.2 — interact actions + D2 chain resolution (CT-04, D2)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.interact import interact
from blackbox_mcp.tools.assertion import assert_


async def test_type_and_click_flow(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    await interact("type", "testid=email", "user@example.com")
    r = await interact("click", "testid=submit")
    assert r["ok"] is True
    assert r["resolved_by"] == "testid"
    # the click handler flips the status text
    assert (await assert_("text_visible", "로그인됨"))["passed"] is True


async def test_chain_resolves_bare_text(session):
    # non-interactive element → no role match → falls through to visible text
    await session.page.set_content("<p>안내 문구</p>")
    r = await interact("click", "안내 문구")   # no prefix -> chain -> text
    assert r["ok"] is True
    assert r["resolved_by"] == "text"


async def test_chain_resolves_role_for_widget(session):
    # a widget with an accessible name resolves via role+name (D2 priority #2),
    # which used to be skipped for bare strings.
    await session.page.set_content("<button>다음</button>")
    r = await interact("click", "다음")
    assert r["ok"] is True
    assert r["resolved_by"] == "role=button"


async def test_chain_prefers_testid(session):
    await session.page.set_content('<button data-testid="go">갈래</button>')
    r = await interact("click", "go")           # bare -> testid match wins
    assert r["ok"] is True
    assert r["resolved_by"] == "testid"


async def test_hover_select_press(session):
    await session.page.set_content(
        "<select data-testid='s'><option value='a'>A</option>"
        "<option value='b'>B</option></select>"
        "<input data-testid='inp'>"
        "<a data-testid='link' href='#'>hi</a>"
    )
    assert (await interact("hover", "testid=link"))["ok"] is True
    assert (await interact("select", "testid=s", "b"))["ok"] is True
    r = await interact("press", "testid=inp", "a")
    assert r["ok"] is True
    assert (await assert_("element_visible", "testid=s"))["passed"] is True


async def test_unknown_action_is_structured(session):
    r = await interact("frobnicate", "testid=x")
    assert r["ok"] is False


async def test_missing_element_returns_error_not_raise(session):
    await session.page.set_content("<p>nothing here</p>")
    r = await interact("click", "testid=nope", None)
    assert r["ok"] is False
    assert "error" in r


_KEY_PAGE = """
<input id="q" placeholder="검색">
<div id="kd">keydown:0</div><div id="inp">input:0</div><div id="sug"></div>
<script>
let n = 0, i = 0;
const q = document.getElementById('q');
q.addEventListener('keydown', () => {
  n++;
  document.getElementById('kd').textContent = 'keydown:' + n;
  document.getElementById('sug').textContent = '자동완성 결과';
});
q.addEventListener('input', () => {
  i++;
  document.getElementById('inp').textContent = 'input:' + i;
});
</script>
"""


async def _counts(session):
    return await session.page.evaluate(
        "() => ({kd: document.getElementById('kd').textContent,"
        "        inp: document.getElementById('inp').textContent})")


async def test_type_fires_no_key_events(session):
    """Documents the sharp edge type_keys exists for: fill() sets the value in
    one shot, so a keydown-driven UI stays inert while the step still passes."""
    await session.page.set_content(_KEY_PAGE)
    r = await interact("type", "#q", "notebook")
    assert r["ok"] is True                       # the step "passes" regardless
    c = await _counts(session)
    assert c["kd"] == "keydown:0"
    assert c["inp"] == "input:1"                 # one bulk input, not per char
    assert (await assert_("text_visible", "자동완성 결과"))["passed"] is False


async def test_type_keys_drives_key_handlers(session):
    await session.page.set_content(_KEY_PAGE)
    r = await interact("type_keys", "#q", "notebook")
    assert r["ok"] is True
    assert r["detail"] == "typed 8 char(s) as key events"
    c = await _counts(session)
    # one keydown per mappable character (the leading clear adds a Delete)
    assert int(c["kd"].split(":")[1]) >= len("notebook")
    assert c["inp"] == "input:8"
    assert (await assert_("text_visible", "자동완성 결과"))["passed"] is True
    assert await session.page.input_value("#q") == "notebook"


async def test_type_keys_sends_cjk_per_character(session):
    """Hangul/CJK has no keyboard mapping, so Playwright inserts it as text:
    no keydown, but `input` still fires PER CHARACTER — which is what a
    debounced search-as-you-type actually listens to. `type` gives it one
    bulk event instead, so type_keys is still the right tool here."""
    await session.page.set_content(_KEY_PAGE)
    await interact("type_keys", "#q", "노트북")
    c = await _counts(session)
    assert c["inp"] == "input:3"
    assert await session.page.input_value("#q") == "노트북"


async def test_type_keys_replaces_existing_value(session):
    """press_sequentially appends; "set this field to X" is what a scenario
    author means, so type_keys clears first — same semantics as type."""
    await session.page.set_content("<input id='q' value='기존값'>")
    await interact("type_keys", "#q", "새값")
    assert await session.page.input_value("#q") == "새값"


async def test_type_keys_requires_a_value(session):
    r = await interact("type_keys", "#q")
    assert r["ok"] is False
    assert "requires a value" in r["error"]
