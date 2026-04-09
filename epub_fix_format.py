# epub_fix_format.py
# author: Daisy Jane @dayzl
# Normalizes epub files for reflowable reading on eReaders and PDF viewers.
#
# Handles three source structures commonly found in music epub publications:
#   New-style reflowable  -- section.song-start + div.music1
#   Chapter-style         -- div.music90 chapter pages + div.musicL/R inline figures
#   Old-style ballads     -- div.chapter-header-block + illustype_fullpage_image_text
#   Fixed-layout          -- pages position:absolute; unsupported (exit)
#
# Normalized output structure (per song):
#   <audio class="mp3">...</audio>          (optional; before first music-page)
#   <div class="music-page">               <- title page: all in one flow container
#     <div class="music-header">
#       <h1 class="title">...</h1>
#       <h3 class="subtitle">...</h3>     (optional)
#       <h4 class="credit">...</h4>       (optional)
#     </div>
#     <img/>                              <- first score image in normal flow
#     <div class="music-footer">         (only if p.rights present)
#       <p class="rights">...</p>
#     </div>
#   </div>
#   <div class="music-page"><img/></div>  (subsequent score pages)
#   ...
#
# Rewrite pipeline (reflowable only):
#   0  unwrap_anon_section_divs    dissolve anonymous <div> wrappers inside <section>
#   1  rewrite_section_music       sections -> divs; song-start unwrapped
#   2  normalize_titles            title variants -> h1.title / h3.subtitle / h4.credit
#                                  + merge consecutive h1.title siblings into one
#   3  normalize_image_blocks      dissolve song-header-block/illustype BEFORE music1 rename
#   4  normalize_music_divs        music90/music1/musicfirst/music[id] -> music-page
#   5  wrap_music_header           inject music-header around title block
#   6  move_audio_before_header    audio.mp3 moved before first music-page
#   7  merge_header_and_first_page music-header + first music-page + rights -> one music-page
#   8  promote_continuation_pages  div.music after music-page -> music-page
#   9  move_footer_to_page         move footer to first or last page (FOOTER_FIRST)
#   10  wrap_figure_blocks         Berklee: figure + caption kept together
#   11 merge_split_headers         safety-net for any residual split headers (last)
#
# Usage:
#   python epub_fix_format.py input.epub [output.epub]
#   python epub_fix_format.py input.epub --no-images   (skip image processing)
#
# Requirements: Pillow  (pip install Pillow)
# Safe to re-run on already-processed files.

import argparse
import io
import os
import re as _re
import shutil
import sys
import zipfile
import subprocess
import tempfile

from PIL import Image

HAS_MAGICK   = shutil.which('magick') is not None  # Check once at import. Images pass through silently if missing
FOOTER_FIRST = False  # If True: footer on title page; If False: footer on last page


# ---------------------------------------------------------------------------
# CSS stylesheet
# ---------------------------------------------------------------------------

FIXED_CSS = '''\
/* --- Base reset ------------------------------------------------------- */
html, body {
    margin: 0;
    padding: 0;
}

a {
    text-decoration: none;
    color: inherit;
}

img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: auto;
}

/* --- General elements ------------------------------------------------- */
article, section {
    display: block;
    width: 100%;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

article, section, div, figure,
h1, h2, h3, h4, h5, h6, p, span, ol, ul, li {
    font-style: normal;
    margin: 0;
    padding: 0;
    text-transform: none;
    hyphens: none;
    -epub-hyphens: none;
    box-sizing: border-box;
}

strong      { font-weight: bold;   font-style: normal; }
em          { font-style: italic;  font-weight: normal; }
.bold       { font-weight: bold;   font-style: normal; }
.italic     { font-style: italic;  font-weight: normal; }
.bolditalic { font-style: italic;  font-weight: bold; }
span.b      { font-weight: bold;   font-style: normal; }
span.i      { font-style: italic;  font-weight: normal; }

/* -----------------------------------------------------------------------
   Song header (title page text block)
   page-break-inside:avoid keeps title/subtitle/credit together.
   margin-bottom separates it from the first score image.
   ----------------------------------------------------------------------- */
div.music-header {
    page-break-inside: avoid;
    text-align: center;
    margin-bottom: 0.5em;
}

/* normal flow: no special positioning needed */
.header-main {
    text-align: center;
}

/* footer sits below image in normal flow */
.music-footer {
    page-break-inside: avoid;
    margin-top: 0.5em;
    text-align: center;
}

.music-footer p.rights {
    font-size: 0.5em;
    margin: 0;
}

/* -----------------------------------------------------------------------
   Normalized song titles / credits / rights
   ----------------------------------------------------------------------- */
h1.title {
    font-size: 1em;
    font-weight: bold;
    line-height: 1.2;
    text-align: center;
    text-transform: uppercase;
    margin: 0 0 0.2em 0;
}

h3.subtitle {
    font-size: 0.7em;
    font-weight: normal;
    line-height: 1.2;
    text-align: center;
    margin: 0 0 0.1em 0;
}

h4.credit {
    font-size: 0.5em;
    font-weight: normal;
    line-height: 1;
    text-align: right;
    display: block;
    width: 100%;
    margin: 0;
}

p.rights {
    font-size: 0.4em;
    font-weight: normal;
    line-height: 1;
    text-align: center;
    margin: 0;
}

/* -----------------------------------------------------------------------
   Music pages - one logical page per score image.
   page-break-before:always starts each on a new page.
   Image is full-width, centered with auto margins. No absolute positioning,
   no height tricks that break in reflowable EPUB engine.
   ----------------------------------------------------------------------- */
div.music-page {
    page-break-before: always;
    page-break-inside: avoid;
    width: 100%;
    text-align: center;
}

div.music-page img {
    display: block;
    width: 100%;
    height: auto;
    text-align: center;
    margin-left: auto;
    margin-right: auto;
    float: none;
}

/* -----------------------------------------------------------------------
   Inline music figures (Berklee: musicL, musicR, music)
   These are NOT full-page; they float beside body text.
   ----------------------------------------------------------------------- */
div.music {
    display: block;
    width: 100%;
    text-align: center;
    margin: 0.5em 0;
}

div.musicL {
    float: left;
    width: 45%;
    margin: 0 1em 0.5em 0;
    text-align: center;
}

div.musicR {
    float: right;
    width: 45%;
    margin: 0 0 0.5em 1em;
    text-align: center;
}

div.music img,
div.musicL img,
div.musicR img {
    max-width: 100%;
    height: auto;
    display: block;
}

/* -----------------------------------------------------------------------
   Figure block: inline image + caption kept together (Berklee)
   ----------------------------------------------------------------------- */
div.fig-block {
    display: block;
    width: 100%;
    page-break-inside: avoid;
    -webkit-column-break-inside: avoid;
    clear: both;
}

/* -----------------------------------------------------------------------
   Layout helpers
   ----------------------------------------------------------------------- */
div.clear { clear: both; }
div.break { page-break-before: always; }

/* -----------------------------------------------------------------------
   TOC
   ----------------------------------------------------------------------- */
body h1.tochead_int,
body h1.toc_head,
body h1.title-toc {
    text-align: center;
    font-size: 1em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 3px;
    color: #555;
    margin: 0 0 0.8em 0;
    page-break-before: always;
}

body p.toc_int,
body p.toc_entry {
    text-align: left;
    font-size: 0.9em;
    line-height: 1.4;
    margin: 0.35em 0 0 0;
}

body div.toc_entry {
    text-align: left;
    font-size: 0.9em;
    line-height: 1.8;
    margin: 0;
}

body div.toc_entry a,
body a.toc_entry_chapter {
    display: block;
    text-align: left;
    font-weight: normal;
    text-decoration: none;
    color: inherit;
}

/* -----------------------------------------------------------------------
   Berklee body / narrative text
   ----------------------------------------------------------------------- */
body p.ChStartC {
    font-size: 0.6em;
    line-height: 1.3;
    text-align: center;
    font-weight: normal;
    margin: 0 0 0.5em 0;
}

body p.ChStartL {
    font-size: 0.6em;
    line-height: 1.3;
    text-align: left;
    font-weight: normal;
    margin: 0;
}

body p.ChStartR {
    font-size: 0.6em;
    line-height: 1.3;
    text-align: right;
    font-weight: normal;
    margin: 0;
}

body p.ChStartLS {
    font-size: 0.65em;
    line-height: 1.4;
    text-align: left;
    font-weight: normal;
    margin: 0 0 0.75em 0;
}

body p.body,
body p.bodyS,
body p.bodyD,
body p.bodyC {
    font-size: 0.8em;
    line-height: 1.5;
    margin: 0 0 0.75em 0;
    text-align: left;
}

body p.bio {
    font-size: 0.75em;
    line-height: 1.5;
    margin: 0 0 0.75em 0;
    text-align: left;
    font-style: italic;
}

body p.level {
    font-size: 0.65em;
    text-align: right;
    margin: 0 0 0.25em 0;
}

body p.photo-credit {
    font-size: 0.55em;
    text-align: center;
    margin: 0.2em 0 0 0;
}

/* -----------------------------------------------------------------------
   Figure captions
   ----------------------------------------------------------------------- */
body p.FIG,
body p.fig {
    font-size: 0.65em;
    line-height: 1.3;
    text-align: center;
    font-weight: normal;
    margin: 0.2em 0 0.5em 0;
}

/* -----------------------------------------------------------------------
   Copyright / publisher page
   ----------------------------------------------------------------------- */
div.copyrightart { width: 90%; margin: 0 auto; }
div.group1 { margin: 2em auto 1em auto; }
div.group2 { margin: 1em auto; }
div.group3 { margin: 0 auto; width: 60%; text-align: center; }
div.group4 { margin: 0.5em 0; }

section.address-container { display: block; width: 100%; margin: 1em 0 0 0; }
div.location { display: block; width: 100%; margin: 0.5em 0; text-align: center; }

body div.pubInfo {
    text-align: center;
    font-size: 0.75em;
    line-height: 1.5;
    margin: 1em auto;
    width: 90%;
}

body p.address,
body p.copyrights   { font-size: 0.55em; line-height: 1.2; text-align: center; margin: 0; }
body p.p-blanc      { margin: 0.5em 0; }
body p.p-c-br       { font-size: 0.6em; text-align: center; margin: 0.5em 0; }
body p.photorights  { font-size: 0.6em; line-height: 1.2; text-align: center; }
body p.isbn         { font-size: 0.6em; line-height: 1.2; text-align: center; }
body p.hladdress    { font-size: 0.5em; line-height: 1.2; text-align: center; }
body p.copyright    { font-size: 0.55em; line-height: 1.2; text-align: center; }
body p.website      { font-size: 0.6em; font-weight: bold; text-align: center; margin: 2px 0 0 0; }

/* -----------------------------------------------------------------------
   Footnotes
   ----------------------------------------------------------------------- */
p.footnote,
p.footnotes,
aside.footnote,
div.footnote,
div.footnotes {
    font-size: 0.55em;
    line-height: 1;
    margin: 0.25em 0 0 0;
    text-align: center;
    font-weight: normal;
}

/* -----------------------------------------------------------------------
   Audio / video
   ----------------------------------------------------------------------- */
audio.mp3 { width: 100%; }
p.label   { font-size: 0.6em; line-height: 1.2; }
video     { width: 100%; height: auto; display: block; margin: 0.5em auto; }

/* -----------------------------------------------------------------------
   Notation legend
   ----------------------------------------------------------------------- */
body h1.legend  { page-break-before: always; font-size: 1em;   text-align: center; font-weight: bold; }
body h3.legend2 { page-break-before: always; font-size: 0.85em; text-align: center; font-weight: bold; }

div.backcover { width: 100%; margin: 0 auto; }
ul, ol { margin: 0 0 0 2em; }
'''


