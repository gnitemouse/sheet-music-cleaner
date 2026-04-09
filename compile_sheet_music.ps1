# compile_sheet_music.ps1
# author: Daisy Jane @dayzl
#
# Compiles a folder of TIFF pages into a single PDF using ImageMagick.
# Tries compression methods in order from smallest to most compatible:
#   fax (CCITT Group 4) -> threshold + fax -> lzw
#
# Input resolution:
#   PDF    -- looks for a clean_<base>/ directory produced by clean_sheet_music.ps1,
#             preferring the clean_<base>/out/ subdirectory if it exists.
#   Folder -- uses the folder directly, preferring its out/ subdirectory if present.
#
# Output: <base>.pdf (or the path given as the second argument)
#
# Usage:
#   .\compile_sheet_music.ps1 input.pdf
#   .\compile_sheet_music.ps1 input.pdf compiled\output.pdf
#   .\compile_sheet_music.ps1 clean_myscore\
#
# Merge multiple PDFs after compiling:
#   pdftk file1.pdf file2.pdf cat output merged.pdf (recommended)
#   magick file1.pdf file2.pdf merged.pdf (works, but re-rasterizes)
# Note: pdftk preserves quality exactly; magick re-rasterizes, which may increase file size.
#
# Requirements: ImageMagick (magick must be on PATH)

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$InFile,
    [Parameter(Mandatory=$false, Position=1)]
    [string]$OutFile
)

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

$files = Get-ChildItem (Join-Path $inDir '*.tif') | Sort-Object Name

if ($files.Count -eq 0) {
    Write-Host "No .tif files found in: $inDir"
    exit 1
}

Write-Host "Compiling $($files.Count) pages from ${inDir}..."

# Attempt 1: fax (CCITT Group 4) -- smallest file size, requires true 1-bit B&W
Write-Host 'Trying -compress fax...'
magick @($files.FullName) -compress fax $outFile 2>$null

if ($LASTEXITCODE -ne 0) {
    # Attempt 2: force 1-bit conversion with a threshold, then retry fax
    Write-Host 'Fax failed. Trying -threshold 50% -compress fax...'
    magick @($files.FullName) -threshold 50% -compress fax $outFile 2>$null

    if ($LASTEXITCODE -ne 0) {
        # Attempt 3: lzw -- lossless, works on grayscale; larger than fax
        Write-Host 'Fax failed again. Falling back to -compress lzw...'
        magick @($files.FullName) -compress lzw $outFile

        if ($LASTEXITCODE -ne 0) {
            Write-Host 'All compression methods failed.'
            exit 1
        } else {
            Write-Host 'Used: lzw (grayscale input detected)'
        }
    } else {
        Write-Host 'Used: threshold + fax'
    }
} else {
    Write-Host 'Used: fax (CCITT Group 4)'
}

Write-Host "Done. Output: $outFile"
