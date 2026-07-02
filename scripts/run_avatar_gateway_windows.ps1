param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"

function Get-EnvOrDefault {
    param(
        [string]$Name,
        [string]$Default
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

$rootDir = Split-Path -Parent $PSScriptRoot
$exeCandidates = @(
    (Join-Path $rootDir "CPP/build-clang/avatar_gateway.exe"),
    (Join-Path $rootDir "CPP/build/avatar_gateway.exe"),
    "C:/temp/avatar-run/avatar_gateway.exe"
)

$exePath = $null
foreach ($candidate in $exeCandidates) {
    if (Test-Path $candidate) {
        $exePath = $candidate
        break
    }
}

if (-not $exePath) {
    Write-Error "avatar_gateway.exe not found. Please build CPP target first (e.g. CPP/build-clang)."
    exit 1
}

$clangBin = Get-EnvOrDefault -Name "AVATAR_CLANG_BIN" -Default "C:/msys64/clang64/bin"
if (-not (Test-Path $clangBin)) {
    Write-Error "clang runtime directory not found: $clangBin"
    exit 1
}

$systemRoot = [Environment]::GetFolderPath("Windows")
$env:PATH = "$clangBin;$systemRoot/System32;$systemRoot"

$camera = Get-EnvOrDefault -Name "CAMERA" -Default "/dev/video0"
$renderMode = Get-EnvOrDefault -Name "RENDER_MODE" -Default "beauty"
$outputMode = Get-EnvOrDefault -Name "OUTPUT_MODE" -Default "network"
$outputDevice = Get-EnvOrDefault -Name "OUTPUT_DEVICE" -Default "/dev/video43"
$networkHost = Get-EnvOrDefault -Name "NETWORK_HOST" -Default "0.0.0.0"
$networkPort = Get-EnvOrDefault -Name "NETWORK_PORT" -Default "8080"
$networkPath = Get-EnvOrDefault -Name "NETWORK_PATH" -Default "/mjpeg"
$networkJpegQuality = Get-EnvOrDefault -Name "NETWORK_JPEG_QUALITY" -Default "70"
$fallbackStyle = Get-EnvOrDefault -Name "FALLBACK_STYLE" -Default "normal"
$backgroundMode = Get-EnvOrDefault -Name "BACKGROUND_MODE" -Default "camera"
$avatarScale = Get-EnvOrDefault -Name "AVATAR_SCALE" -Default "1.0"
$eyeAnimation = Get-EnvOrDefault -Name "EYE_ANIMATION" -Default "subtle"
$mouthAnimation = Get-EnvOrDefault -Name "MOUTH_ANIMATION" -Default "normal"
$mouthYOffset = Get-EnvOrDefault -Name "MOUTH_Y_OFFSET" -Default "0.00"
$mouthXOffset = Get-EnvOrDefault -Name "MOUTH_X_OFFSET" -Default "0.00"
$maxFaces = Get-EnvOrDefault -Name "MAX_FACES" -Default "1"
$detectEvery = Get-EnvOrDefault -Name "DETECT_EVERY" -Default "2"
$beautyStrength = Get-EnvOrDefault -Name "BEAUTY_STRENGTH" -Default "0.45"
$avatarName = Get-EnvOrDefault -Name "AVATAR_NAME" -Default "avatar_male"
$gpioAvatarSelect = Get-EnvOrDefault -Name "GPIO_AVATAR_SELECT" -Default "0"
$gpio0Pin = Get-EnvOrDefault -Name "GPIO0_PIN" -Default "0"
$gpio1Pin = Get-EnvOrDefault -Name "GPIO1_PIN" -Default "1"
$avatarGpio00 = Get-EnvOrDefault -Name "AVATAR_GPIO_00" -Default "avatar_00"
$avatarGpio01 = Get-EnvOrDefault -Name "AVATAR_GPIO_01" -Default "avatar_01"
$avatarGpio10 = Get-EnvOrDefault -Name "AVATAR_GPIO_10" -Default "avatar_10"
$avatarGpio11 = Get-EnvOrDefault -Name "AVATAR_GPIO_11" -Default "avatar_11"
$width = Get-EnvOrDefault -Name "WIDTH" -Default "960"
$height = Get-EnvOrDefault -Name "HEIGHT" -Default "540"
$fps = Get-EnvOrDefault -Name "FPS" -Default "15"

$avatarFallback = Join-Path $rootDir "assets/avatar.png"
$avatarDir = Join-Path $rootDir "assets/avatars"

$args = @(
    "--camera", $camera,
    "--render-mode", $renderMode,
    "--output-mode", $outputMode,
    "--output", $outputDevice,
    "--network-host", $networkHost,
    "--network-port", $networkPort,
    "--network-path", $networkPath,
    "--network-jpeg-quality", $networkJpegQuality,
    "--fallback-style", $fallbackStyle,
    "--background-mode", $backgroundMode,
    "--avatar-scale", $avatarScale,
    "--eye-animation", $eyeAnimation,
    "--mouth-animation", $mouthAnimation,
    "--mouth-y-offset", $mouthYOffset,
    "--mouth-x-offset", $mouthXOffset,
    "--max-faces", $maxFaces,
    "--detect-every", $detectEvery,
    "--beauty-strength", $beautyStrength,
    "--avatar", $avatarFallback,
    "--avatar-dir", $avatarDir,
    "--avatar-name", $avatarName,
    "--gpio0", $gpio0Pin,
    "--gpio1", $gpio1Pin,
    "--avatar-gpio-00", $avatarGpio00,
    "--avatar-gpio-01", $avatarGpio01,
    "--avatar-gpio-10", $avatarGpio10,
    "--avatar-gpio-11", $avatarGpio11,
    "--width", $width,
    "--height", $height,
    "--fps", $fps
)

if ($gpioAvatarSelect -in @("1", "true", "on")) {
    $args += "--gpio-avatar-select"
}

if ($ExtraArgs) {
    $args += $ExtraArgs
}

& $exePath @args
exit $LASTEXITCODE