# ---------------------------------------------------------------------------
# Viewport normalisation
# ---------------------------------------------------------------------------

_VIEWPORT_RE = _re.compile(
    r'<meta\b[^>]*\bname=["\']viewport["\'][^>]*/?>',
    _re.IGNORECASE,
)
_VIEWPORT_CLEAN = '<meta name="viewport" content="width=device-width, initial-scale=1.0"/>'


def fix_viewport(content: bytes) -> bytes:
    text = content.decode('utf-8', errors='replace')
    return _VIEWPORT_RE.sub(_VIEWPORT_CLEAN, text).encode('utf-8')


# ---------------------------------------------------------------------------
# Inline style / align scrubbing
# ---------------------------------------------------------------------------

_INLINE_STYLE_RE = _re.compile(
    r'(<(?:div|section|h[1-6]|p|span|img)\b[^>]*?)\s+style=(?:"[^"]*"|\'[^\']*\')',
    _re.IGNORECASE,
)
_INLINE_ALIGN_RE = _re.compile(
    r'(<(?:div|section|h[1-6]|p|span|img)\b[^>]*?)\s+align="(?:left|right|center)"',
    _re.IGNORECASE,
)

def scrub_inline_overrides(text: str) -> str:
    text = _INLINE_STYLE_RE.sub(r'\1', text)
    text = _INLINE_ALIGN_RE.sub(r'\1', text)
    return text


# ---------------------------------------------------------------------------
# Step 0: unwrap_anon_section_divs
# ---------------------------------------------------------------------------
# Dissolves anonymous <div> wrappers (no class, no id) that are direct children
# of <section> elements and contain a song-header-block or h1.songtitle/title.
# These wrappers exist in Hal Leonard Hymns-style sources and prevent rights
# elements from being contiguous siblings of title/credit elements.
#
# Guard conditions (ALL must be true to unwrap):
#   - tag is <div> with no class and no id
#   - direct child of <section> (checked by surrounding context)
#   - contains a song-header-block or h1.songtitle or h1.title
# Idempotent: once unwrapped the conditions don't re-match.

_ANON_DIV_OPEN_RE = _re.compile(r'<div>', _re.IGNORECASE)  # bare <div> only no attrs
_SONG_CONTENT_RE = _re.compile(
    r'(?:class="song-header-block"|class="songtitle"|class="title")',
    _re.IGNORECASE,
)


def unwrap_anon_section_divs(text: str) -> str:
    '''Dissolve bare <div>...</div> wrappers inside <section> that contain
    song header content. Repeat until stable (handles rare double-wrapping).
    Uses _find_div_end for depth-aware boundary detection so nested <div>
    children are never truncated.'''
    while True:
        changed = False
        result  = []
        i       = 0
        while i < len(text):
            m = _ANON_DIV_OPEN_RE.search(text, i)
            if not m:
                result.append(text[i:])
                break
            start = m.start()
            end   = _find_div_end(text, start)
            if end <= m.end() or text[end - len('</div>'):end].lower() != '</div>':
                result.append(text[i:])
                break
            inner = text[m.end():end - len('</div>')]
            if _SONG_CONTENT_RE.search(inner):
                result.append(text[i:start])             # emit before wrapper
                result.append(inner)                     # dissolve wrapper
                changed = True
            else:
                result.append(text[i:end])               # emit whole div unchanged
            i = end
        text = ''.join(result)
        if not changed:
            break
    return text


# ---------------------------------------------------------------------------
# Step 1: rewrite_section_music
# ---------------------------------------------------------------------------
# section.music      -> div.music   (Hal Leonard outer wrapper - keep)
# section.song-start -> unwrapped   (super-block - dissolve, emit contents only)
# Depth-tracked character-by-character so nested sections close correctly.

