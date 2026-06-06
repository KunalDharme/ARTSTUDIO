# AartStudio

`AartStudio` is a FastAPI-powered media portal for uploading and browsing photos and videos.

## Run locally

```bash
cd aartstudio
..\venv\Scripts\activate  # Windows
pip install -r ..\requirements.txt
uvicorn aartstudio.main:app --reload
```

Open `http://127.0.0.1:8000` in your browser.

## Features

- Upload image or MP4/WebM video files
- Browse media with tag filters and pagination
- Watch video files and view uploaded photos
- SQLite database backend with SQLAlchemy

## Notes

The main FastAPI app package is in `aartstudio/fastapi_app` after the move.
