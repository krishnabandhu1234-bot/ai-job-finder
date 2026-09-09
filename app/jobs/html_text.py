"""Strips job-board HTML descriptions down to plain text.

Shared by every connector that receives HTML job descriptions
(Greenhouse, Ashby). Job description HTML is untrusted external content -
this only ever extracts visible text for storage/display, it never
executes scripts or renders the HTML (see section 24: job descriptions
are data, never instructions, and are never rendered as live HTML
anywhere in the app).
"""

from __future__ import annotations

import html as html_module
import re

from bs4 import BeautifulSoup

_BLOCK_TAGS = ["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote"]


def html_to_text(html: str) -> str:
    if not html:
        return ""

    # Some sources (observed on Greenhouse's public API) return
    # HTML-escaped markup - the JSON string literally contains "&lt;div
    # class=&quot;...&quot;&gt;" instead of real "<div ...>" tags. Parsing
    # that as-is just decodes the entities into text that *looks* like
    # tags without actually being structural HTML, so get_text() has
    # nothing to strip and the "tags" leak straight into the stored
    # description. Unescaping first reveals the real markup so it can
    # actually be parsed and stripped. This is a no-op (and harmless) for
    # sources that already send real, unescaped HTML.
    html = html_module.unescape(html)

    soup = BeautifulSoup(html, "html.parser")

    for br in soup.find_all("br"):
        br.replace_with("\n")
    # Mark block-element boundaries with a newline BEFORE extracting text,
    # so paragraphs/list items break onto their own line - but use a plain
    # space separator within get_text() itself, so an inline tag in the
    # middle of a sentence (e.g. "<p>Great <b>role</b></p>") doesn't
    # fracture it into "Great\nrole".
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")

    text = soup.get_text(separator=" ")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)