_SECTION_MUSIC_RE = _re.compile(r'<section(\s[^>]*)?\bclass="music"', _re.IGNORECASE)
_SECTION_SONG_RE  = _re.compile(r'<section(\s[^>]*)?\bclass="song-start"', _re.IGNORECASE)
_SECTION_CLOSE_RE = _re.compile(r'</section>', _re.IGNORECASE)


def rewrite_section_music(text: str) -> str:
    result = []
    music_depth = 0
    song_depth  = 0
    i = 0

    while i < len(text):
        m = _SECTION_MUSIC_RE.match(text, i)
        if m:
            attrs = (m.group(1) or '').rstrip()
            prefix = (' ' + attrs) if attrs and not attrs.startswith(' ') else attrs
            result.append(f'<div{prefix} class="music"')
            music_depth += 1
            i = m.end()
            continue

        m = _SECTION_SONG_RE.match(text, i)
        if m:
            # Unwrap: skip the entire opening tag including any trailing attrs
            gt = text.find('>', m.end())
            if gt == -1:
                break
            song_depth += 1
            i = gt + 1
            continue

        m = _SECTION_CLOSE_RE.match(text, i)
        if m:
            if song_depth > 0:
                song_depth -= 1     # close of song-start: emit nothing
            elif music_depth > 0:
                result.append('</div>')
                music_depth -= 1
            else:
                result.append(m.group())
            i = m.end()
            continue

        result.append(text[i])
        i += 1

    return ''.join(result)


# ---------------------------------------------------------------------------
# Step 2: normalize_titles
# ---------------------------------------------------------------------------
# Maps all source variants to h1.title / h3.subtitle / h4.credit.
#
# Source -> Target:
#   h1.songtitle        -> h1.title       (preserve id=)
#   h1.title-chapter    -> h1.title       (strip inner span.b)
#   p.song              -> h1.title       (Berklee; preserve id=)
#   h3.songsubtitle     -> h3.subtitle
#   h1.subtitle-chapter -> h3.subtitle    (strip inner span.b)
#   p.p-title           -> h4.credit      (old-style composer credit)
#   h4.credit           -> h4.credit      (no change; already normalized)
#   h3.songpretitle     -> prepend "(text) " to following h1.title, then removed
#   div.header-container / credit-container / footer-container -> unwrapped

_SPAN_B_RE = _re.compile(r'<span\b[^>]*class="b"[^>]*>(.*?)</span>', _re.DOTALL | _re.IGNORECASE)

def _strip_span_b(html: str) -> str:
    return _SPAN_B_RE.sub(r'\1', html)

def _extract_id(attrs: str) -> str:
    m = _re.search(r'\bid="([^"]*)"', attrs)
    return f' id="{m.group(1)}"' if m else ''


_SONGTITLE_RE = _re.compile(
    r'<h1\b([^>]*)class="songtitle"([^>]*)>(.*?)</h1>',
    _re.DOTALL | _re.IGNORECASE,
)
_TITLE_CHAPTER_RE = _re.compile(
    r'<h1\b[^>]*class="title-chapter"[^>]*>(.*?)</h1>',
    _re.DOTALL | _re.IGNORECASE,
)
_SUBTITLE_CHAPTER_RE = _re.compile(
    r'<h1\b[^>]*class="subtitle-chapter"[^>]*>(.*?)</h1>',
    _re.DOTALL | _re.IGNORECASE,
)
_SONGSUBTITLE_RE = _re.compile(
    r'<h3\b[^>]*class="songsubtitle"[^>]*>(.*?)</h3>',
    _re.DOTALL | _re.IGNORECASE,
)
_P_TITLE_RE = _re.compile(
    r'<p\b[^>]*class="p-title"[^>]*>(.*?)</p>',
    _re.DOTALL | _re.IGNORECASE,
)
_P_SONG_RE = _re.compile(
    r'<p\b([^>]*)class="song"([^>]*)>(.*?)</p>',
    _re.DOTALL | _re.IGNORECASE,
)
# Merge songpretitle into the following h1.title (applied after title rewrites)
_PRETITLE_MERGE_RE = _re.compile(
    r'<h3\b[^>]*class="songpretitle"[^>]*>(.*?)</h3>'
    r'\s*'
    r'<h1\b([^>]*)class="title"([^>]*)>(.*?)</h1>',
    _re.DOTALL | _re.IGNORECASE,
)
# Unwrap container divs and old title-lines wrapper (no longer needed)
_CONTAINER_DIV_RE = _re.compile(
    r'<div\b[^>]*class="(?:header-container|credit-container|footer-container|title-lines)"[^>]*>'
    r'(.*?)'
    r'</div>',
    _re.DOTALL | _re.IGNORECASE,
)
_SUBTITLE_RE = _re.compile(
    r'<h3\b[^>]*class="subtitle"[^>]*>(.*?)</h3>',
    _re.DOTALL | _re.IGNORECASE,
)

# Clean <br> from lines
def _clean_lines(html: str) -> str:
    t = html.strip()
    # normalize all <br> variants INCLUDING </br>
    t = _re.sub(r'</?br\s*/?>', '<br/>', t, flags=_re.IGNORECASE)
    # collapse duplicate <br>
    t = _re.sub(r'(<br/>\s*){2,}', '<br/>', t)
    # trim leading/trailing <br>
    t = _re.sub(r'^(<br/>\s*)+|(\s*<br/>)+$', '', t)
    return t

def normalize_titles(text: str) -> str:
    # h1.songtitle -> h1.title
    def _songtitle(m: _re.Match) -> str:
        id_attr = _extract_id(m.group(1) + m.group(2))
        return f'<h1{id_attr} class="title">{m.group(3)}</h1>'
    text = _SONGTITLE_RE.sub(_songtitle, text)

    # h1.title-chapter -> h1.title
    text = _TITLE_CHAPTER_RE.sub(
        lambda m: f'<h1 class="title">{_strip_span_b(m.group(1))}</h1>', text)

    # h1.subtitle-chapter -> h3.subtitle
    text = _SUBTITLE_CHAPTER_RE.sub(
        lambda m: f'<h3 class="subtitle">{_strip_span_b(m.group(1))}</h3>', text)

    # h3.songsubtitle -> h3.subtitle
    text = _SONGSUBTITLE_RE.sub(
        lambda m: f'<h3 class="subtitle">{m.group(1)}</h3>', text)

    # p.p-title -> h4.credit
    text = _P_TITLE_RE.sub(
        lambda m: f'<h4 class="credit">{m.group(1)}</h4>', text)

    # p.song -> h1.title (Berklee)
    def _p_song(m: _re.Match) -> str:
        id_attr = _extract_id(m.group(1) + m.group(2))
        return f'<h1{id_attr} class="title">{m.group(3)}</h1>'
    text = _P_SONG_RE.sub(_p_song, text)

    # Unwrap container divs and title-lines wrapper (repeat until stable)
    while True:
        new = _CONTAINER_DIV_RE.sub(lambda m: m.group(1), text)
        if new == text:
            break
        text = new

    # Merge h3.songpretitle into following h1.title.
    # Prepend as-is (no added parens, source may already have them)
    def _merge_pretitle(m: _re.Match) -> str:
        pretitle = m.group(1).strip()
        h1_pre   = m.group(2)
        h1_post  = m.group(3)
        body     = m.group(4).strip()
        id_attr  = _extract_id(h1_pre + h1_post)
        return f'<h1{id_attr} class="title">{pretitle} {body}</h1>'
    text = _PRETITLE_MERGE_RE.sub(_merge_pretitle, text)

    # Merge consecutive h1.title siblings into a single h1 with <br/>.
    # This must happen before wrap_music_header so each song gets one header,
    # not one per title line. The first id= is kept; subsequent ids are dropped.
    # Negative lookahead (?!<h1\b) prevents group 1 from spanning song
    # boundaries (backtracking cross-section would otherwise absorb everything).
    _CONSEC_TITLE_RE = _re.compile(
        r'(<h1\b([^>]*)class="title"[^>]*>'
        r'(?:(?!<h1\b).)*?</h1>)'
        r'(\s*<h1\b[^>]*class="title"[^>]*>'
        r'(?:(?!<h1\b).)*?</h1>)+',
        _re.DOTALL | _re.IGNORECASE,
    )

    def _merge_titles(m: _re.Match) -> str:
        # Re-find all h1.title tags in the full match and join their text
        parts = _re.findall(
            r'<h1\b([^>]*)class="title"[^>]*>((?:(?!<h1\b).)*?)</h1>',
            m.group(0), _re.DOTALL | _re.IGNORECASE,
        )
        # Preserve id from the first element that has one
        id_attr = ''
        texts   = []
        for attrs, body in parts:
            if not id_attr:
                id_attr = _extract_id(attrs)
            clean = _clean_lines(body)
            if clean:
                texts.append(clean)
        return f'<h1{id_attr} class="title">{" ".join(texts)}</h1>'

    text = _CONSEC_TITLE_RE.sub(_merge_titles, text)


    def _clean_subtitle(m: _re.Match) -> str:
        body = _clean_lines(m.group(1))
        if not body:
            return ''
        return f'<h3 class="subtitle">{body}</h3>'

    text = _re.sub(r'<h3\b[^>]*class="subtitle"[^>]*>(.*?)</h3>',
        _clean_subtitle,
        text,
        flags=_re.DOTALL | _re.IGNORECASE,
    )

    return text


