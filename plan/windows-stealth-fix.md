# Plan: Fix Windows Fingerprint Spoofing Stability

## Context

Dự án CloakBrowser đã thêm Windows support gần đây (commit `15c79aa`), nhưng sau khi review kỹ, **fingerprint spoofing cho Windows chưa ổn định**. Có nhiều vấn đề từ bug logic, thiếu patches, đến CI/CD chưa hoàn thiện.

## Các vấn đề phát hiện

### 1. BUG: Python `get_default_stealth_args()` thiếu Windows branch
**File:** `cloakbrowser/config.py:41-47`

Python không có branch cho Windows. Khi chạy trên Windows (`platform.system() == "Windows"`), code rơi vào nhánh Linux fallback:
```python
# Linux: spoof as Windows  <-- WRONG: Windows cũng vào đây!
return base + [
    "--fingerprint-platform=windows",
    "--fingerprint-hardware-concurrency=8",          # ← Sai: hardcode 8 trên native Windows
    "--fingerprint-gpu-vendor=NVIDIA Corporation",    # ← Sai: spoof GPU trên native Windows
    "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",  # ← Sai: user có thể dùng AMD/Intel
]
```

JS version (`js/src/config.ts:161-163`) đã handle đúng:
```typescript
if (isWindows) {
    return [...base, "--fingerprint-platform=windows"];  // ✅ Không spoof GPU
}
```

**Hậu quả:** Trên Windows, fingerprint bị mismatch — GPU report NVIDIA RTX 3070 nhưng user thực tế dùng Intel/AMD, concurrency hardcode 8 không khớp CPU thật → các detection service sẽ phát hiện inconsistency.

### 2. JS test `config.test.ts` sẽ fail trên Windows
**File:** `js/tests/config.test.ts:28`

Test expect `--fingerprint-hardware-concurrency=8` khi không phải macOS, nhưng trên Windows native thì arg này không nên có.

### 3. `patches/` directory rỗng — không có C++ patches
**File:** `patches/README.md`

Directory chỉ chứa README. CI build với `continue-on-error: true` → binary được build mà **không có stealth patches** → binary sẽ bị detect như Chromium bình thường.

### 4. CI Windows build chỉ package `chrome.exe`
**File:** `.github/workflows/build-deploy.yml:178`

```powershell
Compress-Archive -Path chrome.exe -DestinationPath ../../../../cloakbrowser-win32-x64.tar.gz -Force
```

Chỉ package `chrome.exe` mà thiếu DLLs, resources, locales, icudtl.dat, v8_context_snapshot.bin... → binary không chạy được.

### 5. Error message lỗi thời
**File:** `cloakbrowser/config.py:129`

Vẫn hiển thị "Windows builds are coming soon" dù `win32-x64` đã có trong `AVAILABLE_PLATFORMS`.

### 6. Không có Windows stealth testing trong CI
CI chỉ test trên `ubuntu-latest, macos-latest`. Không verify stealth hoạt động trên Windows.

---

## Plan Implementation

### Step 1: Fix Python `get_default_stealth_args()` — thêm Windows branch
**File:** `cloakbrowser/config.py`

Thêm Windows check trước Linux fallback:
```python
def get_default_stealth_args() -> list[str]:
    seed = random.randint(10000, 99999)
    system = platform.system()

    base = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        f"--fingerprint={seed}",
    ]

    if system == "Darwin":
        return base + ["--fingerprint-platform=macos"]

    if system == "Windows":
        # Windows: native platform — no GPU/concurrency spoofing needed
        return base + ["--fingerprint-platform=windows"]

    # Linux: spoof as Windows
    return base + [
        "--fingerprint-platform=windows",
        "--fingerprint-hardware-concurrency=8",
        "--fingerprint-gpu-vendor=NVIDIA Corporation",
        "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
    ]
```

### Step 2: Fix JS test cho Windows compatibility
**File:** `js/tests/config.test.ts`

Update test để handle cả 3 platforms:
```typescript
if (isMac) {
    expect(args).toContain("--fingerprint-platform=macos");
    expect(args.some((a) => a.includes("hardware-concurrency"))).toBe(false);
} else if (process.platform === "win32") {
    expect(args).toContain("--fingerprint-platform=windows");
    expect(args.some((a) => a.includes("hardware-concurrency"))).toBe(false);
} else {
    // Linux
    expect(args).toContain("--fingerprint-platform=windows");
    expect(args).toContain("--fingerprint-hardware-concurrency=8");
}
```

### Step 3: Thêm unit test cho Windows stealth args (Python)
**File:** `tests/test_platform.py`

Thêm test class `TestWindowsStealthArgs`:
- Test mock `platform.system() == "Windows"` → verify không có GPU spoofing args
- Test verify có `--fingerprint-platform=windows`
- Test verify KHÔNG có `--fingerprint-hardware-concurrency`, `--fingerprint-gpu-vendor`, `--fingerprint-gpu-renderer`

### Step 4: Fix error message lỗi thời
**File:** `cloakbrowser/config.py:127-131`

Update message bỏ "Windows builds are coming soon" vì Windows đã supported.

### Step 5: Fix CI Windows build packaging
**File:** `.github/workflows/build-deploy.yml:174-178`

Sửa packaging step để include tất cả required files:
```powershell
Set-Location src\out\Release
# Package all required Chromium runtime files
tar -czvf ../../../../cloakbrowser-win32-x64.tar.gz chrome.exe *.dll *.bin *.pak *.dat locales/ resources/
```

### Step 6: Thêm stealth patches placeholder documentation
**File:** `patches/README.md`

Update README để rõ ràng hơn: patches là proprietary, binary phải download từ official release. Giải thích workflow cho contributors.

---

## Verification

1. **Python tests:**
   ```bash
   pytest tests/test_platform.py -v
   pytest tests/ -m "not slow" -v
   ```

2. **JS tests:**
   ```bash
   cd js && npm run test && npm run typecheck && npm run build
   ```

3. **Ruff lint:**
   ```bash
   ruff check cloakbrowser/ tests/
   ```

4. **Manual verification** (nếu có Windows machine):
   - Set `CLOAKBROWSER_BINARY_PATH` → chạy `python examples/basic.py`
   - Verify stealth args không có GPU spoofing trên Windows
