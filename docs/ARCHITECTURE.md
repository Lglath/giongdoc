# GiongDoc – kiến trúc module (bản hợp đồng giữa các workstream)

Ngôn ngữ: Python 3.11+, UI PySide6 (Qt 6), đóng gói PyInstaller -> .app -> .dmg.
Contract chung: `giongdoc/core.py` (Language, Segment, ProsodySettings, AudioClip, Voice, TTSEngine).
Âm thanh nội bộ: mono float32, 24 kHz.

| Package | Trách nhiệm | API công khai |
|---|---|---|
| `giongdoc/text/` | Chuẩn hóa văn bản (số, ngày, đơn vị, viết tắt) theo 4 ngôn ngữ, tách câu, map dấu câu -> độ dài ngắt nghỉ, nhận diện ngôn ngữ, markup inline, từ điển phát âm | `pipeline.prepare(text, default_language=None, settings=None, dictionary=None) -> list[Segment]`; `detect.detect_language(text) -> Language`; `dictionary.PronunciationDict` |
| `giongdoc/engines/` | Engine TTS: `edge` (neural online, tự nhiên nhất), `macsay` (giọng hệ thống macOS, offline), `custom` (giọng tùy chỉnh F5-TTS/XTTS từ mẫu có đồng ý) | `registry.all_engines()`, `registry.get(engine_id)`, `registry.all_voices(language=None)`, `registry.find_voice(voice_id)`; `custom_voices.CustomVoiceStore`, `custom_voices.ConsentRecord` |
| `giongdoc/audio/` | Giải mã, resample, cắt lặng đầu/cuối, crossfade, fade, chuẩn hóa âm lượng (loudness), ghép đoạn + ngắt nghỉ, xuất WAV/MP3/M4A | `codec.decode_bytes(data) -> AudioClip`, `dsp.*`, `smoothing.assemble(parts: list[tuple[AudioClip, int]], settings=SmoothingSettings()) -> AudioClip`, `export.export(clip, path, fmt="mp3", bitrate="192k")` |
| `giongdoc/service.py` | Điều phối: text -> segments -> engine -> audio, cache theo hash, progress, hủy | `SynthesisService.render(...)`, `SynthesisService.preview_sentence(...)` |
| `giongdoc/ui/` | Cửa sổ chính, editor, chọn giọng/ngôn ngữ, thanh tốc độ/cao độ/ngắt nghỉ, nghe thử, xuất file, quản lý giọng tùy chỉnh | `ui.app.main()` |
| `giongdoc/project/` | Lưu/mở dự án `.giongdoc` (JSON), lịch sử, cài đặt | `project.model.Project` |
| `packaging/` | PyInstaller spec, Info.plist, script build .app/.dmg, GitHub Actions macOS | `packaging/build_macos.sh` |

## Markup inline (do module text phân tích)
- `[pause 800]` hoặc `[ngat 800]` – chèn khoảng lặng 800 ms
- `[voice:edge:vi-VN-NamMinhNeural]...[/voice]` – đổi giọng cho đoạn (hội thoại nhiều nhân vật)
- `[lang:ko]...[/lang]` – ép ngôn ngữ cho đoạn
- `[rate 0.8]...[/rate]` – đổi tốc độ cho đoạn
- `*từ nhấn mạnh*` – nhấn mạnh
- Từ điển phát âm: "AI" -> "ây ai", "TikTok" -> "tíc tóc"...

## Ngắt nghỉ mặc định (ms, nhân với pause_scale)
dấu phẩy , 、，: 250 · chấm phẩy ; ：: 400 · hai chấm : 350 · chấm . 。: 600 · ? ！ ? !: 650 · ba chấm … ...: 800 · gạch ngang — –: 300 · xuống dòng: 700 · đoạn mới (dòng trống): 1100
