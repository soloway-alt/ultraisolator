import json
import re
import struct
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANDING_PAGE = ROOT / "docs" / "index.html"
STYLESHEET = ROOT / "docs" / "site.css"
BENCHMARK_SOURCE = ROOT / "docs" / "benchmarks" / "cs2-vprof-summary.json"
SOCIAL_PREVIEW_SVG = ROOT / "docs" / "social-preview.svg"
SOCIAL_PREVIEW_PNG = ROOT / "docs" / "social-preview.png"
REPOSITORY_URL = "https://github.com/chezzof/ultraisolator"
RELEASE_URL = f"{REPOSITORY_URL}/releases/latest"


class LandingPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.images = []
        self.tags = []
        self.html_language = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append(tag)
        if "id" in attributes:
            self.ids.add(attributes["id"])
        if tag == "html":
            self.html_language = attributes.get("lang")
        elif tag == "a":
            self.links.append(attributes.get("href"))
        elif tag == "img":
            self.images.append(attributes)


class LandingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = LANDING_PAGE.read_text(encoding="utf-8")
        cls.css = STYLESHEET.read_text(encoding="utf-8")
        cls.parser = LandingPageParser()
        cls.parser.feed(cls.html)

    def test_static_landing_assets_exist(self):
        self.assertTrue(LANDING_PAGE.is_file())
        self.assertTrue(STYLESHEET.is_file())
        self.assertIn('href="site.css?v=responsive-images"', self.html)
        self.assertIn('href="assets/icon.png"', self.html)
        self.assertTrue((LANDING_PAGE.parent / "assets" / "icon.png").is_file())

    def test_has_semantic_page_structure_and_language(self):
        self.assertEqual(self.parser.html_language, "en")
        for tag in ("header", "nav", "main", "section", "footer"):
            self.assertIn(tag, self.parser.tags)
        self.assertIn('href="#main-content"', self.html)
        self.assertIn('name="viewport"', self.html)

    def test_required_content_sections_are_present(self):
        expected_ids = {
            "main-content",
            "top",
            "workflow",
            "product",
            "benchmark",
            "safety",
            "faq",
        }
        self.assertTrue(expected_ids.issubset(self.parser.ids))
        for phrase in ("Detect", "Review", "Isolate", "Restore"):
            self.assertIn(f">{phrase}<", self.html)

    def test_download_and_repository_ctas_use_canonical_urls(self):
        self.assertGreaterEqual(self.parser.links.count(RELEASE_URL), 3)
        self.assertGreaterEqual(self.parser.links.count(REPOSITORY_URL), 3)
        self.assertNotIn("leggapattern01-dot", self.html)

    def test_product_tour_uses_real_repository_screenshots(self):
        sources = [image.get("src", "").split("?", 1)[0] for image in self.parser.images]
        for filename in ("dashboard.png", "topology.png", "settings.png"):
            source = f"screenshots/{filename}"
            self.assertIn(source, sources)
            self.assertTrue((ROOT / "docs" / source).is_file())

        for image in self.parser.images:
            self.assertIn("alt", image)
            self.assertNotIn("placeholder", image.get("src", "").lower())
            source = image.get("src", "").split("?", 1)[0]
            if source and not source.startswith(("http://", "https://", "data:")):
                self.assertTrue((LANDING_PAGE.parent / source).is_file(), source)

    def test_benchmark_claims_match_the_structured_source_and_include_caveat(self):
        benchmark = json.loads(BENCHMARK_SOURCE.read_text(encoding="utf-8"))
        headline = benchmark["headline"]
        for key in (
            "frame_total_p95_spike_without_ms",
            "frame_total_p95_spike_with_ms",
            "client_rendering_p95_spike_without_ms",
            "client_rendering_p95_spike_with_ms",
        ):
            self.assertIn(f'{headline[key]:.2f} ms', self.html)
        methodology = " ".join(benchmark["methodology"]["notes"])
        self.assertIn("workload-specific", methodology)
        self.assertIn("should be reproduced on target hardware", methodology)
        self.assertIn("workload-specific", self.html)
        self.assertIn("should be reproduced on your hardware", self.html)
        self.assertIn("benchmarks/cs2-vprof-summary.json", self.html)

    def test_copy_does_not_invent_accounts_or_guaranteed_gains(self):
        normalized = re.sub(r"\s+", " ", self.html.lower())
        self.assertNotIn("sign in", normalized)
        self.assertNotIn("log in", normalized)
        self.assertNotIn("create account", normalized)
        self.assertNotIn("guaranteed fps", normalized)
        self.assertIn("does ultraisolator guarantee more fps?", normalized)
        self.assertIn("<p> no.", normalized)

    def test_social_preview_matches_the_premium_brand_without_fake_metrics(self):
        preview = SOCIAL_PREVIEW_SVG.read_text(encoding="utf-8")
        self.assertIn("UltraIsolator", preview)
        self.assertIn("PROTECT", preview)
        self.assertIn("screenshots/dashboard.png", preview)
        for stale_claim in ("ESPORTS ISOLATOR", "+9.8%", "P95 SPIKE", "PROCS JAILED"):
            self.assertNotIn(stale_claim, preview)

        with SOCIAL_PREVIEW_PNG.open("rb") as image:
            self.assertEqual(image.read(8), b"\x89PNG\r\n\x1a\n")
            length = struct.unpack(">I", image.read(4))[0]
            self.assertEqual(image.read(4), b"IHDR")
            width, height = struct.unpack(">II", image.read(8))
        self.assertEqual(length, 13)
        self.assertEqual((width, height), (1280, 640))

    def test_styles_are_responsive_accessible_and_use_no_gradients(self):
        self.assertIn("@media (max-width: 540px)", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertRegex(self.css, r"img\s*\{[^}]*height:\s*auto;")
        self.assertNotIn("gradient(", self.css.lower())
        self.assertNotIn("<svg", self.html.lower())


if __name__ == "__main__":
    unittest.main()
