# Football Podcast Studio

A small local Streamlit app for repeatedly turning podcast audio into an MP4 with a fixed football background. German subtitles are optional.

## What it does

- Accepts MP3, WAV, M4A, AAC, FLAC, or OGG audio.
- Uses the included `background.jpeg`, or lets you upload another background.
- Creates a video without subtitles by default, so audio is placed directly over the background image.
- Optionally transcribes the audio locally with Faster-Whisper (`base`, CPU mode).
- Optionally translates captions to German locally with the free Argos Translate English-to-German model, downloaded the first time it is needed.
- Burns German captions into the video and provides a separate `.srt` download when subtitles are enabled.
- Lets you supply your own German `.srt` instead of automatic transcription/translation.

The audio and subtitle translation stay on your computer. Subtitles are off by default. If enabled, the first automatic subtitle run needs internet to download the Whisper speech model and the Argos English-to-German model. Later translations run locally. You can also upload your own German SRT.

## Windows setup

1. Install Python 3.10 or 3.11.
2. FFmpeg is bundled through the `imageio-ffmpeg` Python package, so a separate FFmpeg installation or PATH setup is not needed.
3. Extract this project folder.
4. Open PowerShell in the extracted folder and run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   streamlit run app.py
   ```

The app opens in your browser at `http://localhost:8501`. Keep the PowerShell window open while using it. By default, video creation skips transcription and translation. If you enable automatic subtitles, the first run downloads the Whisper `base` model and may take a few minutes.

## Notes

- This is a local web app, so uploaded recordings are processed on your computer; it is not a public website.
- First-time subtitle model downloads need an internet connection; later automatic translation runs locally without Google Translate requests.
- Only upload recordings you own or have permission to use.