# ---------------------------------------------------------------------------
# Step 3: normalize_image_blocks
# ---------------------------------------------------------------------------
# Unwraps super-blocks (chapter-header-block, song-header-block).
# Normalizes illustype_fullpage* outer + fullpage_image_text inner -> div.music-page.
# Must run before normalize_music_divs (step 4) so song-header-block is dissolved
# before music1 is renamed, otherwise the depth-unaware regex stops too early.

_SUPER_BLOCK_PAT = _re.compile(
    r'<div\b[^>]*class="[^"]*(?:chapter-header-block|song-header-block)[^"]*"[^>]*>',
    _re.IGNORECASE,
)
# illustype outer wrapping a fullpage_image_text inner
_ILLUSTYPE_WRAPPED_RE = _re.compile(
    r'<div\b[^>]*class="[^"]*illustype_[^"]*"[^>]*>\s*'
    r'<div\b[^>]*class="[^"]*fullpage_image_text[^"]*"[^>]*>'
    r'(.*?)'
    r'</div>'       # close fullpage_image_text
    r'\s*</div>',   # close illustype outer
    _re.DOTALL | _re.IGNORECASE,
)
# illustype outer with no inner fullpage wrapper
_ILLUSTYPE_BARE_RE = _re.compile(
    r'<div\b[^>]*class="[^"]*illustype_[^"]*"[^>]*>(.*?)</div>',
    _re.DOTALL | _re.IGNORECASE,
)


def normalize_image_blocks(text: str) -> str:
    # Depth-aware unwrap of super-blocks; repeat until stable.
    # Simple regex fails because music1 closes before song-header-block,
    # so non-greedy .*? stops at music1's </div> instead of the block's own close.
    while True:
        m = _SUPER_BLOCK_PAT.search(text)
        if not m:
            break
        end = _find_div_end(text, m.start())
        if end <= m.end() or text[end - len('</div>'):end].lower() != '</div>':
            break
        inner = text[m.end():end - len('</div>')]   # content between open and close tags
        text = text[:m.start()] + inner + text[end:]

    # illustype + fullpage_image_text -> div.music-page
    text = _ILLUSTYPE_WRAPPED_RE.sub(
        lambda m: f'<div class="music-page">{m.group(1)}</div>', text)

    # remaining bare illustype -> div.music-page
    text = _ILLUSTYPE_BARE_RE.sub(
        lambda m: f'<div class="music-page">{m.group(1)}</div>', text)

    return text


# ---------------------------------------------------------------------------
# Step 4: normalize_music_divs
#
# music-page, music-header -> unchanged
# musicL, musicR           -> unchanged (inline figures)
# music90                  -> music-page  (Berklee full-page chapter image)
# music[id=...]            -> music-page  (Hal Leonard / Berklee standalone page)
# music1, musicfirst       -> music-page  (first page; extracted in step 6)
# music (no id, no suffix) -> music       (Berklee inline figure)

_MUSIC_DIV_RE = _re.compile(
    r'(<div)\s+([^>]*class="music[^"]*"[^>]*)>',
    _re.IGNORECASE,
)


def normalize_music_divs(text: str) -> str:
    def _replace(m: _re.Match) -> str:
        tag   = m.group(1)
        attrs = m.group(2)
        cls   = attrs.lower()

        # Already canonical, leave unchanged
        if _re.search(r'class="music-(?:page|header)"', attrs, _re.IGNORECASE):
            return m.group(0)

        # Inline float figures unchanged
        if _re.search(r'class="music[LR]"', attrs, _re.IGNORECASE):
            return m.group(0)

        # Named suffix variants -> music-page.
        # illustype_* and fullpage_image* remain in normalize_image_blocks (step 3).
        if any(x in cls for x in ['music90', 'music1', 'musicfirst']):
            id_m = _re.search(r'id="[^"]*"', attrs)
            id_attr = (' ' + id_m.group()) if id_m else ''
            return f'{tag}{id_attr} class="music-page">'

        # plain div.music WITH id= -> standalone page (Berklee chapter covers)
        if _re.search(r'\bclass="music"', attrs, _re.IGNORECASE) and 'id=' in attrs:
            id_m = _re.search(r'id="[^"]*"', attrs)
            id_attr = (' ' + id_m.group()) if id_m else ''
            return f'{tag}{id_attr} class="music-page">'

        # plain div.music without id -> inline figure, leave as-is
        return m.group(0)

    text = _MUSIC_DIV_RE.sub(_replace, text)
    # Clean up legacy double-class from old script runs
    text = _re.sub(r'class="music music-page"', 'class="music-page"', text, flags=_re.IGNORECASE)
    return text



# ---------------------------------------------------------------------------
# Shared helpers: depth-aware div boundary detection
# ---------------------------------------------------------------------------

_DIV_OPEN_RE  = _re.compile(r'<div\b', _re.IGNORECASE)
_DIV_CLOSE_RE = _re.compile(r'</div>', _re.IGNORECASE)


def _find_div_end(text: str, start: int) -> int:
    '''Return the index just after the </div> that closes the div opening at start.
    start must point to the < of the opening <div...> tag.
    NOTE: If the HTML is malformed (unbalanced <div>), returns len(text).
    Callers must tolerate truncated ranges in that case.'''
    close_open = text.index('>', start) + 1
    depth = 1
    i = close_open
    while i < len(text) and depth > 0:
        mo = _DIV_OPEN_RE.search(text, i)
        mc = _DIV_CLOSE_RE.search(text, i)
        if mc is None:
            break
        if mo is not None and mo.start() < mc.start():
            depth += 1
            i = mo.end()
        else:
            depth -= 1
            i = mc.end()
    return i


# ---------------------------------------------------------------------------
# Step 5: wrap_music_header
# ---------------------------------------------------------------------------
# Injects div.music-header around title+subtitle+credit+rights sequences that
# are not yet inside one. Handles Hal Leonard new-style (song-start was unwrapped
# in step 1, leaving elements as siblings) and Jazz Ballads (chapter-header-block
# was unwrapped in step 4, same result).
# Guard: before-context check (80 chars) prevents double-wrapping on re-runs.

