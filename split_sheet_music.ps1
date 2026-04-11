# split_sheet_music.ps1
# author: Daisy Jane @dayzl
#
# Splits a PDF into individual TIFF pages using ImageMagick.
# Each page is rasterized to grayscale at the given density (default: 400 dpi).
#
# Unlike clean_sheet_music.ps1, no image processing is applied; pages are
# rasterized as-is. This is useful if the source PDF is already clean, or
# if you want to inspect raw pages.
#
# Output goes into clean_<base>/ directory so that compile_sheet_music.ps1
# can pick it up directly without any extra arguments:
#   .\split_sheet_music.ps1 input.pdf
#   .\compile_sheet_music.ps1 input.pdf
#
# If you want to curate or reorder pages before compiling, move your keepers
# into clean_<base>/out/ so that compile_sheet_music.ps1 will read that subfolder.
#
# Output filenames follow pattern <base>_NNN.tif pattern (zero-padded, 3 digits).
#
# Usage:
#   .\split_sheet_music.ps1 input.pdf
#   .\split_sheet_music.ps1 input.pdf -Density 600
#
# Requirements: ImageMagick (magick must be on PATH)

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$InputPdf,

    # Rasterization density in DPI. 400 is a good default
    [Parameter(Mandatory=$false)]
    [int]$Density = 400
)

# Validate input
if (-not ($InputPdf -match '\.pdf$')) {
    Write-Host "Input must be a .pdf file: $InputPdf"
    exit 1
}

if (-not (Test-Path $InputPdf)) {
    Write-Host "File not found: $InputPdf"
    exit 1
}

# Get base name and output name
# Create output directory next to source, not relative to current working directory
$InputPdf = Resolve-Path $InputPdf
$base = [System.IO.Path]::GetFileNameWithoutExtension($InputPdf)
$pdfDir = [System.IO.Path]::GetDirectoryName($InputPdf)
$outDir = Join-Path $pdfDir "clean_${base}"

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Output path pattern: clean_<base>/<base>_NNN.tif
# ImageMagick expands %03d to a zero-padded three-digit page index (0-based).
# Rename to 1-based after rasterization so page numbering is intuitive.
$outPattern = Join-Path $outDir "${base}_%03d.tif"

Write-Host "Splitting ${InputPdf} at ${Density} dpi -> ${outDir}\"

# Rasterize all pages to grayscale TIFFs at the requested density.
# -density must come before the input file to set the decode resolution
# -colorspace Gray keeps files small and is correct for sheet music
magick -density $Density $InputPdf -colorspace Gray $outPattern

if ($LASTEXITCODE -ne 0) {
    Write-Host 'ImageMagick failed. Check that magick is on PATH and the input PDF is valid.'
    exit 1
}

# ImageMagick starts numbering at 0. Re-number from 1 (_001, _002, ...)
# Sort descending so we rename the last page first, where
# e.g. _001 already exists when we try to rename _000 -> _001.
$pages = Get-ChildItem (Join-Path $outDir '*.tif') | Sort-Object Name -Descending

$index = $pages.Count
foreach ($page in $pages) {
    $newName = "${base}_$($index.ToString('000')).tif"
    $newPath = Join-Path $outDir $newName
    if ($page.FullName -ne $newPath) {
        Rename-Item -Path $page.FullName -NewName $newName
    }
    $index--
}

$count = $pages.Count
Write-Host "Done. $count page(s) written to ${outDir}\"
