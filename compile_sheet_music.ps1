# compile_sheet_music.ps1
# author: Daisy Jane @dayzl
#
# Compiles a folder of TIFF pages into a single PDF using ImageMagick and pdftk.
# Detects colorspace per page and applies the appropriate compression:
#   Gray         -> fax (CCITT Group 4) -> threshold + fax -> lzw
#   RGB / sRGB   -> jpeg (quality 85)
#
# Flags -bw and -grayscale bypass colorspace detection and force all pages through
# the B&W (fax chain) or grayscale (lzw) path respectively. If both are set, -bw wins.
#
# Input resolution:
#   PDF    -- looks for a clean_<base>/ directory produced by clean_sheet_music.ps1,
#             preferring the clean_<base>/out/ subdirectory if it exists.
#   Folder -- uses the folder directly, preferring its out/ subdirectory if present.
#
# Output: <base>.pdf next to the TIFF source directory (or the path given as $OutFile)
#
# Usage:
#   .\compile_sheet_music.ps1 input.pdf
#   .\compile_sheet_music.ps1 input.pdf output.pdf
#   .\compile_sheet_music.ps1 clean_myscore\
#   .\compile_sheet_music.ps1 input.pdf -bw
#   .\compile_sheet_music.ps1 input.pdf -grayscale
#
# Merge multiple PDFs after compiling:
#   pdftk file1.pdf file2.pdf cat output merged.pdf (recommended)
#   magick file1.pdf file2.pdf merged.pdf (works, but re-rasterizes)
# Note: pdftk preserves quality exactly; magick re-rasterizes, which may increase file size.
#
# Requirements: ImageMagick (magick must be on PATH)
#               pdftk (recommended; magick is used as fallback if pdftk is absent)
#               Note: magick fallback re-rasterizes pages, which may increase file size.

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$InFile,

    [Parameter(Mandatory=$false, Position=1)]
    [string]$OutFile,

    # Force every page through threshold + fax chain
    [switch]$bw,

    # Force every page through lzw
    [switch]$grayscale
)

# pdftk is preferred for merging; magick is used as a fallback (re-rasterizes pages)
$usePdftk = [bool](Get-Command 'pdftk' -ErrorAction SilentlyContinue)

# Resolve base name and parent directory from a PDF path or a folder path
if (Test-Path $InFile -PathType Container) {
    $base = Split-Path $InFile -Leaf
    $base = $base.TrimEnd('\', '/')
    $parentDir = $InFile
} elseif ($InFile -match '\.pdf$') {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($InFile)
    # Convention: clean_sheet_music.ps1 outputs to clean_<base>/
    $parentDir = "clean_${base}"
} else {
    Write-Host "Input must be a .pdf file or a directory: $InFile"
    exit 1
}

if (-not $OutFile) {
    $OutFile = "${base}.pdf"
}

# Prefer <parent>/out/ (manual curation subfolder), fallback to <parent> itself
$outSubDir = Join-Path $parentDir 'out'
if (Test-Path $outSubDir -PathType Container) {
    $inDir = $outSubDir
} elseif (Test-Path $parentDir -PathType Container) {
    $inDir = $parentDir
} else {
    Write-Host "Directory not found: $parentDir"
    exit 1
}

# Output PDF sits next to $inDir (i.e. in $parentDir)
$OutFile = Join-Path $parentDir $OutFile

$files = Get-ChildItem (Join-Path $inDir '*.tif') | Sort-Object Name

if ($files.Count -eq 0) {
    Write-Host "No .tif files found in: $inDir"
    exit 1
}

# Temp dir for single-page PDFs, inside $inDir, cleaned up after merge
$tempDir = Join-Path $inDir '_compile_temp'
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

# Report active mode
if ($bw) {
    Write-Host "Mode: forced B&W (threshold + fax chain)"
} elseif ($grayscale) {
    Write-Host "Mode: forced grayscale (lzw)"
} else {
    Write-Host "Mode: auto (colorspace detection per page)"
}
Write-Host "Compiling $($files.Count) pages from ${inDir}..."

# Process files individually to allow per-page compression and correct merge order
$pageIndex = 1
foreach ($file in $files) {
    # Zero-padded page name for correct sort order during merge
    $pagePdf = Join-Path $tempDir ('page_{0:D3}.pdf' -f $pageIndex)

    # Determine processing path
    if ($bw) {
        $mode = 'bw'
    } elseif ($grayscale) {
        $mode = 'gray'
    } else {
        # Colorspace probe: Gray -> fax chain, anything else -> JPEG
        $colorspace = magick identify -format '%[colorspace]' $file.FullName
        if ($colorspace -eq 'Gray') {
            $mode = 'bw'
        } else {
            $mode = 'color'
        }
    }

    Write-Host "  Page $pageIndex ($($file.Name)): $mode"

    if ($mode -eq 'color') {
        # JPEG for RGB/sRGB pages
        magick $file.FullName -compress jpeg -quality 85 $pagePdf
        if ($LASTEXITCODE -ne 0) {
            Write-Host "JPEG compression failed for $($file.Name)."
            Remove-Item $tempDir -Recurse
            exit 1
        }
    } else {
        # fax chain: fax -> threshold + fax -> lzw
        magick $file.FullName -compress fax $pagePdf 2>$null
        if ($LASTEXITCODE -ne 0) {
            magick $file.FullName -threshold 50% -compress fax $pagePdf 2>$null
            if ($LASTEXITCODE -ne 0) {
                magick $file.FullName -compress lzw $pagePdf
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "All compression methods failed for $($file.Name)."
                    Remove-Item $tempDir -Recurse
                    exit 1
                } else {
                    Write-Host "    Used: lzw"
                }
            } else {
                Write-Host "    Used: threshold + fax"
            }
        } else {
            Write-Host "    Used: fax (CCITT Group 4)"
        }
    }

    $pageIndex++
}

# Merge all single-page PDFs in order
$pageFiles = @(Get-ChildItem (Join-Path $tempDir '*.pdf') | Sort-Object Name | Select-Object -ExpandProperty FullName)

if ($usePdftk) {
    Write-Host 'Merging pages with pdftk...'
    pdftk @pageFiles cat output $OutFile
} else {
    Write-Host 'pdftk not found. Merging with magick (pages will be re-rasterized)...'
    magick @pageFiles $OutFile
}

if ($LASTEXITCODE -ne 0) {
    Write-Host 'Merge failed.'
    Remove-Item $tempDir -Recurse
    exit 1
}

# Clean up temp dir after successful merge
Remove-Item $tempDir -Recurse

Write-Host "Done. Output: $OutFile"
