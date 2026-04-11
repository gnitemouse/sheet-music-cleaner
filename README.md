# sheet-music-cleaner

**v1.0** -- Tools for cleaning and digitizing scanned sheet music;
ePub file formatter to improve readability across eReader devices.

---

## Scripts

### `clean_sheet_music.ps1`

Scanned sheet music PDFs are often low contrast, slightly rotated, and not
suitable for printing or reading on screen. This script rasterizes each page
to a high-resolution grayscale TIFF, then auto-levels and sharpens.

Pass `-final` to also apply level adjustment and deskew, producing clean pages
ready to compile into a PDF. Without `-final`, you get a set of TIFFs to review
or edit with an external tool such as ScanTailor Advanced before compiling.

| Mode | Flag | Output |
|------|------|--------|
| Review | *(none)* | `clean_<base>/clean_*.tif` |
| Final | `-final` | `clean_<base>/<base>_*.tif` |

**Usage**

```powershell
.\clean_sheet_music.ps1 input.pdf          # review output
.\clean_sheet_music.ps1 input.pdf -final   # level adjust + deskew
```

**Requirements:** ImageMagick (`magick` on PATH)

---

### `split_sheet_music.ps1`

Some PDFs are already clean enough to compile directly.
This script splits such a PDF into individual TIFF pages so they can be
reviewed, reordered, or compiled immediately.

Unlike `clean_sheet_music.ps1`, no image processing is applied. Pages are
rasterized to grayscale TIFFs at the requested density (default: 400 dpi).

Output goes into directory `clean_<base>/`, which can be accepted by
`compile_sheet_music.ps1` with no extra arguments.
If you want to curate or reorder pages before compiling, move
keepers into `clean_<base>/out/`.

| Argument | Default | Description |
|----------|---------|-------------|
| `InputPdf` | *(required)* | Path to the source PDF |
| `-Density` | `400` | Rasterization DPI; increase to `600` for fine print |

**Usage**

```powershell
.\split_sheet_music.ps1 input.pdf               # split at 400 dpi (default)
.\split_sheet_music.ps1 input.pdf -Density 300  # split at 300 dpi
```

Then compile directly:

```powershell
.\compile_sheet_music.ps1 input.pdf
```

**Requirements:** ImageMagick (`magick` on PATH)

---

### `compile_sheet_music.ps1`

Compiles a folder of TIFF pages into a single PDF. Takes the output of
`clean_sheet_music.ps1` directly, but works with any folder of TIFFs.

Automatically selects the best available compression for the input, falling
back to more compatible methods if needed. If the input directory contains
an `out/` subdirectory, files are read from there instead, which lets you
curate or reorder pages before compiling.

**Usage**

```powershell
# From a PDF name (looks for clean_<base>/ directory)
.\compile_sheet_music.ps1 input.pdf

# With explicit output path
.\compile_sheet_music.ps1 input.pdf compiled\output.pdf

# From a folder directly
.\compile_sheet_music.ps1 clean_myscore\
```

**Merging multiple compiled PDFs**

```powershell
# pdftk -- recommended; concatenates without re-rasterizing
pdftk file1.pdf file2.pdf cat output merged.pdf

# ImageMagick -- works but re-rasterizes, which may increase file size
magick file1.pdf file2.pdf merged.pdf
```

**Requirements:** ImageMagick (`magick` on PATH); pdftk (optional, for merging)

---

### `epub_fix_format.py`

Music epub files often display poorly on eReaders. Score images overflow the
screen, titles and credits are misaligned, or the layout breaks on reflowable
devices. This script rewrites the epub's internal structure into a clean,
consistent format that works across devices and viewers such as Okular and
Onyx Boox.

It normalizes several source structures commonly found in music epub
publications into a standard reflowable layout: one page per score image,
with titles, subtitles, credits, and rights blocks correctly positioned.
Safe to re-run on already-processed files.

Two processing modes:

| Mode | What it does |
|------|--------------|
| Default | Fixes layout and structure; also enhances embedded score images (grayscale, auto-level, sharpen, compress) |
| `--no-images` | Fixes layout and structure only; leaves images untouched |

Use `--no-images` if your images are already clean, or to check the
structural output before committing to a full image pass.

**Usage**

```bash
python epub_fix_format.py input.epub
python epub_fix_format.py input.epub output.epub
python epub_fix_format.py input.epub --no-images
```

See the file header for the full list of supported source structures and the
rewrite pipeline.

**Requirements:** Python 3.8+, Pillow (`pip install Pillow`), ImageMagick
(optional, for image enhancement)

---

## Typical workflow

If your source PDF is already clean (good contrast, straight pages), use
`split_sheet_music.ps1` to go straight to compile:

```
input.pdf
    |
    v
split_sheet_music.ps1          # rasterize pages, no processing
    |
    v
clean_<base>/<base>_*.tif      # review or reorder; move keepers to out/
    |
    v
compile_sheet_music.ps1        # compile TIFFs to PDF
    |
    v
<base>.pdf
```

For scanned or low-quality PDFs, use `clean_sheet_music.ps1` instead:

```
input.pdf
    |
    v
clean_sheet_music.ps1          # rasterize, auto-level, sharpen
    |
    v
clean_<base>/clean_*.tif       # review output
    |
    |  (optional) edit pages manually, move keepers to out/
    |
    v
clean_sheet_music.ps1 -final   # level adjust + deskew
    |
    v
clean_<base>/<base>_*.tif
    |
    v
compile_sheet_music.ps1        # compile TIFFs to PDF
    |
    v
<base>.pdf
```

> **External tools:** [ScanTailor Advanced](https://github.com/4lex4/scantailor-advanced)
> is useful for manual page cleanup between steps. For merging multiple
> compiled PDFs, [pdftk](https://www.pdflabs.com/tools/pdftk-the-pdf-toolkit/)
> preserves quality better than ImageMagick.

---

## Requirements summary

| Tool | Used by | Notes | Install |
|------|---------|-------|---------|
| ImageMagick | all scripts | required by `.ps1` scripts; optional for `epub_fix_format.py` | https://imagemagick.org |
| Python 3.8+ | `epub_fix_format.py` | required | https://python.org |
| Pillow | `epub_fix_format.py` | required | `pip install Pillow` |
| pdftk | merging PDFs | (optional) better than magick for large files | https://www.pdflabs.com/tools/pdftk-the-pdf-toolkit/ |
| ScanTailor Advanced | manual cleanup | (optional) external page editor | https://github.com/4lex4/scantailor-advanced |

---

## License

MIT License. See [LICENSE](LICENSE).
