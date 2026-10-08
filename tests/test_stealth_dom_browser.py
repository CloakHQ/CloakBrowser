"""Real-browser parity tests: humanized actions land on the element Playwright resolves."""

import pytest


_RECORD_CLICKS = """() => {
    window.__clicked = [];
    document.addEventListener('click', (e) => {
        // The innermost element with an id (a click on a button's <span> is the button's).
        const el = e.composedPath().find((n) => n.id);
        window.__clicked.push(el ? el.id : null);
    }, true);
}"""


def _clicked_id(page, selector_or_locator):
    """Click humanized and return the id of the element that received it."""
    page.evaluate("window.__clicked = []")
    if isinstance(selector_or_locator, str):
        page.click(selector_or_locator, timeout=3000)
    else:
        selector_or_locator.click(timeout=3000)
    return page.evaluate("window.__clicked")[-1]


@pytest.mark.slow
def test_text_selector_ignores_hidden_head_script_and_clicks_visible_target():
    """Issue #512: isolated text resolution must agree with Playwright.

    A non-rendered script containing the same text precedes the visible dropdown
    item. Playwright ignores the script; the isolated resolver must select and
    click the same visible ``<li>`` rather than failing its visibility check.
    """
    from cloakbrowser import launch

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.head.innerHTML =
                    '<script id="hidden-copy" type="application/json">["Hoy"]<\\/script>';
                document.body.innerHTML = `
                    <div class="daterangepicker dropdown-menu"
                         style="display:block; position:absolute">
                        <ul><li id="target" class="active">Hoy</li></ul>
                    </div>`;
                window.targetClicks = 0;
                document.querySelector('#target').addEventListener(
                    'click', () => window.targetClicks++
                );
            }"""
        )

        selector = "text=Hoy"
        expected = {"status": "ok", "id": "target", "tag": "LI"}
        playwright_identity = page.locator(selector).first.evaluate(
            "el => ({status: 'ok', id: el.id, tag: el.tagName})"
        )
        assert playwright_identity == expected

        page.click(selector, timeout=3000)
        assert page.evaluate("window.targetClicks") == 1
    finally:
        browser.close()


@pytest.mark.slow
def test_display_contents_uses_rendered_content_geometry():
    """A boxless display:contents target uses its rendered text/child union."""
    from cloakbrowser import launch

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.body.innerHTML = `
                    <ul><li id="target" style="display:contents">Hoy</li></ul>
                    <div id="union" style="display:contents">
                        <span id="left">left</span><span id="right">right</span>
                        <span id="nested" style="display:contents">
                            <span id="nested-child">nested</span>
                        </span>
                        <span id="hidden" style="visibility:hidden;position:absolute;
                              left:1000px;top:1000px;font-size:100px">hidden</span>
                    </div>
                    <div id="hidden-text" style="display:contents;visibility:hidden">
                        hidden text
                    </div>`;
                window.targetClicks = 0;
                window.nestedClicks = 0;
                document.querySelector('#target').addEventListener(
                    'click', () => window.targetClicks++
                );
                document.querySelector('#nested').addEventListener(
                    'click', () => window.nestedClicks++
                );
            }"""
        )

        own_rect = page.evaluate(
            """() => {
                const rect = document.querySelector('#target').getBoundingClientRect();
                return {width: rect.width, height: rect.height};
            }"""
        )
        assert own_rect == {"width": 0, "height": 0}

        page.click("text=Hoy", timeout=3000)
        page.click("#nested", timeout=3000)
        assert page.evaluate("window.targetClicks") == 1
        assert page.evaluate("window.nestedClicks") == 1
    finally:
        browser.close()


