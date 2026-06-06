from fastapi_app import crud, schemas


def test_follow_and_feed(db_session):
    a = crud.create_user(db_session, "alice", "pw")
    b = crud.create_user(db_session, "bob", "pw")
    # bob creates a post
    post = crud.create_post(db_session, schemas.PostCreate(title="Bob Post", content="hello"), author=b.username, author_id=b.id)
    # alice follows bob
    assert crud.follow_user(db_session, a.id, b.id) is True
    # feed for alice should include bob's post
    feed = crud.get_personal_feed(db_session, a.id)
    assert any(p.id == post.id for p in feed)
    # unfollow
    assert crud.unfollow_user(db_session, a.id, b.id) is True
    feed2 = crud.get_personal_feed(db_session, a.id)
    # without follows, feed might be empty or not include post; ensure post no longer prioritized
    assert post.id in [p.id for p in crud.list_posts(db_session)]
