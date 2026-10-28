from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

import streamlit as st


st.set_page_config(page_title="Football Podcast Studio", page_icon="🏈", layout="centered")
st.markdown("""
<style>
  .stApp {background: linear-gradient(145deg,#101c30,#172b3c 55%,#273a3c); color:#f7f4ec}
  .block-container {max-width: 900px; padding-top: 2.4rem}
  h1,h2,h3,p,label {color:#f7f4ec}
  div[data-testid="stFileUploader"] {background:#ffffff0d; border:1px solid #ffffff22; border-radius:16px; padding:12px}
  .hero {padding:25px 28px; border:1px solid #ffffff24; border-radius:22px; background:linear-gradient(120deg,#173552,#263e43); margin-bottom:22px}
  .hero p {color:#d7e3e3; margin-bottom:0}
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>🏈 Football Podcast Studio</h1><p>Upload a recording and add it to a background image. German subtitles are optional.</p></div>', unsafe_allow_html=True)

st.info("Create a video from your audio and a background image. You can add German subtitles later by enabling the optional subtitle setting.")

audio = st.file_uploader("1 · Upload the podcast audio", type=["mp3", "wav", "m4a", "aac", "flac", "ogg"])
bg_path = Path(__file__).parent / "background.jpeg"
use_default_bg = st.checkbox("Use the included football background image", value=True)
image = None if use_default_bg else st.file_uploader("2 · Upload a background image", type=["png", "jpg", "jpeg", "webp"])
add_subtitles = st.checkbox("Add German subtitles (automatic or from an .srt file)", value=False)
custom_srt = None
if add_subtitles:
    custom_srt = st.file_uploader("Optional · Use your own German subtitle file (.srt)", type=["srt"])

with st.expander("Video options", expanded=False):
    video_title = st.text_input("Video title", value="American Football is a Gamble")
    resolution = st.selectbox("Video size", ["1920x1080", "1280x720"], index=0)
    if add_subtitles:
        font_size = st.slider("Subtitle font size", 20, 48, 34)
    else:
        font_size = 34
    ffmpeg_path = st.text_input("FFmpeg command or full path", value="ffmpeg", help="If FFmpeg is not on PATH, enter the full path to ffmpeg.exe.")


def find_ffmpeg(value: str) -> str:
    value = value.strip().strip('"')

    # Prefer the executable bundled in the imageio-ffmpeg PyPI wheel when the
    # default command is selected. This avoids the broken Conda FFmpeg binary.
    if not value or value.lower() == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise RuntimeError(
                "Could not load the bundled FFmpeg. Install it in this environment with "
                "python -m pip install imageio-ffmpeg, then restart the app. "
                f"Details: {type(exc).__name__}: {exc}"
            ) from exc

    found = shutil.which(value)
    if found:
        return found
    if value and Path(value).is_file():
        return value

    # Common Windows location used in the earlier setup.
    candidates = list(Path.home().glob("Downloads/ffmpeg*/**/bin/ffmpeg.exe"))
    if candidates:
        return str(candidates[0])
    raise RuntimeError(
        "The bundled FFmpeg was not found. Install it in this environment with "
        "python -m pip install imageio-ffmpeg, then restart the app."
    )


def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def make_srt_from_audio(audio_file: Path) -> str:
    from faster_whisper import WhisperModel
    import argostranslate.package
    import argostranslate.translate

    @st.cache_resource(show_spinner=False)
    def get_model():
        return WhisperModel("base", device="cpu", compute_type="int8")

    @st.cache_resource(show_spinner=False)
    def get_translation_model():
        installed_languages = argostranslate.translate.get_installed_languages()
        source_language = next((language for language in installed_languages if language.code == "en"), None)
        target_language = next((language for language in installed_languages if language.code == "de"), None)
        if source_language and target_language:
            existing = source_language.get_translation(target_language)
            if existing:
                return existing

        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        package = next((item for item in available if item.from_code == "en" and item.to_code == "de"), None)
        if package is None:
            raise RuntimeError("The free English-to-German translation model is unavailable right now.")
        argostranslate.package.install_from_path(package.download())
        installed_languages = argostranslate.translate.get_installed_languages()
        source_language = next(language for language in installed_languages if language.code == "en")
        target_language = next(language for language in installed_languages if language.code == "de")
        translation = source_language.get_translation(target_language)
        if translation is None:
            raise RuntimeError("The English-to-German model downloaded, but could not be loaded.")
        return translation

    model = get_model()
    segments, info = model.transcribe(str(audio_file), beam_size=5, vad_filter=True, language="en")
    segments = list(segments)
    if not segments:
        raise RuntimeError("I could not detect speech in this recording.")
    with st.spinner("Loading the free offline English-to-German model (first run only)…"):
        translator = get_translation_model()
    source_texts = [re.sub(r"\s+", " ", segment.text).strip() for segment in segments]
    progress = st.progress(0, text="Transcribing finished. Translating subtitles offline…")
    cues = []
    for i, (segment, source) in enumerate(zip(segments, source_texts), start=1):
        try:
            translated = translator.translate(source) if source else ""
        except Exception as exc:
            raise RuntimeError(
                f"German translation failed on subtitle {i}/{len(segments)} "
                f"for text {source!r}: {type(exc).__name__}: {exc!r}"
            ) from exc
        cues.append(f"{i}\n{srt_time(segment.start)} --> {srt_time(segment.end)}\n{translated or source}")
        progress.progress(i / len(segments), text=f"Translated subtitle {i} of {len(segments)}")
    progress.empty()
    return "\n\n".join(cues) + "\n"


def escape_filter_path(path: Path) -> str:
    # FFmpeg filter syntax needs drive colons and special characters escaped.
    value = path.resolve().as_posix()
    value = value.replace(":", r"\:").replace("'", r"\'").replace(",", r"\,").replace("[", r"\[").replace("]", r"\]")
    return value


def create_video(ffmpeg: str, audio_file: Path, image_file: Path, srt_file: Path | None, output_file: Path, size: str, font: int, title: str):
    width, height = size.split("x", maxsplit=1)
    video_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    if srt_file is not None:
        subtitle_filter = f"subtitles='{escape_filter_path(srt_file)}':force_style='FontName=Arial,FontSize={font},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=42'"
        video_filter += f",{subtitle_filter}"
    cmd = [ffmpeg, "-hide_banner", "-y", "-loop", "1", "-framerate", "30", "-i", str(image_file), "-i", str(audio_file),
           "-vf", video_filter,
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-metadata", f"title={title}", "-shortest", "-movflags", "+faststart", str(output_file)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not start FFmpeg at {ffmpeg!r}: {type(exc).__name__}: {exc}"
        ) from exc
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = "FFmpeg returned no error text. Check that the selected ffmpeg.exe is a working FFmpeg build."
        command_text = subprocess.list2cmdline(cmd) if os.name == "nt" else " ".join(repr(part) for part in cmd)
        raise RuntimeError(
            f"FFmpeg exited with code {result.returncode}.\n"
            f"Details: {details[-5000:]}\n"
            f"Command: {command_text}"
        )
    if not output_file.is_file() or output_file.stat().st_size == 0:
        raise RuntimeError(
            "FFmpeg reported success but did not create a non-empty video file. "
            f"Output path: {output_file}"
        )


if st.button("Create podcast video", type="primary", use_container_width=True):
    if not audio:
        st.error("Please upload an audio file first.")
    elif use_default_bg and not bg_path.exists():
        st.error("The included background image is missing from the project folder.")
    elif not use_default_bg and not image:
        st.error("Please upload a background image or select the included one.")
    else:
        with st.spinner("Preparing your podcast video…"):
            try:
                with tempfile.TemporaryDirectory(prefix="football_podcast_") as temp_dir:
                    temp = Path(temp_dir)
                    audio_path = temp / (Path(audio.name).stem + Path(audio.name).suffix.lower())
                    audio_path.write_bytes(audio.getvalue())
                    if use_default_bg:
                        image_path = bg_path
                    else:
                        suffix = Path(image.name).suffix.lower() or ".jpg"
                        image_path = temp / f"background{suffix}"
                        image_path.write_bytes(image.getvalue())
                    srt_text = None
                    srt_path = None
                    if add_subtitles:
                        if custom_srt:
                            srt_text = custom_srt.getvalue().decode("utf-8-sig", errors="replace")
                        else:
                            srt_text = make_srt_from_audio(audio_path)
                        srt_path = temp / "subtitles_de.srt"
                        srt_path.write_text(srt_text, encoding="utf-8-sig")
                    video_name = "football_podcast_with_subtitles.mp4" if add_subtitles else "football_podcast.mp4"
                    video_path = temp / video_name
                    ffmpeg = find_ffmpeg(ffmpeg_path)
                    create_video(ffmpeg, audio_path, image_path, srt_path, video_path, resolution, font_size, video_title)
                    st.success("Your video is ready.")
                    video_bytes = video_path.read_bytes()
                    st.video(video_bytes)
                    st.download_button("Download MP4 video", video_bytes, file_name=video_name, mime="video/mp4", use_container_width=True)
                    if srt_text is not None:
                        st.download_button("Download German subtitles (.srt)", srt_text.encode("utf-8-sig"), file_name="subtitles_de.srt", mime="application/x-subrip", use_container_width=True)
            except Exception as exc:
                st.error(f"Could not create the video: {type(exc).__name__}: {exc!r}")
                with st.expander("Technical details"):
                    st.code(traceback.format_exc())

st.caption("When German subtitles are enabled, speech recognition and translation run on your computer. The first run may download the required models.")
