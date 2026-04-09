# clean_sheet_music.ps1
# author: Daisy Jane @dayzl
#
# Cleans scanned sheet music PDFs using ImageMagick.
# Rasterizes each page to a high-resolution grayscale TIFF, then auto-levels
# and sharpens. With -final, also applies level adjustment and deskew for
# a print-ready result.
#
# Two-pass workflow:
#   Preview  (no flag)  -- fast pass; outputs clean_*.tif for review.
#                          Useful for checking results before committing to
#                          the slower deskew step.
#   Final    (-final)   -- full pass; applies level adjustment and deskew,
#                          then outputs <base>_*.tif and removes temp files.
#
# Output directory: clean_<base>/
#   Preview output:  clean_<base>/clean_*.tif
#   Final output:    clean_<base>/<base>_*.tif
#
# Usage:
#   .\clean_sheet_music.ps1 input.pdf
#   .\clean_sheet_music.ps1 input.pdf -final
#
# Requirements: ImageMagick (magick must be on PATH)

param(
    [Parameter(Mandatory=$true)]
    [string]$InputPdf,
    [switch]$final
)

$base = [System.IO.Path]::GetFileNameWithoutExtension($InputPdf)
$outDir = "clean_${base}"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Temp and output file patterns (%02d is expanded by ImageMagick per page)
$tmp1  = Join-Path $outDir 'tmp1_%02d.tif'
$tmp3  = Join-Path $outDir 'tmp3_%02d.tif'
$clean = Join-Path $outDir 'clean_%02d.tif'
$output = Join-Path $outDir "${base}_%02d.tif"

# Step 1: Rasterize at 400 dpi, convert to grayscale, strip alpha
Write-Host 'Step 1: Rasterizing PDF...'
magick -density 400 $InputPdf -colorspace Gray -alpha remove $tmp1

# Step 2: Normalize contrast and apply mild unsharp-mask sharpening
Write-Host 'Step 2: Auto-level and sharpen...'
$tmp1Files = Get-ChildItem (Join-Path $outDir 'tmp1_*.tif') | Sort-Object Name
magick @($tmp1Files.FullName) -auto-level -sharpen 0x1 $clean

if ($final) {
    # Step 3: Narrow the tonal range to push near-white to white and
    #         near-black to black, improving print contrast
    Write-Host 'Step 3: Level adjustment...'
    $cleanFiles = Get-ChildItem (Join-Path $outDir 'clean_*.tif') | Sort-Object Name
    magick @($cleanFiles.FullName) -level 20%,70% $tmp3

    # Step 4: Correct page rotation introduced by scanning
    Write-Host 'Step 4: Deskew...'
    $tmp3Files = Get-ChildItem (Join-Path $outDir 'tmp3_*.tif') | Sort-Object Name
    magick @($tmp3Files.FullName) -deskew 25% +repage $output

    Write-Host 'Cleaning up temp files...'
    Remove-Item (Join-Path $outDir 'tmp1_*.tif')
    Remove-Item (Join-Path $outDir 'tmp3_*.tif')
} else {
    Write-Host 'Skipping Steps 3 & 4 (use -final to enable).'
    Remove-Item (Join-Path $outDir 'tmp1_*.tif')
}

Write-Host "Done. Output in: $outDir"