_HEADER_CONTENT_RE = _re.compile(
    r'(<h1\b[^>]*class="title"[^>]*>.*?</h1>)'           # h1.title (required)
    r'(\s*<h3\b[^>]*class="subtitle"[^>]*>.*?</h3>)?'   # h3.subtitle (optional)
    r'(?:\s*<h4\b[^>]*class="credit"[^>]*>.*?</h4>)*'   # h4.credit (0+)
    r'(?:\s*<p\b[^>]*class="rights"[^>]*>.*?</p>)*',    # p.rights (0+)
    _re.DOTALL | _re.IGNORECASE,
)


def wrap_music_header(text: str) -> str:
    def _wrap(m: _re.Match) -> str:
        if not m.group(0).strip():
            return m.group(0)
        before = text[max(0, m.start() - 80):m.start()]
        if 'music-header' in before:
            return m.group(0)
        return f'<div class="music-header">\n{m.group(0)}\n</div>'
    return _HEADER_CONTENT_RE.sub(_wrap, text)


# ---------------------------------------------------------------------------
# Step 6: move_audio_before_header
# ---------------------------------------------------------------------------
# Moves audio.mp3 from after the music-header to before it, so audio stays
# on the preceding prose page rather than between the header and score images.
# Must run BEFORE merge_header_and_first_page (step 7) because after merging,
# the header is inside a music-page and the search target changes.

_AUDIO_RE     = _re.compile(r'<audio[^>]*class="mp3"[^>]*>.*?</audio>', _re.DOTALL | _re.IGNORECASE)
_LABEL_RE     = _re.compile(r'<p[^>]*class="label"[^>]*>.*?</p>',      _re.DOTALL | _re.IGNORECASE)
_HDR_OPEN_RE  = _re.compile(r'<div[^>]*class="music-header"[^>]*>',    _re.IGNORECASE)
_PAGE_OPEN_RE = _re.compile(r'<div[^>]*class="music-page"[^>]*>',      _re.IGNORECASE)


def move_audio_before_header(text: str) -> str:
    '''Move audio.mp3 (and optional p.label) from after music-header to before it.
    Skips any music-page divs between the header close and the audio tag.'''
    result = []
    pos    = 0
    for hdr_m in _HDR_OPEN_RE.finditer(text):
        if hdr_m.start() < pos:
            continue
        hdr_end = _find_div_end(text, hdr_m.start())

        # Skip whitespace after header
        scan = hdr_end
        while scan < len(text) and text[scan] in ' \t\r\n':
            scan += 1

        # Skip any music-page divs between header and audio
        while True:
            pm = _PAGE_OPEN_RE.match(text, scan)
            if not pm:
                break
            scan = _find_div_end(text, scan)
            while scan < len(text) and text[scan] in ' \t\r\n':
                scan += 1

        # Optional p.label
        label_end = scan
        lm = _LABEL_RE.match(text, scan)
        if lm:
            label_end = lm.end()
            while label_end < len(text) and text[label_end] in ' \t\r\n':
                label_end += 1

        # Required audio.mp3
        am = _AUDIO_RE.match(text, label_end)
        if not am:
            continue

        audio_block = text[scan:am.end()]
        result.append(text[pos:hdr_m.start()])
        result.append(audio_block)
        result.append('\n')
        result.append(text[hdr_m.start():hdr_end])
        pos = am.end()

    result.append(text[pos:])
    return ''.join(result)


# ---------------------------------------------------------------------------
# Helper: normalize_credits
# ---------------------------------------------------------------------------
# Collapses consecutive h4.credit elements into a single h4, joining their
# text with <br/>. Connector words (by, from, and) broken across a <br/> are
# rejoined onto the same line.

_CREDIT_BLOCK_RE = _re.compile(
    r'(<h4[^>]*class="credit"[^>]*>.*?</h4>\s*)+',
    _re.DOTALL | _re.IGNORECASE
)
_SINGLE_CREDIT_RE = _re.compile(
    r'<h4[^>]*class="credit"[^>]*>(.*?)</h4>',
    _re.DOTALL | _re.IGNORECASE
)

def normalize_credits(hdr_block: str) -> str:
    def repl(match: _re.Match) -> str:
        parts = _SINGLE_CREDIT_RE.findall(match.group(0))

        cleaned = []
        for p in parts:
            t = _clean_lines(p) # normalize <br> variants, trim edges
            if t:
                cleaned.append(t)
        if not cleaned:
            return ''

        joined = '<br/>'.join(cleaned) # join first, then fix connectors

        # remove <br/> after connector words
        joined = _re.sub(
            r'\b(by|from|and)\s*<br/>\s*',
            r'\1 ',
            joined,
            flags=_re.IGNORECASE,
        )

        return '<h4 class="credit">' + joined + '</h4>\n'

    return _CREDIT_BLOCK_RE.sub(repl, hdr_block)


# ---------------------------------------------------------------------------
# Helper: is_header_heavy
# ---------------------------------------------------------------------------
# Returns True if the combined title + subtitle + credit line count exceeds 3.
# Used by merge_header_and_first_page to suppress the rights footer when the
# header already fills most of the title page.

def count_lines_from_block(inner_html: str) -> int:
    if not inner_html.strip():
        return 0

    brs = len(_re.findall(r'<br\s*/?>', inner_html, _re.IGNORECASE))
    return brs + 1

def extract_inner(tag_pattern: str, html: str) -> str:
    m = _re.search(tag_pattern, html, _re.DOTALL | _re.IGNORECASE)
    return m.group(1).strip() if m else ''

def is_header_heavy(hdr_block: str) -> bool:
    title   = extract_inner(r'<h1[^>]*class="title"[^>]*>(.*?)</h1>', hdr_block)
    subtitle = extract_inner(r'<h3[^>]*class="subtitle"[^>]*>(.*?)</h3>', hdr_block)
    credit  = extract_inner(r'<h4[^>]*class="credit"[^>]*>(.*?)</h4>', hdr_block)

    title_lines    = count_lines_from_block(title)
    subtitle_lines = count_lines_from_block(subtitle)
    credit_lines   = count_lines_from_block(credit)

    total_lines = title_lines + subtitle_lines + credit_lines
    return total_lines > 3


# ---------------------------------------------------------------------------
# Step 7: merge_header_and_first_page
# ---------------------------------------------------------------------------
# Merges music-header + following music-page + following rights into a single
# div.music-page. This is the correct flow-layout approach: everything on the
# "title page" lives in one container so no cross-sibling coordination is needed.
# Footer sits in normal flow after the image, not absolutely positioned.
#
# Input (after steps 1-6):
#   <div class="music-header">title/credit</div>
#   <div class="music-page"><img/></div>
#   <p class="rights">...</p>
#
# Output:
#   <div class="music-page">
#     <div class="music-header">title/credit</div>
#     <img/>
#     <div class="music-footer"><p class="rights">...</p></div> (if present)
#   </div>
#
# Idempotent: skips if music-header is already inside a music-page.

_RIGHTS_LOOSE_RE = _re.compile(
    r'(?:\s*<p[^>]*class="rights"[^>]*>.*?</p>)+',
    _re.DOTALL | _re.IGNORECASE,
)
_IMG_TAG_RE   = _re.compile(r'<img\b[^>]*/?>',  _re.IGNORECASE)
_FIG_OPEN_RE  = _re.compile(r'<div[^>]*class="fig-block"[^>]*>', _re.IGNORECASE)
_MUSIC_NO_ID  = _re.compile(r'<div\s+[^>]*class="music"[^>]*>', _re.IGNORECASE)


