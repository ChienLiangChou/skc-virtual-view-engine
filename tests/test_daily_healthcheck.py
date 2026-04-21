import unittest

from scripts import daily_healthcheck


class FakeLocator:
    def __init__(self, text):
        self.text = text
        self.clicked = False

    def inner_text(self, timeout=None):
        return self.text

    def click(self, timeout=None):
        self.clicked = True


class FakeFrame:
    def __init__(self, text):
        self._body = FakeLocator(text)

    def locator(self, selector):
        if selector != "body":
            raise AssertionError(f"Unexpected selector: {selector}")
        return self._body


class FakePage:
    def __init__(self, body_text="", frames=None):
        self._body = FakeLocator(body_text)
        self._wake_button = FakeLocator("")
        self.frames = frames or []
        self.wait_calls = []

    def locator(self, selector):
        if selector != "body":
            raise AssertionError(f"Unexpected selector: {selector}")
        return self._body

    def get_by_role(self, role, name=None):
        if role != "button":
            raise AssertionError(f"Unexpected role: {role}")
        if name != daily_healthcheck.WAKE_UP_BUTTON_LABEL:
            raise AssertionError(f"Unexpected button name: {name}")
        return self._wake_button

    def wait_for_timeout(self, milliseconds):
        self.wait_calls.append(milliseconds)


class DailyHealthcheckTests(unittest.TestCase):
    def test_maybe_wake_sleeping_app_clicks_wake_button(self):
        page = FakePage(
            body_text="This app has gone to sleep due to inactivity. Would you like to wake it back up?"
        )

        woke_app = daily_healthcheck.maybe_wake_sleeping_app(page)

        self.assertTrue(woke_app)
        self.assertTrue(page._wake_button.clicked)
        self.assertEqual(page.wait_calls, [5000])

    def test_maybe_wake_sleeping_app_ignores_normal_pages(self):
        page = FakePage(body_text="Healthy app content")

        woke_app = daily_healthcheck.maybe_wake_sleeping_app(page)

        self.assertFalse(woke_app)
        self.assertFalse(page._wake_button.clicked)
        self.assertEqual(page.wait_calls, [])

    def test_find_frame_with_markers_matches_by_content(self):
        page = FakePage(
            frames=[
                FakeFrame("unrelated frame"),
                FakeFrame("互動街景\n互動衛星圖\n目前街景相機距建物約 18 公尺"),
                FakeFrame("Kevin Chou/SKC Realty Team\n定位成功\n建物辨識街景\n定位品質"),
            ]
        )

        main_frame, main_text = daily_healthcheck.find_frame_with_markers(
            page, daily_healthcheck.MAIN_FRAME_MARKERS
        )
        interactive_frame, interactive_text = daily_healthcheck.find_frame_with_markers(
            page, daily_healthcheck.INTERACTIVE_FRAME_MARKERS
        )

        self.assertIs(page.frames[2], main_frame)
        self.assertIn("定位品質", main_text)
        self.assertIs(page.frames[1], interactive_frame)
        self.assertIn("互動衛星圖", interactive_text)


if __name__ == "__main__":
    unittest.main()
