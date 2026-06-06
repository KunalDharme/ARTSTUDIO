import os
from io import BytesIO

import pytest
from fastapi_app import crud, schemas
from fastapi_app.main import UPLOAD_DIR


def test_browse_page_renders(client):
    response = client.get("/browse")
    assert response.status_code == 200
    assert "Browse media" in response.text


def test_watch_media_page_renders(db_session, client):
    media = crud.create_media_item(
        db_session,
        schemas.MediaCreate(
            title="Test Photo",
            description="Test description",
            tags="test,photo",
            uploader="tester",
            media_type="image",
        ),
        filename="test-photo.png",
        uploader_id=None,
    )

    response = client.get(f"/watch/{media.id}")
    assert response.status_code == 200
    assert "Test Photo" in response.text
    assert "Uploaded by tester" in response.text


def test_upload_requires_authentication(client):
    response = client.post(
        "/upload",
        data={"title": "Private Upload", "description": "No auth", "tags": "private"},
        files={"media_file": ("noauth.png", b"fakeimage", "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_authenticated_upload_and_browse(client, tmp_path):
    response = client.post(
        "/register",
        data={"username": "uploaduser", "password": "secret123", "email": "upload@example.com"},
    )
    assert response.status_code == 200 or response.status_code == 303
    assert "access_token" in client.cookies

    upload_filename = "uploaded-test.png"
    file_data = BytesIO(b"fakepngdata")

    response = client.post(
        "/upload",
        data={"title": "Uploaded Test", "description": "Uploaded via test", "tags": "upload,test"},
        files={"media_file": (upload_filename, file_data, "image/png")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Browse media" in response.text

    # verify uploaded media appears in browse results
    browse_response = client.get("/browse")
    assert browse_response.status_code == 200
    assert "Uploaded Test" in browse_response.text

    saved_path = os.path.join(UPLOAD_DIR, upload_filename)
    if os.path.exists(saved_path):
        os.remove(saved_path)