def merge_header_and_first_page(text: str) -> str:
    '''Merge music-header + first music-page (+ optional rights) into one music-page.
    Also handles music-page wrapped in fig-block (Berklee pattern).'''
    result = []
    pos    = 0

    for hdr_m in _HDR_OPEN_RE.finditer(text):
        if hdr_m.start() < pos:
            continue

        # Idempotency: skip if this header is already inside a music-page
        before = text[max(0, hdr_m.start() - 60):hdr_m.start()]
        if _PAGE_OPEN_RE.search(before):
            continue

        hdr_end   = _find_div_end(text, hdr_m.start())
        hdr_block = text[hdr_m.start():hdr_end]

        # Skip whitespace after header
        scan = hdr_end
        while scan < len(text) and text[scan] in ' \t\r\n':
            scan += 1

        # Skip optional fig-block wrapper (Berklee wraps first page in fig-block)
        fig_start = None
        fig_end   = None
        fb = _FIG_OPEN_RE.match(text, scan)
        if fb:
            fig_start = scan
            fig_end   = _find_div_end(text, scan)
            # Peek inside the fig-block for the music-page/music
            inner_scan = fb.end()
            while inner_scan < fig_end and text[inner_scan] in ' \t\r\n':
                inner_scan += 1
            scan = inner_scan   # point inside the fig-block

        # Require a music-page (or promotable div.music without id) immediately
        pm = _PAGE_OPEN_RE.match(text, scan)
        if not pm:
            # Also accept div.music without id= (will be promoted by step 8)
            mu = _MUSIC_NO_ID.match(text, scan)
            if mu and 'id=' not in mu.group().lower():
                pm = mu
        if not pm:
            continue # no score page follows, leave unchanged

        page_end   = _find_div_end(text, scan)
        page_block = text[scan:page_end]

        # Extract images
        img_tags = _IMG_TAG_RE.findall(page_block)
        # Wrap img in centering table against inline-style inheritance
        img_html = ''.join(
            '<table width="100%" border="0" cellpadding="0" cellspacing="0">'
            '<tr><td align="center">' + tag + '</td></tr></table>'
            for tag in img_tags
        )

        # Clean header
        hdr_block = normalize_credits(hdr_block).replace('\r\n', '\n')
        hdr_block = _IMG_TAG_RE.sub('', hdr_block)

        # advance scan past the page (and past any enclosing fig-block)
        scan = page_end
        if fig_end is not None and scan < fig_end:
            scan = fig_end      # consume the fig-block close too
        while scan < len(text) and text[scan] in ' \t\r\n':
            scan += 1

        # Optional trailing rights (Hymns: p.rights after the first music-page)
        rights_html = ''
        rm = _RIGHTS_LOOSE_RE.match(text, scan)
        if rm:
            rights_html = rm.group().strip()
            scan = rm.end()

        # keep_rights suppresses the footer on header-heavy title pages (step 7).
        # This is a layout decision independent of step 9 (FOOTER_FIRST): even if
        # step 9 would later move the footer to the last page, injecting it here
        # when the header is already dense produces one pass of bad layout first.
        # is_header_heavy acts as a pre-filter so step 9 never sees it on this page.
        keep_rights = rights_html and not is_header_heavy(hdr_block)

        footer_block = (
            '\n' + _normalize_footer(rights_html)
            if keep_rights else ''
        )
        merged = (
            '<div class="music-page">\n'
            + hdr_block + '\n'
            + (img_html + '\n' if img_html else '')
            + footer_block
            + '\n</div>\n'
        )

        # normalize boundary spacing once
        chunk = text[pos:hdr_m.start()].rstrip()
        result.append(chunk + '\n')
        result.append(merged)
        pos = scan

    result.append(text[pos:])
    return ''.join(result)


# ---------------------------------------------------------------------------
# Step 8: promote_continuation_pages
# ---------------------------------------------------------------------------
# Converts div.music -> div.music-page for score continuation pages.
# Rule: a div.music with NO id= that immediately follows a music-page
# (with only whitespace/break divs between) is a continuation score page.
# Stops promoting when a music-header or non-music element is reached.
# Idempotent (already-promoted pages match music-page, not music).

_PROMO_MUSIC_RE  = _re.compile(r'<div\s+([^>]*)class="music"([^>]*)>', _re.IGNORECASE)
_PROMO_PAGE_RE   = _re.compile(r'<div[^>]*class="music-page"[^>]*>', _re.IGNORECASE)
_PROMO_HEADER_RE = _re.compile(r'<div[^>]*class="music-header"[^>]*>', _re.IGNORECASE)
_PROMO_BREAK_RE  = _re.compile(r'<div[^>]*/>', _re.IGNORECASE)   # self-closing divs incl. break


def promote_continuation_pages(text: str) -> str:
    '''After each music-page, promote immediately following div.music (no id)
    siblings to music-page until a music-header or non-music element appears.'''
    result = []
    pos = 0

    while pos < len(text):
        # Find next music-page opening tag
        mp = _PROMO_PAGE_RE.search(text, pos)
        if not mp:
            result.append(text[pos:])
            break

        # Emit everything up to and including the complete music-page block
        mp_end = _find_div_end(text, mp.start())
        result.append(text[pos:mp_end])
        pos = mp_end

        # Now scan forward promoting div.music siblings
        while pos < len(text):
            # Skip whitespace
            ws_end = pos
            while ws_end < len(text) and text[ws_end] in ' \t\r\n':
                ws_end += 1

            # Self-closing div (e.g. <div class="break"/>), emit and continue
            sc = _PROMO_BREAK_RE.match(text, ws_end)
            if sc:
                result.append(text[pos:sc.end()])
                pos = sc.end()
                continue

            # Stop if we hit a music-header
            if _PROMO_HEADER_RE.match(text, ws_end):
                break

            # Promote div.music with no id= to music-page
            mu = _PROMO_MUSIC_RE.match(text, ws_end)
            if mu:
                combined_attrs = mu.group(1) + mu.group(2)
                if 'id=' not in combined_attrs.lower():
                    mu_end = _find_div_end(text, ws_end)
                    inner  = text[mu.end():mu_end - len('</div>')]
                    result.append(text[pos:ws_end])   # emit whitespace
                    result.append('<div class="music-page">')  # promoted
                    result.append(inner)
                    result.append('</div>')
                    pos = mu_end
                    continue
                # Has id= not a continuation page, stop promoting
                break

            # Anything else, stop promoting
            break

    return ''.join(result)


# ---------------------------------------------------------------------------
# Step 9: move_footer_to_page
# ---------------------------------------------------------------------------
# Moves the music-footer to either the first or last music-page of each song,
# controlled by the FOOTER_FIRST module constant (default: False = last page).
#
# Idempotent:
#   - footer already on target page -> no extraction needed, loop does nothing
#   - footer on non-target page     -> extracted, re-injected into target page
#   - no footer anywhere            -> no-op
#   - single-page song              -> first page IS the last page, no extraction
#
# Runs after promote_continuation_pages (step 8) so all continuation pages are
# already div.music-page before this pass inspects them.

_RIGHTS_LINES_RE = _re.compile(
    r'<p[^>]*class="rights"[^>]*>(.*?)</p>',
    _re.DOTALL | _re.IGNORECASE,
)

_FOOTER_WRAPPER_RE = _re.compile(
    r'<div[^>]*class="music-footer"[^>]*>(.*?)</div>',
    _re.DOTALL | _re.IGNORECASE,
)

_FOOTER_OPEN_RE = _re.compile(r'<div[^>]*class="music-footer"[^>]*>', _re.IGNORECASE)

