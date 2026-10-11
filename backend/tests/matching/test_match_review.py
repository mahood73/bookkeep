"""Admin preview/apply is the public seam for a reviewed identity correction."""
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database, models
from app.jwt import create_access_token
from app.routers import book_matches
from test_library_match import sessions

WORK = {'id': 748620, 'title': 'The Long Way to a Small, Angry Planet', 'slug': 'the-long-way',
        'canonical_id': None, 'compilation': False, 'state': 'normalized', 'description': 'correct description',
        'contributions': [{'author': {'id': 135809, 'name': 'Becky Chambers'}}],
        'default_ebook_edition_id': 900, 'book_series': [], 'taggings': []}

def client_for(sessions, admin=True):
    with sessions() as db:
        if not admin:
            db.add(models.User(id=2, email='reader@example.test', username='reader', is_admin=False))
        db.add(models.Book(id=304, title='Wrong set', author='Becky Chambers', hardcover_id=1976891,
            hardcover_slug='wrong-set', isbn='9781500453305', booklore_id=2261, ebook_available=True,
            downloaded_release_hashes='["seeded-hash"]', default_ebook_edition_id=800))
        db.add(models.BookRequest(id=1, book_id=304, user_id=1, format='ebook', status='approved', edition_id=801, notes='preserve'))
        db.add(models.DownloadTask(id=1, book_id=304, format='ebook', source='manual', protocol='torrent', state='complete', import_status='imported', client_download_id='seeded-hash'))
        db.commit()
    app = FastAPI()
    app.include_router(book_matches.router, prefix='/api/book-matches')
    def get_db():
        with sessions() as db:
            yield db
    app.dependency_overrides[database.get_db] = get_db
    client = TestClient(app)
    client.headers['Authorization'] = 'Bearer '+create_access_token(1 if admin else 2, 'admin' if admin else 'reader', admin)
    return client

def test_admin_previews_then_applies_without_changing_requests_files_or_downloads(sessions):
    client = client_for(sessions)
    with patch('app.hardcover_matching.resolve_work', AsyncMock(return_value=WORK)), patch('app.hardcover_matching.canonical_family', AsyncMock(return_value={748620})):
        preview = client.post('/api/book-matches/304/preview', json={'hardcover_id':748620})
        assert preview.status_code == 200, preview.text
        with sessions() as db:
            assert db.get(models.Book,304).hardcover_id == 1976891
        result = client.post('/api/book-matches/304/apply', json={'review_token':preview.json()['review_token']})
        assert result.status_code == 200, result.text
    with sessions() as db:
        book = db.get(models.Book,304)
        assert (book.hardcover_id, book.title, book.default_ebook_edition_id) == (748620, WORK['title'], 900)
        assert (book.isbn, book.booklore_id, book.ebook_available, book.downloaded_release_hashes)==('9781500453305',2261,True,'["seeded-hash"]')
        request = db.get(models.BookRequest,1)
        assert (request.book_id, request.status, request.edition_id, request.notes)==(304,'approved',801,'preserve')
        task = db.get(models.DownloadTask,1)
        assert (task.book_id,task.state,task.import_status,task.client_download_id)==(304,'complete','imported','seeded-hash')
        review = db.get(models.HardcoverMatch,304)
        assert review.reviewed_hardcover_id==748620 and review.reviewed_by==1 and review.reviewed_at

def test_regular_user_cannot_preview_or_apply(sessions):
    client = client_for(sessions,admin=False)
    assert client.post('/api/book-matches/304/preview',json={'hardcover_id':748620}).status_code==403
    assert client.post('/api/book-matches/304/apply',json={'review_token':'invalid'}).status_code==403

def test_target_alias_conflict_blocks_preview(sessions):
    client = client_for(sessions)
    with sessions() as db:
        db.add(models.Book(id=305,title='Alias',author='Becky Chambers',hardcover_id=999))
        db.commit()
    with patch('app.hardcover_matching.resolve_work', AsyncMock(return_value=WORK)), patch('app.hardcover_matching.canonical_family', AsyncMock(return_value={748620,999})):
        response=client.post('/api/book-matches/304/preview',json={'hardcover_id':748620})
        assert response.status_code==409 and '305' in response.text

def test_changed_book_requires_new_preview(sessions):
    client=client_for(sessions)
    with patch('app.hardcover_matching.resolve_work', AsyncMock(return_value=WORK)),patch('app.hardcover_matching.canonical_family',AsyncMock(return_value={748620})):
        token=client.post('/api/book-matches/304/preview',json={'hardcover_id':748620}).json()['review_token']
        with sessions() as db:
            db.get(models.Book,304).isbn='different-file-isbn'
            db.commit()
        result=client.post('/api/book-matches/304/apply',json={'review_token':token})
        assert result.status_code==409
    with sessions() as db:
        assert db.get(models.Book,304).hardcover_id==1976891

def test_conflict_created_after_preview_is_rechecked(sessions):
    client=client_for(sessions)
    with patch('app.hardcover_matching.resolve_work',AsyncMock(return_value=WORK)),patch('app.hardcover_matching.canonical_family',AsyncMock(return_value={748620})):
        token=client.post('/api/book-matches/304/preview',json={'hardcover_id':748620}).json()['review_token']
        with sessions() as db:
            db.add(models.Book(id=305,title='Existing target',author='Becky Chambers',hardcover_id=748620));db.commit()
        assert client.post('/api/book-matches/304/apply',json={'review_token':token}).status_code==409
    with sessions() as db:
        assert db.get(models.Book,304).hardcover_id==1976891

def test_invalid_or_other_book_review_cannot_apply(sessions):
    client=client_for(sessions)
    assert client.post('/api/book-matches/304/apply',json={'review_token':'invalid'}).status_code==409
    with patch('app.hardcover_matching.resolve_work',AsyncMock(return_value=WORK)),patch('app.hardcover_matching.canonical_family',AsyncMock(return_value={748620})):
        token=client.post('/api/book-matches/304/preview',json={'hardcover_id':748620}).json()['review_token']
        assert client.post('/api/book-matches/305/apply',json={'review_token':token}).status_code==409
        assert client.post('/api/book-matches/304/apply',json={'review_token':token+'tamper'}).status_code==409

def test_pending_queue_is_admin_only_and_cleared_by_correction(sessions):
    client=client_for(sessions)
    with sessions() as db:
        db.add(models.HardcoverMatch(book_id=304,pending_hardcover_id=748620,pending_reason='Review candidate'));db.commit()
    assert len(client.get('/api/book-matches/pending').json())==1
    with patch('app.hardcover_matching.resolve_work',AsyncMock(return_value=WORK)),patch('app.hardcover_matching.canonical_family',AsyncMock(return_value={748620})):
        token=client.post('/api/book-matches/304/preview',json={'hardcover_id':748620}).json()['review_token']
        assert client.post('/api/book-matches/304/apply',json={'review_token':token}).status_code==200
    assert client.get('/api/book-matches/pending').json()==[]
    client.headers.clear()
    assert client.get('/api/book-matches/pending').status_code==401
