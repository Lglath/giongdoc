# GiongDoc – Sơ đồ chức năng & phân chia module bảo trì

## 1. Chức năng cho người dùng
| Nhóm | Chức năng | Module phụ trách |
|---|---|---|
| Giọng đọc | 25 giọng neural (Việt: Hoài My, Nam Minh; Anh Mỹ/Anh; Hàn; Trung), giọng macOS offline (Linh, Yuna, Tingting, Samantha…), lọc theo ngôn ngữ | `engines/edge.py`, `engines/macsay.py`, `engines/registry.py` |
| Giọng tùy chỉnh | Thêm giọng từ file 5–30 giây hoặc ghi âm, kèm lời thoại mẫu, **bắt buộc xác nhận đồng ý**; chạy F5-TTS / XTTS (cài thêm) | `engines/custom*.py`, `ui/custom_voice_dialog.py` |
| Ngôn ngữ | Tự nhận diện Việt/Anh/Hàn/Trung, văn bản trộn nhiều ngôn ngữ tự đổi giọng, ép bằng `[lang:..]` | `text/detect.py` |
| Đọc tự nhiên | Ngắt nghỉ theo dấu câu (phẩy 250ms, chấm 600ms, ba chấm 800ms, đoạn mới 1100ms…), tách câu dài ở liên từ, đọc số/ngày/tiền/đơn vị kiểu tiếng Việt, từ điển phát âm (AI → ây ai, TikTok → tíc tóc) | `text/*` |
| Làm mượt | Cắt lặng thừa, fade chống tiếng "tách", crossfade, cân âm lượng từng câu về -16 LUFS, limiter, "room tone" lấp khoảng lặng, ngắt nghỉ dao động nhẹ ±8% cho giống người | `audio/smoothing.py`, `audio/dsp.py` |
| Chỉnh sửa | Chèn ngắt nghỉ 300/600/1000ms (Cmd+Shift+P), đổi giọng theo đoạn (hội thoại nhiều nhân vật), nhấn mạnh `*..*`, đổi tốc độ đoạn, làm sạch văn bản, tìm & thay (Cmd+F), đếm từ + ước lượng thời lượng, tô màu thẻ, kéo thả .txt/.md/.docx | `ui/editor.py`, `ui/text_tools.py` |
| Điều chỉnh | Tốc độ, cao độ, âm lượng, độ dài ngắt nghỉ, làm mượt nâng cao | `ui/main_window.py` |
| Nghe & xuất | Nghe thử câu hiện tại, đọc toàn bộ có tô sáng câu đang đọc, dừng/hủy, xuất MP3/WAV/M4A + phụ đề .srt (dùng cho video TikTok) | `service.py`, `audio/export.py`, `ui/workers.py` |
| Dự án | Lưu/mở `.giongdoc`, file gần đây, tự lưu nháp 20 giây | `project/model.py` |

## 2. Luồng xử lý
Văn bản → `text.pipeline.prepare` (markup → chuẩn hóa → từ điển → tách câu + ngắt nghỉ) → `SynthesisService` (chọn giọng theo ngôn ngữ từng câu, cache từng câu: sửa 1 câu chỉ đọc lại câu đó) → engine → `audio.timeline.assemble_with_timeline` (làm mượt + mốc thời gian) → phát / xuất file + SRT.

## 3. Quy tắc bảo trì
- Mọi module chỉ phụ thuộc `giongdoc/core.py`. Thêm engine mới = 1 file trong `engines/` implement `TTSEngine` + đăng ký trong `registry._build`.
- Mỗi module có test riêng: `tests/test_text_*.py`, `test_engines.py`, `test_audio.py`, `test_ui_smoke.py` (`make test`, hiện 129 pass).
- Thêm ngôn ngữ mới: thêm vào `Language`, quy tắc số trong `text/normalize.py`, dấu câu trong `text/segmenter.py`, giọng trong `engines/edge.py`.

## 4. Lộ trình gợi ý
1. Giọng offline chất lượng cao cho tiếng Việt (Piper/F5-TTS-Vietnamese tải theo yêu cầu).
2. Đọc file PDF/EPUB dài theo chương, xuất nhiều file.
3. Nhạc nền + ducking, chia sẻ trực tiếp sang video.