def _normalize_p(raw: str) -> str:
    '''Flatten one fragment (post-br-split) to a clean string.'''
    t = _re.sub(r'<[^>]+>', ' ', raw)
    t = t.replace('&nbsp;', ' ').replace('\xa0', ' ')
    t = _re.sub(r'\s+', ' ', t).strip()
    t = _re.sub(r'\s*\(Renewed(?:\s+\d{4})?\)\s*', ' ', t, flags=_re.IGNORECASE)
    t = _re.sub(r'\s+', ' ', t).strip()
    return t

def _shorten_copyright(line: str) -> str:
    '''Cut at the first admin tail marker; keeps year + publisher name only.'''
    return _re.split(
        r'\s+(?:c/o|all\s+rights|administered)\b',
        line,
        flags=_re.IGNORECASE,
    )[0].strip(' ,')

def _strip_shared_suffix(a: str, b: str) -> tuple[str, str]:
    '''Remove trailing words shared between a and b from b.
    Requires >= 4 shared words to avoid trimming short coincidences.'''
    a_words = a.split()
    b_words = b.split()
    i, max_len = 1, min(len(a_words), len(b_words))
    while i <= max_len and a_words[-i].lower() == b_words[-i].lower():
        i += 1
    shared = i - 1
    if shared >= 4:
        b_words = b_words[:-shared]
    return a, ' '.join(b_words).strip()

def _classify(line: str) -> str | None:
    '''Return 'arrangement', 'copyright', or None.
    Signal anchors only: © or year presence, no noise-list needed.'''
    has_year = bool(_re.search(r'\b(19|20)\d{2}\b', line))
    has_c    = '©' in line
    is_arr   = bool(_re.search(r'\barrangement\b', line, _re.IGNORECASE))

    if is_arr and has_year:         # arrangement + year (© optional but present in all real data)
        return 'arrangement'
    if has_c and has_year:          # bare © + year (covers "© 1972 SCHWARTZ" style)
        return 'copyright'
    return None                     # noise: admin lines, "Copyright Renewed", etc.

def _normalize_footer(footer_html: str) -> str:
    '''
    Classify-and-pick pipeline:
      1. normalize  -- flatten each <p> to a plain string
      2. classify   -- tag each line as 'arrangement', 'copyright', or None
      3. pick       -- keep first of each useful class; discard None lines
      4. join       -- one <p class="rights"> per selected line
    '''
    # Unwrap existing footer div if present
    m = _FOOTER_WRAPPER_RE.search(footer_html)
    inner = m.group(1) if m else footer_html

    # Split each <p> on <br> first, then normalize fragments
    lines = []
    for raw in _RIGHTS_LINES_RE.findall(inner):
        for part in _re.split(r'</?br\s*/?>', raw, flags=_re.IGNORECASE):
            norm = _normalize_p(part)
            if norm:
                lines.append(norm)

    if not lines:
        return footer_html  # No <p> lines found: return original unchanged.
        # (Caller's `if collected_footer` guard prevents this path on empty input.)

    # Classify and pick first of each class
    copyright_line = None
    arrangement_line = None
    for line in lines:
        t = _classify(line)
        if t == 'copyright' and copyright_line is None:
            copyright_line = _shorten_copyright(line) # Shorten copyright only
        elif t == 'arrangement' and arrangement_line is None:
            arrangement_line = line

    # Strip shared suffix from arrangement line if both present
    if copyright_line and arrangement_line:
        copyright_line, arrangement_line = _strip_shared_suffix(
            copyright_line, arrangement_line
        )

    selected = [l for l in (copyright_line, arrangement_line) if l]
    if not selected:
        return '' # Lines found but were classified as noise. Remove footer

    # Join into single line with middle dot
    return (
        '<div class="music-footer">'
        + '<p class="rights">' + ' \u00b7 '.join(selected) + '</p>'
        + '</div>'
    )

def move_footer_to_page(text: str, first: bool=False) -> str:
    result = []
    pos    = 0

    while pos < len(text):
        # Find the next music-page
        mp = _PAGE_OPEN_RE.search(text, pos)
        if not mp:
            result.append(text[pos:])
            break

        # Emit everything before this music-page unchanged
        result.append(text[pos:mp.start()])

        # Collect all consecutive music-page blocks for this song.
        # Stop when we hit a music-header (next song's title page) or no more music-pages.
        pages   = []   # list of (page_start, page_end) absolute positions
        scan    = mp.start()

        while True:
            pm = _PAGE_OPEN_RE.match(text, scan)
            if not pm:
                break
            page_end = _find_div_end(text, scan)
            pages.append((scan, page_end))
            scan = page_end
            # skip whitespace between pages
            while scan < len(text) and text[scan] in ' \t\r\n':
                scan += 1
            # stop if next thing is a music-header (belongs to next song)
            if _PROMO_HEADER_RE.match(text, scan):
                break

        # For each page, extract any music-footer from its content.
        # Accumulate extracted footer html; rebuild page content without it.
        collected_footer = ''
        page_texts       = []
        target_idx = 0 if first else len(pages)-1

        for i, (pstart, pend) in enumerate(pages):
            raw = text[pstart:pend]
            fm  = _FOOTER_OPEN_RE.search(raw)

            if fm and i != target_idx:
                # Footer found on non-target page. Extract it
                footer_abs_start = pstart + fm.start()
                footer_abs_end   = _find_div_end(text, footer_abs_start)
                footer_html      = text[footer_abs_start:footer_abs_end]
                collected_footer = footer_html # Last one wins if multiple

                # Remove footer from page
                inner_before = raw[:fm.start()].rstrip()
                inner_after  = raw[footer_abs_end - pstart:].lstrip('\r\n')
                # inner_after begins at the footer end; typically only contains
                # the page's closing </div>. If additional content follows the
                # footer, it is preserved as-is (only leading newlines stripped).
                page_texts.append(inner_before + '\n' + inner_after)
            else:
                page_texts.append(raw)

        # Inject collected footer into target page, just before its closing </div>
        target = page_texts[target_idx]
        close_idx = target.rfind('</div>')
        normalized_footer = _normalize_footer(collected_footer) if collected_footer else ''
        page_texts[target_idx] = (
            target[:close_idx].rstrip()
            + ('\n' + normalized_footer + '\n' if normalized_footer else '\n')
            + target[close_idx:]
        )

        result.extend(page_texts)
        pos = scan

    return ''.join(result)


# ---------------------------------------------------------------------------
# Step 10: wrap_figure_blocks
# ---------------------------------------------------------------------------
# Wraps each inline music figure (musicL, musicR, music90) and its immediately
# following caption (p.FIG, p.fig, p.photo-credit) in a div.fig-block so they
# paginate together. Idempotent: skips figures already inside a fig-block.

_FIGURE_RE = _re.compile(
    r'(<div\b[^>]*class="music(?:L|R|90)?"[^>]*>'
    r'(?:(?!<div|</div>).)*?'
    r'</div>)'
    r'(\s*<p\b[^>]*class="(?:FIG|fig|photo-credit)"[^>]*>.*?</p>)',
    _re.DOTALL | _re.IGNORECASE,
)


def wrap_figure_blocks(text: str) -> str:
    def _wrap(m: _re.Match) -> str:
        before = text[max(0, m.start() - 60):m.start()]
        if 'fig-block' in before:
            return m.group(0)
        return f'<div class="fig-block">{m.group(0)}</div>'
    return _FIGURE_RE.sub(_wrap, text)


# ---------------------------------------------------------------------------
# Step 11: merge_split_headers  (safety)
# ---------------------------------------------------------------------------
# Merges two consecutive div.music-header blocks where the first contains ONLY
# a single h1.title (a split title line) and the second is the continuation.
# Primary merging happens in normalize_titles (step 2); this is a fallback.
# Safe: only merges when first header is exactly one h1 with no other content.
# Must run LAST after all wrapping and normalization.

