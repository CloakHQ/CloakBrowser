# Fingerprint & Identity Configuration

CloakBrowser generates a random fingerprint seed on each launch, compiling a fully consistent browser identity from a single integer. All hardware parameters (GPU, screen, CPU, memory, fonts, canvas/WebGL noise) are derived from this seed, making them look coherent and natural without manual tuning.

## How Seeds Work

```
seed=12345 → GPU=Intel UHD 630,  screen=1920x1080,  CPU=8 cores,  RAM=8GB, WebGL Noise=A
seed=67890 → GPU=RTX 3070,       screen=2560x1440,  CPU=16 cores, RAM=16GB, WebGL Noise=B
```

Using the same seed yields the exact same identity across launches. This is invaluable for **multi-account or session persistence** scenarios, as return visits will look like they are coming from the exact same device.

### Usage:
```python
from cloakbrowser import launch

# 1. Random seed (Default): Produces a fresh identity every launch.
browser = launch()

# 2. Fixed seed: Produces the exact same identity every time.
browser = launch(args=["--fingerprint=42069"])
```

---

## Platform-Aware Fingerprinting

The wrapper automatically applies platform-aware defaults. If running on Linux, it overrides the OS string to windows for a much more common desktop fingerprint, while macOS naturally runs as native macOS.

To force a specific platform, use the `--fingerprint-platform` flag:

| Flag Value | Reported Platform | GPU Renderer Pool |
|---|---|---|
| `--fingerprint-platform=windows` | `Win32` | Windows Intel/NVIDIA/AMD GPUs |
| `--fingerprint-platform=macos` | `MacIntel` / Apple | macOS Apple Silicon / Intel GPUs |
| `--fingerprint-platform=linux` | `Linux x86_64` | Linux Mesa/NVIDIA GPUs |

```python
# Force a Linux script to report as a macOS machine:
browser = launch(args=["--fingerprint-platform=macos"])
```

---

## Overriding Individual Fingerprint Attributes

You can pin a seed for general consistency, and override individual hardware metrics manually using process flags:

```python
browser = launch(
    args=[
        "--fingerprint=12345",
        "--fingerprint-gpu-vendor=NVIDIA Corporation",
        "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 4070/PCIe/SSE2",
        "--fingerprint-hardware-concurrency=12",  # Reported CPU cores
        "--fingerprint-device-memory=16",          # Reported RAM in GB
        "--fingerprint-screen-width=2560",         # Screen resolution
        "--fingerprint-screen-height=1440",
    ]
)
```

### Full Fingerprint Flag Reference

| Flag | Controls | Typical Values |
|---|---|---|
| `--fingerprint=seed` | Master fingerprint seed | `10000` to `99999` |
| `--fingerprint-platform` | OS system platform | `windows`, `macos`, `linux` |
| `--fingerprint-gpu-vendor` | WebGL `UNMASKED_VENDOR_WEBGL` | e.g. `Google Inc. (NVIDIA)` |
| `--fingerprint-gpu-renderer` | WebGL `UNMASKED_RENDERER_WEBGL` | e.g. `ANGLE (NVIDIA, ...)` |
| `--fingerprint-hardware-concurrency` | `navigator.hardwareConcurrency` | `4`, `8`, `12`, `16` |
| `--fingerprint-device-memory` | `navigator.deviceMemory` | `4`, `8` (standard Chromium limits) |
| `--fingerprint-screen-width` | Resolution width | `1920`, `1440`, `2560` |
| `--fingerprint-screen-height` | Resolution height | `1080`, `900`, `1440` |
| `--fingerprint-storage-quota` | Hard storage limit (MB) | `5000` (avoids incognito flags) |
| `--fingerprint-fonts-dir` | Target directory for fonts | Absolute path to folder |
| `--fingerprint-noise=false` | Disable canvas/WebGL noise injection | `false` (Not recommended) |

---

## Multi-Account Fingerprint & Profile Pairing

To run multi-account scraping flows, always pair a unique deterministic seed with a unique persistent profile directory. This guarantees that each account is associated with a distinct, stable machine identity that never changes, while keeping account cookies separated:

```python
accounts = [
    {"username": "alice", "profile": "./profiles/alice", "seed": "90001"},
    {"username": "bob",   "profile": "./profiles/bob",   "seed": "90002"},
]

for acct in accounts:
    # Launches browser with Alice's specific profile and consistent fingerprint
    ctx = launch_persistent_context(
        acct["profile"],
        headless=True,
        args=[f"--fingerprint={acct['seed']}"],
    )
    page = ctx.new_page()
    page.goto("https://example.com/dashboard")
    # ... perform account actions ...
    ctx.close()
```
