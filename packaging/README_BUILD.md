# Đóng gói GiongDoc cho macOS

Tài liệu này hướng dẫn build GiongDoc thành ứng dụng `GiongDoc.app` và file cài đặt
`GiongDoc-1.0.0-<arch>.dmg` trên MacBook (Apple Silicon M1/M2/M3/M4 hoặc Intel).

## 1. Chuẩn bị (chỉ làm một lần)

1. **Cài Xcode Command Line Tools** (có sẵn `codesign`, `iconutil`, `hdiutil`):
   ```bash
   xcode-select --install
   ```
2. **Cài Homebrew** (nếu chưa có) – xem https://brew.sh:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   Trên Apple Silicon, làm theo lời nhắc cuối để thêm `/opt/homebrew/bin` vào PATH.
3. **Cài Python 3.11+ và ffmpeg**:
   ```bash
   brew install python@3.11 ffmpeg
   ```

## 2. Build

Trong thư mục gốc của dự án:

```bash
make dmg
```

Script `packaging/build_macos.sh` sẽ tự động:

1. Kiểm tra Python ≥ 3.11 (tự tìm `python3.13/3.12/3.11` hoặc bản của Homebrew).
2. Tạo môi trường ảo `.venv-build`, cài `requirements.txt` + PyInstaller.
3. Tạo biểu tượng (`make_icon.py` → `icon_1024.png`, `make_icns.sh` → `GiongDoc.icns`).
4. Sao chép ffmpeg của Homebrew vào app tại `Contents/Resources/bin/ffmpeg`.
5. Chạy PyInstaller với `packaging/GiongDoc.spec`.
6. Ký ad-hoc (`codesign --force --deep -s -`).
7. Tạo `dist/GiongDoc-1.0.0-arm64.dmg` (hoặc `-x86_64.dmg` trên Intel), có lối tắt `/Applications`.
8. Notarize (chỉ khi có tài khoản Apple Developer, xem mục 5).

Các lệnh khác:

| Lệnh | Tác dụng |
|---|---|
| `make run` | Chạy app trực tiếp từ mã nguồn (tạo `.venv`) |
| `make test` | Chạy test |
| `make build` | Chỉ build `dist/GiongDoc.app`, không tạo DMG |
| `make clean` | Xóa `build/`, `dist/`, `packaging/vendor/` |

**Không có máy Mac / không muốn cài công cụ?** Đẩy mã lên GitHub rồi vào tab
*Actions → Build macOS app → Run workflow* (hoặc push tag `v1.0.0`). Workflow
`.github/workflows/build-macos.yml` build cả bản arm64 và x86_64, file DMG nằm ở mục
*Artifacts* của lần chạy.

## 3. Mở app chưa ký lần đầu

App chỉ được ký ad-hoc nên Gatekeeper sẽ báo *"không thể mở vì không xác minh được nhà phát triển"*.
Chọn một trong các cách:

- **Cách 1:** Kéo `GiongDoc.app` vào *Applications*, sau đó **chuột phải (Control-click) → Mở (Open)** →
  bấm **Mở** trong hộp thoại. Chỉ cần làm một lần.
- **Cách 2 (macOS 15 Sequoia trở lên):** mở app một lần, rồi vào *Cài đặt hệ thống → Quyền riêng tư & Bảo mật*,
  kéo xuống và bấm **Vẫn mở (Open Anyway)**.
- **Cách 3 (Terminal):**
  ```bash
  xattr -dr com.apple.quarantine /Applications/GiongDoc.app
  ```

Lần đầu ghi âm mẫu giọng, macOS sẽ hỏi quyền **Micro** – hãy bấm *Cho phép*.

## 4. Bật tính năng giọng tùy chỉnh (custom voice)

Tính năng tạo giọng từ mẫu giọng của bạn dùng F5-TTS (hoặc Coqui XTTS), cần PyTorch – rất nặng
(vài GB) nên **không** được đóng gói mặc định. App tự phát hiện: nếu thiếu thư viện, mục giọng tùy chỉnh
sẽ bị tắt, các giọng khác vẫn hoạt động bình thường.

