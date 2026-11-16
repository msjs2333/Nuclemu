# Exercise the installed CLI and its local HTTP service without a host Python.
param(
    [Parameter(Mandatory)] [string]$Executable,
    [Parameter(Mandatory)] [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path -LiteralPath $Executable).Path
$out = (New-Item -ItemType Directory -Path $OutputDirectory -ErrorAction Stop).FullName

function Invoke-Lab {
    $result = & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "nuclemu $($args[0]) failed ($LASTEXITCODE)" }
    $result
}
function Post-Lab($route, $data) {
    $json = ConvertTo-Json -InputObject $data -Depth 6 -Compress
    Invoke-RestMethod -Uri ($url + $route) -Method Post -ContentType 'application/json' -Body $json
}

Push-Location $out
try {
    Invoke-Lab validate
    $cal = @{format='nuclemu.calibration/1'; unit='MeV'; experiment='alpha'; device='mca';
             channels=1024; channel1=0; energy1=0; channel2=1000; energy2=6}
    $cal | ConvertTo-Json | Set-Content -LiteralPath calibration.json -Encoding ASCII
    Invoke-Lab run alpha --set source_present=1 --enable-output alpha_detector --seed 187 --duration 3 --calibration calibration.json --package AEL.nuclemu
    Invoke-Lab run beta --set source_present=1 --enable-output beta_detector --seed 187 --window counter=1 --window counter_b=5 --duration 3 --package BABS.nuclemu

    $server = Start-Process -FilePath $exe -ArgumentList 'serve','--no-gui' -WorkingDirectory $out -PassThru -WindowStyle Hidden -RedirectStandardOutput "$out/service.out" -RedirectStandardError "$out/service.err"
    $deadline = (Get-Date).AddSeconds(30)
    do {
        $line = Get-Content -LiteralPath "$out/service.out" -ErrorAction SilentlyContinue | Select-String -Pattern 'http://127\.0\.0\.1:\d+/' | Select-Object -First 1
        if ($line) { break }
        if ($server.HasExited -or (Get-Date) -gt $deadline) { throw 'Local service did not become ready' }
        Start-Sleep -Milliseconds 100
    } while ($true)
    $url = $line.Matches[0].Value
    $catalog = Invoke-RestMethod ($url + 'api/catalog')
    if ('alpha' -notin $catalog.experiments.id -or 'beta' -notin $catalog.experiments.id) { throw 'Missing built-in course' }
    $homePage = Invoke-WebRequest $url -UseBasicParsing
    $assets = [regex]::Matches($homePage.Content, '(?:href|src)="(/[^"]+)"')
    foreach ($path in (@($assets | ForEach-Object { $_.Groups[1].Value }) + @('/draw.js','/cover-beta-absorption.webp'))) {
        $asset = Invoke-WebRequest ($url.TrimEnd('/') + $path) -UseBasicParsing
        if ($asset.RawContentLength -le 0) { throw "Missing asset: $path" }
    }
    foreach ($sample in 'AEL','BABS') {
        $file = "$out/$sample.nuclemu"
        $inspection = Invoke-Lab files inspect $file | Out-String | ConvertFrom-Json
        $item = $inspection.records | Where-Object kind -eq measurement | Select-Object -First 1
        Invoke-Lab files export $file --item $item.id --output "$sample.json"
        $bundle = Get-Content -Raw "$sample.json" -Encoding UTF8 | ConvertFrom-Json
        $products = @($bundle.items | Where-Object kind -eq measurement | ForEach-Object { $_.document })
        $state = Post-Lab 'api/open_package' @{file=[Convert]::ToBase64String([IO.File]::ReadAllBytes($file))}
        if (!$state.portable_loaded -or $null -eq $state.id -or $state.saved_measurements.Count -ne $products.Count) { throw "Reopen failed: $sample" }
        if ($sample -eq 'AEL') {
            $channels = New-Object 'int[]' 1024
            foreach ($window in $products[0].windows) {
                for ($i = 0; $i -lt 1024; $i++) { $channels[$i] += $window.counts[$i] }
            }
            if (($channels | Measure-Object -Sum).Sum -le 0 -or $state.calibration.energy2 -ne 6 -or
                ($channels -join ',') -ne ($state.selected_observation.counts -join ',')) { throw 'Spectrum or calibration mismatch' }
        } else {
            $a,$b = $products
            if ($a.snapshot.device -ne 'counter' -or $b.snapshot.device -ne 'counter_b' -or $a.snapshot.exposure_s -ne 3 -or $b.snapshot.exposure_s -ne 3 -or
                $a.windows.Count -ne 3 -or $b.windows.Count -ne 1 -or $b.windows[0].complete -or $item.measurements.Count -ne 2) { throw 'Counter windows mismatch' }
            foreach ($member in $item.measurements) {
                $null = Post-Lab 'api/action' @{session=$state.id; action='device'; device=$member.device}
                $display = Post-Lab 'api/action' @{session=$state.id; action='select'; device=$member.device; item_id=$member.id}
                $expected = ($products | Where-Object { $_.snapshot.device -eq $member.device }).windows |
                    ForEach-Object { $_.counts[0] } | Measure-Object -Sum
                if ($display.selected_observation.counts[0] -ne $expected.Sum) { throw "Counter readout mismatch: $($member.device)" }
            }
        }
        $confirmation = Post-Lab 'api/action' @{session=$state.id; action='freeze'}
        $null = Post-Lab 'api/action' @{session=$state.id; action='discard'; confirmation_id=$confirmation.confirmation_id}
    }
    Write-Output 'PASS: packaged catalog, alpha spectrum/calibration and beta counter files reopened.'
} finally {
    if ($server -and !$server.HasExited) { $server.Kill(); $server.WaitForExit() }
    Pop-Location
}
