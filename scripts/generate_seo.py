#!/usr/bin/env python3
"""Generate SEO metadata, social preview cards, and a sitemap for the writing hub.

Discovers index.html plus published HTML pages under research/ and notes/.
Research/note titles come from <h1>; descriptions come from .subtitle, or from
that page's first paragraph in .publication-body. Article wording is preserved;
the generator changes only em-dash punctuation.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://njugunasam.co.ke"
PERSON_ID = SITE + "/#person"
PERSON_IMAGE = SITE + "/images/njuguna-ngugi.png"
SOCIAL_DIR = ROOT / "images" / "social"
SIGNATURE_SOURCE = ROOT / "images" / "signature-source.jpg"
EM_DASH = chr(0x2014)
EM_DASH_ENTITY = re.compile(r"&(?:mdash|#0*8212|#x0*2014);", re.I)


def normalize_em_dashes(value: str) -> str:
    return EM_DASH_ENTITY.sub("-", value.replace(EM_DASH, "-"))


def contains_em_dash(value: str) -> bool:
    return EM_DASH in value or bool(EM_DASH_ENTITY.search(value))


@dataclass(frozen=True)
class Page:
    path: Path
    relative: str
    html_title: str
    title: str
    description: str
    category: str
    section: str
    schema_type: str
    image_name: str
    image_alt: str
    home: bool = False

    @property
    def canonical(self) -> str:
        return SITE + ("/" if self.relative == "index.html" else "/" + self.relative)

    @property
    def image_url(self) -> str:
        return SITE + "/images/social/" + self.image_name


class ContentExtractor(HTMLParser):
    """Extract only a page heading and a short summary candidate."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.capture: tuple[str, str, list[str]] | None = None
        self.heading = ""
        self.subtitle = ""
        self.first_paragraph = ""

    def _inside_publication_body(self) -> bool:
        return any(is_publication for _, is_publication in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        is_publication = "publication-body" in attributes.get("class", "").split()
        self.stack.append((tag, is_publication))
        if self.capture is None:
            if tag.lower() == "h1" and not self.heading:
                self.capture = ("h1", "heading", [])
            elif tag.lower() == "p" and "subtitle" in attributes.get("class", "").split():
                self.capture = ("p", "subtitle", [])
            elif tag.lower() == "p" and self._inside_publication_body() and not self.first_paragraph:
                self.capture = ("p", "paragraph", [])

    def handle_data(self, data: str) -> None:
        if self.capture is not None:
            self.capture[2].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture is not None and tag.lower() == self.capture[0]:
            _, purpose, chunks = self.capture
            text = compact("".join(chunks))
            if purpose == "heading" and not self.heading:
                self.heading = text
            elif purpose == "subtitle" and not self.subtitle:
                self.subtitle = text
            elif purpose == "paragraph" and not self.first_paragraph:
                self.first_paragraph = text
            self.capture = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag.lower():
                del self.stack[index:]
                break


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", normalize_em_dashes(value)).strip()


def shorten(value: str, limit: int = 160) -> str:
    value = compact(value)
    if len(value) <= limit:
        return value
    first_sentence = re.search(r"[.!?](?:\s|$)", value)
    if first_sentence and first_sentence.end() <= limit:
        return value[: first_sentence.end()].strip()
    cut = value[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def page_paths() -> list[Path]:
    paths = [ROOT / "index.html"]
    for folder in (ROOT / "research", ROOT / "notes"):
        if folder.exists():
            paths.extend(sorted(folder.rglob("*.html")))
    return paths


def normalize_site_punctuation() -> None:
    changed = 0
    for path in page_paths():
        source = path.read_text(encoding="utf-8")
        normalized = normalize_em_dashes(source)
        if normalized != source:
            path.write_text(normalized, encoding="utf-8")
            changed += 1
    if changed:
        print(f"Replaced em dashes with hyphens in {changed} page(s).")


def describe_page(path: Path) -> Page:
    relative = path.relative_to(ROOT).as_posix()
    if relative == "index.html":
        return Page(
            path=path,
            relative=relative,
            html_title="Njuguna Ngugi | Founder & CEO of Trendify Labs",
            title="Njuguna Ngugi | Founder & CEO of Trendify Labs",
            description=(
                "Njuguna Ngugi is Founder and CEO of Trendify Labs. Read his writing on "
                "artificial intelligence, African development, public finance and technology."
            ),
            category="Profile",
            section="Profile",
            schema_type="ProfilePage",
            image_name="home.png",
            image_alt="Handwritten signature of Njuguna Ngugi",
            home=True,
        )

    source = path.read_text(encoding="utf-8")
    parser = ContentExtractor()
    parser.feed(source)
    if not parser.heading:
        raise ValueError(f"Missing <h1> in published writing page: {relative}")
    description = shorten(parser.subtitle or parser.first_paragraph)
    if not description:
        raise ValueError(f"Could not derive a description for: {relative}")

    is_note = relative.startswith("notes/")
    category = "Short note" if is_note else "Research"
    section = "Short notes" if is_note else "Research"
    slug = re.sub(r"[^a-z0-9-]+", "-", relative[:-5].lower()).strip("-").replace("/", "-")
    return Page(
        path=path,
        relative=relative,
        html_title=f"{parser.heading} - Njuguna Ngugi",
        title=parser.heading,
        description=description,
        category=category,
        section=section,
        schema_type="BlogPosting" if is_note else "Article",
        image_name=f"{slug}.png",
        image_alt=f"Social preview for {parser.heading} by Njuguna Ngugi",
    )


def meta(attribute: str, name: str, content: str) -> str:
    return f'  <meta {attribute}="{escape(name, quote=True)}" content="{escape(content, quote=True)}">'


def json_script(data: dict) -> str:
    serialized = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return '  <script type="application/ld+json">\n' + serialized + "\n  </script>"


def page_metadata(page: Page) -> str:
    lines = [
        f"  <title>{escape(page.html_title)}</title>",
        meta("name", "description", page.description),
        meta("name", "author", "Njuguna Ngugi"),
        meta("name", "robots", "index, follow, max-image-preview:large"),
        f'  <link rel="canonical" href="{escape(page.canonical, quote=True)}">',
        meta("property", "og:type", "profile" if page.home else "article"),
        meta("property", "og:site_name", "Njuguna Ngugi"),
        meta("property", "og:title", page.title),
        meta("property", "og:description", page.description),
        meta("property", "og:url", page.canonical),
        meta("property", "og:image", page.image_url),
        meta("property", "og:image:secure_url", page.image_url),
        meta("property", "og:image:type", "image/png"),
        meta("property", "og:image:width", "1200"),
        meta("property", "og:image:height", "630"),
        meta("property", "og:image:alt", page.image_alt),
    ]
    if page.home:
        lines += [
            meta("property", "profile:first_name", "Njuguna"),
            meta("property", "profile:last_name", "Ngugi"),
            json_script({
                "@context": "https://schema.org",
                "@type": "Person",
                "@id": PERSON_ID,
                "name": "Njuguna Ngugi",
                "url": SITE + "/",
                "image": PERSON_IMAGE,
                "jobTitle": "Founder and Chief Executive Officer",
                "description": page.description,
                "worksFor": {
                    "@type": "Organization",
                    "@id": "https://tiff.co.ke/#organization",
                    "name": "Trendify Labs",
                    "url": "https://tiff.co.ke/",
                },
                "sameAs": ["https://www.linkedin.com/in/njuguna-ngugi-034176348"],
            }),
            json_script({
                "@context": "https://schema.org",
                "@type": "ProfilePage",
                "@id": SITE + "/#profile",
                "url": SITE + "/",
                "name": page.html_title,
                "primaryImageOfPage": PERSON_IMAGE,
                "isPartOf": {"@id": SITE + "/#website"},
                "mainEntity": {"@id": PERSON_ID},
            }),
            json_script({
                "@context": "https://schema.org",
                "@type": "WebSite",
                "@id": SITE + "/#website",
                "url": SITE + "/",
                "name": "Njuguna Ngugi",
                "description": page.description,
                "publisher": {"@id": PERSON_ID},
                "inLanguage": "en",
            }),
        ]
    else:
        lines += [
            meta("property", "article:section", page.section),
            meta("name", "twitter:card", "summary_large_image"),
            meta("name", "twitter:title", page.title),
            meta("name", "twitter:description", page.description),
            meta("name", "twitter:image", page.image_url),
            meta("name", "twitter:image:alt", page.image_alt),
            json_script({
                "@context": "https://schema.org",
                "@type": page.schema_type,
                "mainEntityOfPage": {"@type": "WebPage", "@id": page.canonical},
                "headline": page.title,
                "description": page.description,
                "image": page.image_url,
                "author": {"@type": "Person", "@id": PERSON_ID, "name": "Njuguna Ngugi", "url": SITE + "/"},
                "publisher": {"@id": PERSON_ID},
                "articleSection": page.section,
                "inLanguage": "en",
            }),
        ]
    if page.home:
        lines += [
            meta("name", "twitter:card", "summary_large_image"),
            meta("name", "twitter:title", page.title),
            meta("name", "twitter:description", page.description),
            meta("name", "twitter:image", page.image_url),
            meta("name", "twitter:image:alt", page.image_alt),
        ]
    return "\n".join(lines)


SEO_NAMES = {
    "description", "author", "robots", "twitter:card", "twitter:title",
    "twitter:description", "twitter:image", "twitter:image:alt",
}


def attrs(tag: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag):
        result[match.group(1).lower()] = next(group for group in match.groups()[1:] if group is not None)
    return result


def strip_old_metadata(head: str) -> str:
    head = re.sub(r"<title\b[^>]*>.*?</title\s*>", "", head, flags=re.I | re.S)
    head = re.sub(r"<script\b(?=[^>]*\btype\s*=\s*(['\"])application/ld\+json\1)[^>]*>.*?</script\s*>", "", head, flags=re.I | re.S)

    def remove_meta(match: re.Match[str]) -> str:
        tag = match.group(0)
        attributes = attrs(tag)
        name = attributes.get("name", "").lower()
        prop = attributes.get("property", "").lower()
        if name in SEO_NAMES or name.startswith("twitter:") or prop.startswith(("og:", "profile:", "article:")):
            return ""
        return tag

    head = re.sub(r"<meta\b[^>]*>", remove_meta, head, flags=re.I | re.S)

    def remove_canonical(match: re.Match[str]) -> str:
        return "" if attrs(match.group(0)).get("rel", "").lower() == "canonical" else match.group(0)

    head = re.sub(r"<link\b[^>]*>", remove_canonical, head, flags=re.I | re.S)
    return head


def replace_head(source: str, metadata: str, relative: str) -> str:
    match = re.search(r"(<head\b[^>]*>)(.*?)(</head\s*>)", source, flags=re.I | re.S)
    if not match:
        raise ValueError(f"Missing <head> in {relative}")
    head = strip_old_metadata(match.group(2))
    style = re.search(r"<style\b", head, flags=re.I)
    script = re.search(r"<script\b", head, flags=re.I)
    candidates = [item.start() for item in (style, script) if item]
    insertion = min(candidates) if candidates else len(head)
    before, after = head[:insertion].rstrip(), head[insertion:].lstrip()
    rebuilt = before + "\n" + metadata + ("\n" + after if after else "\n")
    return source[:match.start()] + match.group(1) + rebuilt + match.group(3) + source[match.end():]


def card_html(page: Page) -> str:
    if page.home:
        if not SIGNATURE_SOURCE.is_file():
            raise FileNotFoundError(f"Missing handwritten signature source: {SIGNATURE_SOURCE}")
        signature = base64.b64encode(SIGNATURE_SOURCE.read_bytes()).decode("ascii")
        return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
* {{ box-sizing:border-box; }}
html,body {{ width:1200px; height:630px; margin:0; }}
body {{ background:#f2f0e6; }}
.card {{ width:1200px; height:630px; border:1px solid #c9c7bd; display:flex; align-items:center; justify-content:center; overflow:hidden; background:#f2f0e6; }}
.signature {{ display:block; width:942px; height:628px; max-width:100%; max-height:100%; object-fit:contain; }}
</style></head><body><div class="card"><img class="signature" src="data:image/jpeg;base64,{signature}" alt="Handwritten signature of Njuguna Ngugi"></div></body></html>'''

    title = escape(page.title)
    subtitle = escape(page.description)
    category = escape(page.category.upper())
    brand = "Njuguna Ngugi"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>
* {{ box-sizing:border-box; }}
html,body {{ width:1200px; height:630px; margin:0; }}
body {{ background:#f2f0e6; color:#211f1b; font-family:Arial,Helvetica,sans-serif; }}
.card {{ width:1200px; height:630px; padding:48px 72px 38px; border:1px solid #c9c7bd; display:flex; flex-direction:column; overflow:hidden; position:relative; background:#f2f0e6; }}
.card::before {{ content:""; position:absolute; inset:0 auto 0 0; width:12px; background:#744b3d; }}
header {{ display:flex; align-items:center; justify-content:space-between; gap:24px; padding:0 22px 17px; border-bottom:1px solid #c9c7bd; }}
.brand {{ font:700 20px/1.2 Georgia,"Times New Roman",serif; letter-spacing:-.02em; }}
.category {{ color:#744b3d; font:700 13px/1.2 Arial,Helvetica,sans-serif; letter-spacing:.16em; }}
main {{ flex:1; display:flex; flex-direction:column; justify-content:center; padding:0 22px; }}
.rule {{ width:76px; height:4px; margin:0 0 23px; background:#744b3d; }}
h1 {{ max-width:980px; margin:0; font:500 58px/1.1 Georgia,"Times New Roman",serif; letter-spacing:-.035em; }}
.subtitle {{ max-width:950px; margin:23px 0 0; color:#59574f; font:21px/1.45 Arial,Helvetica,sans-serif; }}
footer {{ padding:15px 22px 0; border-top:1px solid #c9c7bd; color:#59574f; font:14px/1.3 Arial,Helvetica,sans-serif; letter-spacing:.04em; }}
</style></head><body><div class="card" role="img" aria-label="{escape(page.image_alt, quote=True)}">
<header><span class="brand">{brand}</span><span class="category">{category}</span></header>
<main><div class="rule"></div><h1>{title}</h1><p class="subtitle">{subtitle}</p></main>
<footer>njugunasam.co.ke</footer></div></body></html>'''


def render_cards(pages: list[Page]) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required to render social cards; install it with `python3 -m pip install playwright` and `python3 -m playwright install chromium`.") from exc

    SOCIAL_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        executable = Path("/usr/bin/chromium")
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(executable) if executable.exists() else None,
            args=["--no-sandbox"],
        )
        try:
            page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
            for item in pages:
                page.set_content(card_html(item), wait_until="load")
                page.wait_for_function("document.fonts.status === 'loaded'")
                card = page.locator(".card")
                dimensions = card.evaluate("el => ({width:el.offsetWidth,height:el.offsetHeight,scrollHeight:el.scrollHeight})")
                if dimensions["width"] != 1200 or dimensions["height"] != 630 or dimensions["scrollHeight"] > 630:
                    raise RuntimeError(f"Unexpected social-card dimensions for {item.relative}: {dimensions}")
                card.screenshot(path=str(SOCIAL_DIR / item.image_name), animations="disabled")
                print(f"Rendered {item.image_name}: 1200x630")
        finally:
            browser.close()


def write_sitemap(pages: list[Page]) -> None:
    contents = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]
    for page in pages:
        contents.append(f"  <url><loc>{escape(page.canonical)}</loc>")
        if page.home:
            contents.append(f"    <image:image><image:loc>{escape(PERSON_IMAGE)}</image:loc></image:image>")
        contents.append("  </url>")
    contents.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(contents) + "\n", encoding="utf-8")


def check(pages: list[Page]) -> None:
    failures: list[str] = []
    for page in pages:
        source = page.path.read_text(encoding="utf-8")
        if contains_em_dash(source):
            failures.append(f"{page.relative}: still contains an em dash")
        for token in (
            f'<link rel="canonical" href="{page.canonical}">',
            f'<meta property="og:image" content="{page.image_url}">',
            '<meta name="twitter:card" content="summary_large_image">',
            '<script type="application/ld+json">',
        ):
            if token not in source:
                failures.append(f"{page.relative}: missing {token}")
        image = SOCIAL_DIR / page.image_name
        if not image.is_file():
            failures.append(f"{page.relative}: missing social image {image.relative_to(ROOT)}")
        else:
            with image.open("rb") as handle:
                header = handle.read(24)
            if header[:8] != b"\x89PNG\r\n\x1a\n" or int.from_bytes(header[16:20], "big") != 1200 or int.from_bytes(header[20:24], "big") != 630:
                failures.append(f"{page.relative}: social image is not a 1200x630 PNG")
        if page.home:
            for token in (
                f'"image": "{PERSON_IMAGE}"',
                f'"primaryImageOfPage": "{PERSON_IMAGE}"',
                f'<meta property="og:image" content="{page.image_url}">',
                f'<meta name="twitter:image" content="{page.image_url}">',
            ):
                if token not in source:
                    failures.append(f"{page.relative}: missing homepage portrait/preview token {token}")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    if contains_em_dash(sitemap):
        failures.append("sitemap.xml: still contains an em dash")
    if not SIGNATURE_SOURCE.is_file():
        failures.append("missing handwritten signature source image")
    if not (ROOT / "images" / "njuguna-ngugi.png").is_file():
        failures.append("missing public portrait image")
    if f"<image:loc>{PERSON_IMAGE}</image:loc>" not in sitemap:
        failures.append("sitemap.xml: missing homepage portrait image URL")
    for page in pages:
        if f"<loc>{page.canonical}</loc>" not in sitemap:
            failures.append(f"sitemap.xml: missing {page.canonical}")
    if failures:
        raise RuntimeError("SEO validation failed:\n- " + "\n- ".join(failures))
    print(f"SEO validation passed for {len(pages)} pages and {len(pages)} social cards.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate generated metadata, cards, and sitemap without changing files")
    args = parser.parse_args()
    if not args.check:
        normalize_site_punctuation()
    pages = [describe_page(path) for path in page_paths()]
    if args.check:
        check(pages)
        return 0

    body_snapshots: dict[str, str] = {}
    for item in pages:
        content = item.path.read_text(encoding="utf-8")
        end_head = re.search(r"</head\s*>", content, flags=re.I)
        if not end_head:
            raise ValueError(f"Missing </head> in {item.relative}")
        body_snapshots[item.relative] = content[end_head.end():]

    render_cards(pages)
    for item in pages:
        original = item.path.read_text(encoding="utf-8")
        updated = replace_head(original, page_metadata(item), item.relative)
        item.path.write_text(updated, encoding="utf-8")
        new_head_end = re.search(r"</head\s*>", updated, flags=re.I)
        if new_head_end is None or updated[new_head_end.end():] != body_snapshots[item.relative]:
            raise RuntimeError(f"Refusing to change article body content: {item.relative}")
    write_sitemap(pages)
    check(pages)
    print("Generated metadata and sitemap; page wording was preserved apart from em-dash punctuation.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"SEO generation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
