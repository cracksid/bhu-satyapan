"""Screenshot the HTML page with a headless browser.

Chromium does the Devanagari shaping for us, which is the whole reason we
render through a browser instead of drawing the text with Pillow. Pillow can
only shape correctly when an extra library happens to be installed; a browser
always gets क्षेत्र, वर्ग-२ and हिस्सा right.
"""

from playwright.sync_api import sync_playwright


class SheetRenderer:
    """Keeps ONE browser open and turns HTML into PNG bytes.

    Starting a browser takes about a second, so we start it once and reuse it
    for every record:

        with SheetRenderer() as renderer:
            png_bytes = renderer.render(html)
    """

    def __init__(self, width: int = 1000, scale: float = 2.0):
        self.width = width
        # scale 2.0 means the saved image is twice the CSS size (about 2000 px
        # wide), which gives Tesseract enough detail on Devanagari letters.
        self.scale = scale
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch()
            self._page = self._browser.new_page(
                viewport={"width": self.width, "height": 1400},
                device_scale_factor=self.scale,
            )
        except Exception:
            self._playwright.stop()
            raise
        return self

    def render(self, page_html: str) -> bytes:
        """HTML in, PNG bytes of the #sheet element out."""
        self._page.set_content(page_html, wait_until="load")
        sheet = self._page.query_selector("#sheet")
        if sheet is None:
            raise RuntimeError("the page has no #sheet element to screenshot")
        return sheet.screenshot(type="png")

    def __exit__(self, *exc_info):
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