- **Chạy từ mã nguồn:**
  ```bash
  python3.11 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt -r requirements-custom-voice.txt   # hoặc: pip install -e ".[custom-voice]"
  python run.py
  ```
- **Đóng gói kèm vào app** (app sẽ rất lớn):
  ```bash
  WITH_CUSTOM_VOICE=1 make dmg
  ```
- Muốn dùng Coqui XTTS thay F5-TTS: bỏ dấu `#` ở dòng `coqui-tts` trong `requirements-custom-voice.txt`.

Chỉ dùng mẫu giọng của chính bạn hoặc của người đã đồng ý rõ ràng.

## 5. Ký và notarize (tùy chọn, cần Apple Developer Program)

Đặt 4 biến môi trường rồi build; thiếu biến nào thì bước notarize được bỏ qua:

```bash
export DEVELOPER_ID="Developer ID Application: Ten Cua Ban (ABCDE12345)"
export APPLE_ID="ban@example.com"
export TEAM_ID="ABCDE12345"
export APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"   # mật khẩu dành riêng cho ứng dụng, tạo ở appleid.apple.com
make dmg
```

Trên GitHub Actions, khai báo 4 giá trị trên dưới dạng *Repository secrets* cùng tên.

## 6. ffmpeg

- Mặc định script sao chép `$(brew --prefix)/bin/ffmpeg`. Bản Homebrew liên kết động tới nhiều thư viện
  `.dylib`; PyInstaller sẽ gom các thư viện đó vào app. Nếu cuối bước build có cảnh báo
  *"still references Homebrew paths"*, app chỉ xuất được MP3/M4A trên máy có cài ffmpeg qua Homebrew.
- Muốn app hoàn toàn độc lập, dùng một bản ffmpeg **tĩnh** (static) đúng kiến trúc:
  ```bash
  FFMPEG_SRC=/duong/dan/ffmpeg-static make dmg
  # hoặc tải về tự động (file .zip/.tar chứa ffmpeg):
  FFMPEG_URL="https://.../ffmpeg.zip" make dmg     # chỉ dùng khi máy không có ffmpeg nào
  ```
- Khi chạy, app tìm ffmpeg theo thứ tự: biến môi trường `GIONGDOC_FFMPEG` →
  `GiongDoc.app/Contents/Resources/bin/ffmpeg` → `ffmpeg` trong PATH.

## 7. Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| `Python 3.11+ not found` | `brew install python@3.11`, hoặc chạy `PYTHON=/duong/dan/python3.11 make dmg` |
| `iconutil`/`codesign` không tồn tại | `xcode-select --install` |
| `ffmpeg is arm64 but this build is x86_64` | ffmpeg khác kiến trúc (vd. Homebrew Intel chạy qua Rosetta). Dùng đúng Homebrew (`/opt/homebrew` cho Apple Silicon) |
| App mở rồi tắt ngay | Chạy trong Terminal để xem lỗi: `/Applications/GiongDoc.app/Contents/MacOS/GiongDoc` |
| Thiếu module khi chạy app đã đóng gói (`ModuleNotFoundError`) | Thêm tên module vào `hiddenimports` trong `packaging/GiongDoc.spec` rồi build lại |
| Không có tiếng / không nghe thử được | Kiểm tra *Cài đặt hệ thống → Âm thanh*; giọng Edge cần Internet |
| Không ghi âm được | *Cài đặt hệ thống → Quyền riêng tư & Bảo mật → Micro* → bật GiongDoc. Đặt lại: `tccutil reset Microphone com.cuong.giongdoc` |
| "GiongDoc bị hỏng, nên chuyển vào Thùng rác" | Do cờ quarantine: `xattr -dr com.apple.quarantine /Applications/GiongDoc.app` |
| Build lỗi lạ sau khi nâng cấp Python/thư viện | `make distclean && make dmg` |
| Notarize bị từ chối | Xem log: `xcrun notarytool log <submission-id> --apple-id ... --team-id ... --password ...` |