@pytest.mark.slow
def test_text_selector_semantics_match_playwright():
    """Text regex, exact fragments, input values, and normalization stay in parity."""
    from cloakbrowser import launch

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.head.innerHTML = '';
                document.body.innerHTML = `
                    <button id="regex-target">Alpha42</button>
                    <button id="nested-target">Hello<span>World</span></button>
                    <input id="value-target" type="button" value="Submit Me">
                    <button id="normalized-target">foo\u200bbar</button>`;
            }"""
        )

        cases = [
            ("text=/^Alpha\\d+$/", "regex-target"),
            ('text="Hello"', "nested-target"),
            ("text=Submit Me", "value-target"),
            ("text=foobar", "normalized-target"),
        ]
        page.evaluate(_RECORD_CLICKS)
        for selector, expected_id in cases:
            assert page.locator(selector).first.evaluate("el => el.id") == expected_id
            assert _clicked_id(page, selector) == expected_id, selector
    finally:
        browser.close()


@pytest.mark.slow
def test_structural_has_text_and_open_shadow_dom_match_playwright():
    """Custom text pseudos keep their compound position and pierce open shadows."""
    from cloakbrowser import launch

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.head.innerHTML = '';
                document.body.innerHTML = `
                    <article>Wanted<button id="correct">Go</button></article>
                    <article>Other<button id="wrong">Wanted</button></article>
                    <div id="shadow-host" style="display:inline-block"></div>`;
                const shadow = document.querySelector('#shadow-host')
                    .attachShadow({mode: 'open'});
                shadow.innerHTML = `
                    <button id="shadow-target">Shadow</button>
                    <input id="shadow-input">`;
                document.body.dataset.shadowClicks = '0';
                document.body.dataset.hostClicks = '0';
                shadow.querySelector('#shadow-target').addEventListener('click', () => {
                    document.body.dataset.shadowClicks = String(
                        Number(document.body.dataset.shadowClicks) + 1
                    );
                });
                document.querySelector('#shadow-host').addEventListener('click', () => {
                    document.body.dataset.hostClicks = String(
                        Number(document.body.dataset.hostClicks) + 1
                    );
                });
            }"""
        )

        cases = [
            ('article:has-text("Wanted") > button', "correct"),
            ("#shadow-target", "shadow-target"),
        ]
        page.evaluate(_RECORD_CLICKS)
        for selector, expected_id in cases:
            assert page.locator(selector).first.evaluate("el => el.id") == expected_id
            assert _clicked_id(page, selector) == expected_id, selector
        assert page._stealth_world.evaluate(
            "document.body.dataset.shadowClicks"
        ) == "1"

        # A shadow host is a composed ancestor of the deep elementFromPoint hit.
        page.click("#shadow-host", timeout=3000)
        assert page._stealth_world.evaluate(
            "document.body.dataset.hostClicks"
        ) == "2"

        page.locator("#shadow-input").focus()
        assert page._stealth_world.evaluate(
            "document.querySelector('#shadow-host').shadowRoot.activeElement.id"
        ) == "shadow-input"
    finally:
        browser.close()


@pytest.mark.slow
def test_mixed_light_and_nested_shadow_order_matches_playwright():
    """Broad selector first/nth order must match Playwright across roots."""
    from cloakbrowser import launch

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.body.innerHTML = `
                    <div id="host-one"></div>
                    <button id="normal-one">Normal one</button>
                    <div id="host-two"></div>
                    <button id="normal-two">Normal two</button>`;
                document.querySelector('#host-one')
                    .attachShadow({mode: 'open'}).innerHTML =
                    '<button id="shadow-one">Shadow one</button>';
                const second = document.querySelector('#host-two')
                    .attachShadow({mode: 'open'});
                second.innerHTML = `
                    <button id="shadow-two">Shadow two</button>
                    <div id="nested-host"></div>`;
                second.querySelector('#nested-host')
                    .attachShadow({mode: 'open'}).innerHTML =
                    '<button id="shadow-nested">Shadow nested</button>';
            }"""
        )

        playwright_ids = page.locator("button").evaluate_all(
            "elements => elements.map(element => element.id)"
        )
        page.evaluate(_RECORD_CLICKS)
        isolated_ids = [
            _clicked_id(page, f"button >> nth={index}")
            for index in range(len(playwright_ids))
        ]

        assert playwright_ids == [
            "normal-one", "normal-two", "shadow-one", "shadow-two",
            "shadow-nested",
        ]
        assert isolated_ids == playwright_ids
    finally:
        browser.close()


@pytest.mark.slow
def test_actionability_state_matches_playwright():
    """Visibility, native disabled, and ARIA readonly semantics stay in parity."""
    from cloakbrowser import launch
    from playwright.sync_api import TimeoutError as PwTimeout

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.body.innerHTML = `
                    <fieldset disabled><input id="fieldset-input"></fieldset>
                    <div role="group" aria-disabled="true">
                        <button id="aria-button">Button</button>
                    </div>
                    <div id="aria-readonly" role="textbox"
                         contenteditable="true" aria-readonly="true">Edit</div>
                    <select><optgroup disabled>
                        <option id="disabled-option">Choice</option>
                    </optgroup></select>
                    <div id="display-contents" style="display:contents">
                        <span>Rendered child</span>
                    </div>
                    <div style="content-visibility:hidden">
                        <button id="content-hidden">Hidden</button>
                    </div>
                    <button id="zero-width"
                            style="width:0;height:30px;padding:0;border:0">X</button>
                    <input id="check-target" type="checkbox">`;
            }"""
        )

        # Humanized actions wait for the same states Playwright does.
        for selector in ("#fieldset-input", "#aria-button", "#content-hidden"):
            with pytest.raises(PwTimeout):
                page.click(selector, timeout=500)
        with pytest.raises(PwTimeout):
            page.fill("#aria-readonly", "x", timeout=500)
        page.click("#display-contents", timeout=3000)

        # Selector check state must come from the same isolated snapshot, not
        # Playwright's page.is_checked DOM read.
        page.is_checked = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("page.is_checked must not be called")
        )
        page.check("#check-target", timeout=3000)
        assert page._stealth_world.evaluate(
            "document.querySelector('#check-target').checked"
        ) is True

        checkbox = page.locator("#check-target")
        checkbox.is_checked = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("locator.is_checked must not be called")
        )
        checkbox.uncheck(timeout=3000)
        assert page._stealth_world.evaluate(
            "document.querySelector('#check-target').checked"
        ) is False
        checkbox.set_checked(True, timeout=3000)
        assert page._stealth_world.evaluate(
            "document.querySelector('#check-target').checked"
        ) is True
    finally:
        browser.close()


