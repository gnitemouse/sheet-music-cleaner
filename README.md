# sheet-music-cleaner

**v1.0** -- Tools for cleaning and digitizing scanned sheet music PDFs.

Music score ePub file formatter to improve readability across eReader devices.

---

## Scripts

### `clean_sheet_music.ps1`

Cleans a scanned sheet music PDF using ImageMagick. Rasterizes each page to
a high-resolution grayscale TIFF, then auto-levels and sharpens. Pass `-final`
to also apply level adjustment and deskew for a print-ready result.

Without `-final`, output is a set of TIFFs you can review, edit, or process
with an external tool (such as ScanTailor Advanced) before compiling.

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

### `compile_sheet_music.ps1`

Compiles a folder of TIFF pages into a single PDF using ImageMagick. Designed
to consume the output of `clean_sheet_music.ps1`, but works with any folder of
TIFFs.

Tries compression methods in order from smallest to most compatible:
`fax (CCITT Group 4)` → `threshold + fax` → `lzw`

If the input directory contains an `out/` subdirectory, files are read from
there instead. This lets you manually curate pages before compiling.

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

Normalizes epub files for reflowable reading on eReaders and PDF viewers.
Handles several source structures commonly found in music epub publications
and rewrites them into a consistent, reflowable structure. Also enhances
embedded score images (grayscale, auto-level, sharpen, compress).

See the file header for the full list of supported source structures and the
rewrite pipeline.

**Usage**

```bash
python epub_fix_format.py input.epub
python epub_fix_format.py input.epub output.epub
python epub_fix_format.py input.epub --no-images   # skip image processing
```

**Requirements:** Python 3.8+, Pillow (`pip install Pillow`), ImageMagick
(optional, for image enhancement)

---

## Typical workflow

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

## Why PowerShell for the sheet music scripts?

`clean_sheet_music.ps1` and `compile_sheet_music.ps1` wrap ImageMagick's
command-line interface and are primarily filesystem and process orchestration.
PowerShell is a natural fit on Windows for that role: no dependencies beyond
ImageMagick itself, and the scripts run directly from a terminal without a
Python install.

`epub_fix_format.py` is in Python because it parses and rewrites binary zip
archives and XML, where Python's standard library and Pillow are a better fit
than shell scripting.

---

## Requirements summary

| Tool | Used by | Notes | Install |
|------|---------|-------|---------|
| ImageMagick | all scripts | required | https://imagemagick.org |
| Python 3.8+ | `epub_fix_format.py` | required | https://python.org |
| Pillow | `epub_fix_format.py` | required | `pip install Pillow` |
| pdftk | merging PDFs | (optional) better than magick for large files | https://www.pdflabs.com/tools/pdftk-the-pdf-toolkit/ |
| ScanTailor Advanced | manual cleanup | (optional) external page editor | https://github.com/4lex4/scantailor-advanced |

---

## License

MIT License. See [LICENSE](LICENSE).
