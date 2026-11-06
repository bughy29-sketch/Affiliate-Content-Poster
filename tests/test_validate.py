import unittest

from src.config import Config
from src.validate import build_description, detect_affiliate, validate_pin


def make_config(**overrides):
    values = dict(
        client_id="",
        client_secret="",
        refresh_token="",
        default_board_id="123456789",
        dry_run=True,
        max_pins_per_run=1,
        min_delay_seconds=0,
        max_delay_seconds=0,
        disclosure="Conține linkuri de afiliere.",
        queue_path="data/queue.json",
        state_path="data/state.json",
    )
    values.update(overrides)
    return Config(**values)


def make_pin(**overrides):
    pin = {
        "id": "test-1",
        "title": "Titlu valid",
        "description": "Descriere validă.",
        "link": "https://profitshare.ro/l/abc",
        "image_url": "https://cdn.example.com/img.jpg",
        "affiliate": "emag",
    }
    pin.update(overrides)
    return pin


class ValidatePinTests(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_valid_pin_passes(self):
        result = validate_pin(make_pin(), self.config)
        self.assertTrue(result.ok, result.errors)

    def test_amazon_requires_tag(self):
        pin = make_pin(affiliate="amazon", link="https://www.amazon.de/dp/B000")
        result = validate_pin(pin, self.config)
        self.assertFalse(result.ok)
        self.assertTrue(any("tag" in error for error in result.errors))

    def test_amazon_with_tag_passes(self):
        pin = make_pin(
            affiliate="amazon",
            link="https://www.amazon.de/dp/B000?tag=mysite-21",
        )
        result = validate_pin(pin, self.config)
        self.assertTrue(result.ok, result.errors)

    def test_shortener_rejected(self):
        result = validate_pin(make_pin(link="https://bit.ly/abc"), self.config)
        self.assertFalse(result.ok)

    def test_title_too_long(self):
        result = validate_pin(make_pin(title="x" * 101), self.config)
        self.assertFalse(result.ok)

    def test_https_required(self):
        result = validate_pin(make_pin(link="http://profitshare.ro/l/abc"), self.config)
        self.assertFalse(result.ok)

    def test_disclosure_added(self):
        description = build_description(make_pin(), self.config)
        self.assertIn("Conține linkuri de afiliere.", description)

    def test_disclosure_not_duplicated(self):
        pin = make_pin(description="Text. Conține linkuri de afiliere.")
        description = build_description(pin, self.config)
        self.assertEqual(description.lower().count("conține linkuri de afiliere"), 1)

    def test_detect_amazon(self):
        self.assertEqual(detect_affiliate("https://amzn.to/abc"), "amazon")
        self.assertEqual(
            detect_affiliate("https://www.amazon.com/dp/x?tag=a-20"), "amazon"
        )

    def test_detect_emag(self):
        self.assertEqual(
            detect_affiliate("https://profitshare.ro/l/abc"), "emag"
        )

    def test_emag_warning_for_non_profitshare(self):
        result = validate_pin(make_pin(link="https://www.emag.ro/produs"), self.config)
        self.assertTrue(result.ok, result.errors)
        self.assertTrue(any("profitshare" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