@pytest.mark.slow
def test_force_click_keeps_identity_but_skips_coverage_rejection():
    """Force dispatches through a covering element without changing identity."""
    from cloakbrowser import launch

    browser = launch(headless=False, humanize=True, release_channel="preview")
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.body.innerHTML = `
                    <button id="target" style="position:absolute;left:20px;top:20px">
                        Target
                    </button>
                    <div id="cover" style="position:absolute;left:20px;top:20px;
                         width:100px;height:40px;z-index:2"></div>`;
                document.body.dataset.targetClicks = '0';
                document.body.dataset.coverClicks = '0';
                document.querySelector('#target').addEventListener('click', () => {
                    document.body.dataset.targetClicks = String(
                        Number(document.body.dataset.targetClicks) + 1
                    );
                });
                document.querySelector('#cover').addEventListener('click', () => {
                    document.body.dataset.coverClicks = String(
                        Number(document.body.dataset.coverClicks) + 1
                    );
                });
            }"""
        )

        page.click("#target", force=True, timeout=3000)
        counts = page._stealth_world.evaluate(
            """(() => ({
                target: document.body.dataset.targetClicks,
                cover: document.body.dataset.coverClicks,
            }))()"""
        )
        assert counts == {"target": "0", "cover": "1"}
    finally:
        browser.close()


@pytest.mark.slow
@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize("mutation", ["remove", "replace"])
def test_click_rejects_target_mutation_after_mouse_movement(
    monkeypatch, force, mutation,
):
    """Never dispatch to an underlying/stale target after movement.

    The page swaps the target while the cursor travels. The press must not
    land on what is under the cursor now: a removed target times out; a
    replaced target is re-resolved and reached with a fresh move, exactly
    like Playwright re-resolves locators.
    """
    from cloakbrowser import launch
    from cloakbrowser.human.engine import Human
    from playwright.sync_api import TimeoutError as PwTimeout

    browser = launch(headless=True, humanize=True)
    try:
        page = browser.new_page()
        page.evaluate("""() => {
            document.body.innerHTML = `
              <button id="underlying" style="position:absolute;left:20px;top:20px">Underlying</button>
              <button id="target" style="position:absolute;left:20px;top:20px">Original</button>`;
            window.counts = {underlying: 0, replacement: 0};
            document.querySelector('#underlying').onclick = () => counts.underlying++;
        }""")
        real_move = Human.move_to
        state = {"mutated": False}

        async def mutate_during_move(self, x, y, cfg):
            await real_move(self, x, y, cfg)
            if state["mutated"]:
                return
            state["mutated"] = True
            # Mutate from the page's own world, like a real page script would.
            await self.page.main_frame.evaluate("""(mutation) => {
                const old = document.querySelector('#target');
                if (mutation === 'remove') { old.remove(); return; }
                const r = document.createElement('button');
                r.id = 'target'; r.textContent = 'Replacement'; r.style.cssText = old.style.cssText;
                r.onclick = () => counts.replacement++;
                old.replaceWith(r);
            }""", mutation)

        monkeypatch.setattr(Human, "move_to", mutate_during_move)
        if mutation == "remove":
            with pytest.raises(PwTimeout):
                page.click("#target", force=force, timeout=1500)
        else:
            page.click("#target", force=force, timeout=3000)
        counts = page.evaluate("counts")
        assert counts["underlying"] == 0
        assert counts["replacement"] == (1 if mutation == "replace" else 0)
    finally:
        browser.close()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_async_click_rejects_replacement_after_mouse_movement(monkeypatch):
    """Async: an ElementHandle whose element is replaced mid-move must fail
    (handles are not re-resolved), and nothing is clicked."""
    from cloakbrowser import launch_async
    from cloakbrowser.human.engine import Human
    from playwright.async_api import Error as PwError

    browser = await launch_async(headless=True, humanize=True)
    try:
        page = await browser.new_page()
        await page.evaluate("""() => {
            document.body.innerHTML = '<button id="target">Original</button>';
            window.clicks = 0; document.addEventListener('click', () => clicks++, true);
        }""")
        handle = await page.query_selector("#target")
        real_move = Human.move_to

        async def replace_during_move(self, x, y, cfg):
            await real_move(self, x, y, cfg)
            await self.worlds.evaluate(self.page.main_frame, """(() => {
                const old = document.querySelector('#target');
                const r = document.createElement('button'); r.id = 'target'; r.textContent = 'Replacement';
                old.replaceWith(r);
            })()""")

        monkeypatch.setattr(Human, "move_to", replace_during_move)
        with pytest.raises(PwError, match="not attached"):
            await handle.click(force=True, timeout=1000)
        assert await page.evaluate("clicks") == 0
    finally:
        await browser.close()


@pytest.mark.slow
def test_get_by_engines_match_playwright():
    """The reimplemented ``internal:*`` engines must resolve the SAME element
    Playwright's own locator resolves.

    Under-matching yields a typed error; over-matching silently clicks the wrong
    coordinates. Every case below is one where a plausible-but-wrong shortcut
    diverges from Playwright:

      * ``get_by_test_id`` is strict equality, so "submit" must NOT match
        "submit-button", while ``get_by_placeholder``'s ``i`` flag is a
        case-insensitive SUBSTRING, so "mail" MUST match "Your Email".
      * attribute values are compared raw, so a padded ``title`` does not match
        its trimmed form.
      * ``internal:text`` exact compares the full normalized subtree text, unlike
        the public ``text=`` engine which compares immediate fragments.
      * ``<br>`` contributes nothing and shadow-root text is concatenated into
        the host's text (both are ``__elementText`` parity fixes).
      * label resolution order is aria-labelledby, aria-label, then ``.labels``,
        with an unresolvable ``aria-labelledby`` falling through.
    """
    import re

    from cloakbrowser import launch

    browser = launch(headless=True, humanize=True, geoip=False)
    try:
        page = browser.new_page()
        page.goto("https://example.com", wait_until="domcontentloaded")
        page.evaluate(
            """() => {
                document.head.innerHTML = '';
                document.body.innerHTML = `
                    <button id="b1" data-testid="submit-button">Go</button>
                    <button id="b2" data-testid="submit">Go Now</button>
                    <input id="p1" placeholder="Your Email">
                    <img id="a1" alt="Company Logo">
                    <span id="t1" title="  Go  ">titled</span>
                    <button id="b3">Hello<span>World</span></button>
                    <div id="brdiv">a<br>b</div>
                    <div id="gp">X<section><span id="deep">X</span></section></div>
                    <label for="in1">Password</label><input id="in1">
                    <label>Wrapped<input id="in2"></label>
                    <input id="in3" aria-label="Aria Labelled">
                    <span id="lbref">Referenced Label</span>
                    <input id="in4" aria-labelledby="lbref">
                    <input id="in5" aria-labelledby="missing-id" aria-label="Fallback Label">
                    <div id="host"></div>`;
                document.getElementById('host')
                    .attachShadow({mode: 'open'}).innerHTML =
                    '<button id="shadowbtn">DeepShadow</button>';
            }"""
        )

        cases = [
            (page.get_by_test_id("submit"), "b2"),
            (page.get_by_test_id("submit-button"), "b1"),
            (page.get_by_placeholder("mail"), "p1"),
            (page.get_by_placeholder("Your Email", exact=True), "p1"),
            (page.get_by_alt_text("Company Logo"), "a1"),
            (page.get_by_title("Go"), "t1"),
            (page.get_by_text("Go Now"), "b2"),
            (page.get_by_text("HelloWorld", exact=True), "b3"),
            (page.get_by_text("X", exact=True), "deep"),
            (page.get_by_text("ab", exact=True), "brdiv"),
            (page.get_by_text("DeepShadow"), "shadowbtn"),
            (page.get_by_text(re.compile(r"^Go Now$")), "b2"),
            (page.get_by_label("Password"), "in1"),
            (page.get_by_label("Wrapped"), "in2"),
            (page.get_by_label("Aria Labelled"), "in3"),
            (page.get_by_label("Referenced Label"), "in4"),
            (page.get_by_label("Fallback Label"), "in5"),
        ]
        page.evaluate(_RECORD_CLICKS)
        for locator, expected_id in cases:
            selector = locator._impl_obj._selector
            assert locator.first.evaluate("el => el.id") == expected_id, selector
            assert _clicked_id(page, locator.first) == expected_id, selector

        # A strict test id must not match by prefix, and a raw attribute value is
        # never trimmed -- both would be silent over-matches.
        assert page.get_by_test_id("submit").count() == 1
        assert page.get_by_title("Go", exact=True).count() == 0

        # get_by_role resolves through Playwright's own engine as well.
        assert _clicked_id(page, page.get_by_role("button", name="Go Now")) == "b2"
    finally:
        browser.close()