_SPLIT_HEADER_RE = _re.compile(
    r'<div[^>]*class="music-header"[^>]*>\s*'
    r'(<h1[^>]*class="title"[^>]*>.*?</h1>)\s*'         # group 1: first title only
    r'</div>\s*'
    r'<div[^>]*class="music-header"[^>]*>\s*'
    r'(<h1[^>]*class="title"[^>]*>.*?</h1>)'            # group 2: second title
    r'(.*?)</div>',                                     # group 3: rest of second header
    _re.DOTALL | _re.IGNORECASE,
)


def merge_split_headers(text: str) -> str:
    '''Merge two consecutive music-header blocks where the first has only a title.
    Converts: <h1>Part A</h1></div><div...><h1>Part B</h1>rest</div>
    Into:     <div class="music-header"><h1>Part A<br/>Part B</h1>rest</div>
    Safe: only merges when first header contains exactly one h1 and nothing else.'''
    def _merge(m: _re.Match) -> str:
        first_inner  = _re.sub(r'</?h1[^>]*>', '', m.group(1), flags=_re.IGNORECASE)
        second_inner = _re.sub(r'</?h1[^>]*>', '', m.group(2), flags=_re.IGNORECASE)
        return (
            '<div class="music-header">\n'
            + '<h1 class="title">' + first_inner.strip() + '<br/>' + second_inner.strip() + '</h1>'
            + m.group(3)
            + '</div>'
        )
    return _SPLIT_HEADER_RE.sub(_merge, text)


# ---------------------------------------------------------------------------
# Master XHTML rewriter
# ---------------------------------------------------------------------------

def rewrite_xhtml(content: bytes) -> bytes:
    text = content.decode('utf-8', errors='replace')
    text = scrub_inline_overrides(text)
    text = unwrap_anon_section_divs(text)           # 0. dissolve bare <div> wrappers in <section>
    text = rewrite_section_music(text)              # 1. sections -> divs; song-start unwrapped
    text = normalize_titles(text)                   # 2. title variants -> h1.title + merge siblings
    text = normalize_image_blocks(text)             # 3. dissolve song-header-block/illustype FIRST
    text = normalize_music_divs(text)               # 4. music1/music90/music[id] -> music-page
    text = wrap_music_header(text)                  # 5. inject music-header around title block
    text = move_audio_before_header(text)           # 6. audio before header (must precede merge)
    text = merge_header_and_first_page(text)        # 7. merge header+image+rights into one music-page
    text = promote_continuation_pages(text)         # 8. div.music after music-page -> music-page
    text = move_footer_to_page(text, FOOTER_FIRST)  # 9. footer -> first or last page (see FOOTER_FIRST)
    text = wrap_figure_blocks(text)                 # 10. Berklee: figure + caption together
    text = merge_split_headers(text)                # 11. safety-net for residual split headers
    return text.encode('utf-8')


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def is_image(name: str) -> bool:
    return name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))

def is_cover(name: str) -> bool:
    return 'cover' in name.lower()

def enhance_image(data: bytes) -> bytes:
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        print('IMG SKIP: Invalid image')
        return data

    tmp_in  = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp_out = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp_in_path  = tmp_in.name
    tmp_out_path = tmp_out.name
    tmp_in.close()
    tmp_out.close()

    try:
        with open(tmp_in_path, 'wb') as f:
            f.write(data)
        cmd = [
            'magick', tmp_in_path,
            '-colorspace', 'Gray',
            '-auto-level',
            '-contrast-stretch', '0',
            '-white-threshold', '85%',
            '-fuzz', '10%', '-trim', '+repage',
            '-threshold', '60%',
            '-unsharp', '0x0.8+0.8+0.02',
            '-strip',
            '-define', 'png:compression-level=9',
            '-define', 'png:compression-filter=5',
            '-define', 'png:compression-strategy=1',
            tmp_out_path,
        ]
        subprocess.run(cmd, check=True)
        with open(tmp_out_path, 'rb') as f:
            return f.read()
    except subprocess.CalledProcessError as e:
        print(f'ImageMagick failed: {e}')
        return data
    finally:
        try:
            os.remove(tmp_in_path)
            os.remove(tmp_out_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# EPUB processing
# ---------------------------------------------------------------------------

def _is_fixed_layout_epub(z: zipfile.ZipFile) -> bool: # for detection only
    '''Return True if any CSS file uses position:absolute at a fixed 700px width.'''
    for name in z.namelist():
        if not name.lower().endswith('.css'):
            continue
        css = z.read(name).decode('utf-8', errors='replace')
        if (('position: absolute' in css or 'position:absolute' in css) and
                ('width: 700px' in css or 'width:700px' in css)):
            return True
    return False

def process_epub(src: str, dst: str, process_images: bool) -> None:
    total = 0
    saved_bytes = 0

    with zipfile.ZipFile(src, 'r') as zin:
        if _is_fixed_layout_epub(zin): # exit instead of override
            # Fixed-layout epubs use position:absolute with pixel-exact coordinates.
            # No CSS override can reflow them reliably. Text overlays break entirely
            sys.exit('Error: fixed-layout epub detected -- not supported')

        with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
            zout.writestr(
                zipfile.ZipInfo('mimetype'),
                zin.read('mimetype'),
                compress_type=zipfile.ZIP_STORED,
            )

            for item in zin.infolist():
                if item.filename == 'mimetype':
                    continue

                data = zin.read(item.filename)
                name = item.filename

                if name.lower().endswith('.css'):
                    print(f'  CSS      {name}')
                    data = FIXED_CSS.encode('utf-8')

                elif name.lower().endswith(('.xhtml', '.html')):
                    print(f'  XHTML    {name}')
                    data = fix_viewport(data)
                    data = rewrite_xhtml(data)

                elif process_images and is_image(name) and HAS_MAGICK:
                    orig = len(data)
                    if is_cover(name):
                        print(f'  IMG SKIP {os.path.basename(name):30s} (cover)')
                    else:
                        try:
                            data = enhance_image(data)
                            diff = orig - len(data)
                            saved_bytes += diff
                            total += 1
                            print(f'  IMG      {os.path.basename(name):30s} '
                                  f'{orig//1024:4d}KB -> {len(data)//1024:4d}KB  '
                                  f'({diff//1024:+d}KB)')
                        except Exception as e:
                            print(f'  IMG SKIP {name}: {e}')

                zout.writestr(item, data)

    if process_images and total:
        print(f'\n  Images processed: {total}')
        print(f'  Total saved:      {saved_bytes//1024}KB')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Normalize epub structure and images for reflowable reading.'
    )
    parser.add_argument('input', help='Input .epub file')
    parser.add_argument('output', nargs='?', help='Output .epub (default: input_fixed.epub)')
    parser.add_argument(
        '--no-images', action='store_true',
        help='Skip image processing (CSS + structure fix only)',
    )
    args = parser.parse_args()

    src = args.input
    if not os.path.isfile(src):
        sys.exit(f'Error: file not found: {src}')

    base = os.path.splitext(src)[0]
    dst = args.output or f'{base}_fixed.epub'

    if os.path.abspath(src) == os.path.abspath(dst):
        sys.exit('Error: input and output paths are the same')

    print(f'Input:  {src}')
    print(f'Output: {dst}')
    if args.no_images:
        img_status = 'skip (--no-images)'
    elif not HAS_MAGICK:
        img_status = 'skip (ImageMagick not found)'
    else:
        img_status = 'enhance (grayscale, auto-level, sharpen)'
    print(f'Images: {img_status}')
    print()

    process_epub(src, dst, process_images=not args.no_images)
    print(f'\nDone -> {dst}')


if __name__ == '__main__':
    main()
