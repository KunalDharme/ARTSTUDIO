from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.database import Base
from fastapi_app import crud, schemas


def test_user_creation_and_auth(db_session):
    user = crud.create_user(db_session, "tester", "secret", email="t@example.com")
    assert user.username == "tester"
    assert user.email == "t@example.com"
    assert user.hashed_password != "secret"
    assert crud.authenticate_user(db_session, "tester", "secret") is not None
    assert crud.authenticate_user(db_session, "tester", "wrong") is None


def test_posts_crud(db_session):
    user = crud.create_user(db_session, "author", "pw")
    post = crud.create_post(db_session, schemas.PostCreate(title="Hello World", content="**bold**"), author=user.username, author_id=user.id)
    assert post.slug.startswith("hello-world") or post.slug.startswith("hello")
    fetched = crud.get_post(db_session, post.id)
    assert fetched.content == "**bold**"
    updated = crud.update_post(db_session, fetched, "New Title", "new content", True)
    assert updated.title == "New Title"
    crud.delete_post(db_session, updated)
    assert crud.get_post(db_session, post.id) is None
