"""Library sync must not replace a requested work with a search collection."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Book, User
from app.tasks import sync_from_booklore

@pytest.fixture
def sessions():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(User(id=1, email='admin@example.test', username='admin', is_admin=True))
        db.commit()
    yield factory
    engine.dispose()

@pytest.mark.parametrize('title,author,correct,wrong,collection,gid', [
    ('The Food of the Gods', 'H. G. Wells', 458307, 1836489, 'The Novels of H. G. Wells: Volume One', 2253),
    ('The Long Way to a Small, Angry Planet', 'Becky Chambers', 748620, 1976891, 'Becky Chambers 4 Book Set', 2261),
])
def test_sync_keeps_existing_work_when_search_returns_collection(sessions, title, author, correct, wrong, collection, gid):
    with sessions() as db:
        db.add(Book(id=304, title=title, author=author, hardcover_id=correct,
                    hardcover_slug='correct-work', description='original description', page_count=198))
        db.commit()
    library = [{'id': gid, 'title': title, 'metadata': {'authors': [author], 'isbn13': '9781500453305'}}]
    candidate = {'id': wrong, 'title': collection, 'slug': 'wrong-collection', 'compilation': True,
                 'description': 'collection description', 'pages': 564,
                 'contributions': [{'author': {'name': author}}]}
    async def resolve(work_id, db):
        return {'id': int(work_id)}
    with patch('app.hardcover_matching.resolve_work', side_effect=resolve), patch('app.tasks.SessionLocal', sessions), patch('app.routers.booklore.get_default_booklore_server', return_value=SimpleNamespace(name='library', ebook_library_id=None, audiobook_library_id=None)), patch('app.routers.booklore.get_booklore_books', AsyncMock(return_value=library)), patch('app.routers.hardcover.lookup_book_by_title_author', AsyncMock(return_value=candidate)), patch('app.tasks.asyncio.sleep', AsyncMock()):
        asyncio.run(sync_from_booklore())
    with sessions() as db:
        book = db.get(Book, 304)
        assert book.hardcover_id == correct
        assert book.hardcover_slug == 'correct-work'
        assert book.description == 'original description'
        assert book.page_count == 198
        assert book.booklore_id == gid
        assert book.ebook_available
        from app.models import HardcoverMatch
        assert db.get(HardcoverMatch, book.id).pending_hardcover_id == wrong

@pytest.mark.parametrize('hardcover_id,reviewed,candidate_id',[(None,False,1976891),(748620,True,1976891),(111,False,748620)])
def test_local_only_reviewed_and_canonical_aliases_survive_sync(sessions,hardcover_id,reviewed,candidate_id):
    from app.models import HardcoverMatch
    from datetime import datetime,timezone
    with sessions() as db:
        db.add(Book(id=304,title='A work',author='A Writer',hardcover_id=hardcover_id,description='retained',isbn='file-isbn'))
        if reviewed:db.add(HardcoverMatch(book_id=304,reviewed_hardcover_id=hardcover_id,reviewed_at=datetime.now(timezone.utc)))
        db.commit()
    library=[{'id':1,'title':'A work','metadata':{'authors':['A Writer'],'isbn13':'file-isbn'}}]
    async def resolve(work_id,db):return {'id':748620}
    with patch('app.hardcover_matching.resolve_work',side_effect=resolve),patch('app.tasks.SessionLocal',sessions),patch('app.routers.booklore.get_default_booklore_server',return_value=SimpleNamespace(name='library',ebook_library_id=None,audiobook_library_id=None)),patch('app.routers.booklore.get_booklore_books',AsyncMock(return_value=library)),patch('app.routers.hardcover.lookup_book_by_title_author',AsyncMock(return_value={'id':candidate_id,'title':'Collection','slug':'candidate'})),patch('app.tasks.asyncio.sleep',AsyncMock()):
        asyncio.run(sync_from_booklore())
    with sessions() as db:
        book=db.get(Book,304)
        assert (book.hardcover_id,book.description,book.isbn,book.booklore_id)==(hardcover_id,'retained','file-isbn',1)


def test_isbn_match_cannot_reassign_an_existing_work(sessions):
    with sessions() as db:
        db.add(Book(id=304,title='Original title',author='A Writer',hardcover_id=123,isbn='same-isbn',description='original'))
        db.commit()
    library=[{'id':1,'title':'Different collection','metadata':{'authors':['A Writer'],'isbn13':'same-isbn'}}]
    async def resolve(work_id,db):return {'id':work_id}
    with patch('app.hardcover_matching.resolve_work',side_effect=resolve),patch('app.tasks.SessionLocal',sessions),patch('app.routers.booklore.get_default_booklore_server',return_value=SimpleNamespace(name='library',ebook_library_id=None,audiobook_library_id=None)),patch('app.routers.booklore.get_booklore_books',AsyncMock(return_value=library)),patch('app.routers.hardcover.lookup_book_by_title_author',AsyncMock(return_value={'id':456,'title':'Different collection'})),patch('app.tasks.asyncio.sleep',AsyncMock()):
        asyncio.run(sync_from_booklore())
    with sessions() as db:
        book=db.get(Book,304)
        assert (book.hardcover_id,book.description,book.booklore_id,book.ebook_available)==(123,'original',None,False)


def test_new_uncertain_collection_goes_to_review_without_identity(sessions):
    library=[{'id':1,'title':'A single story','metadata':{'authors':['A Writer']}}]
    candidate={'id':456,'title':'A Writer Complete Works','compilation':False}
    with patch('app.hardcover_matching.resolve_work',AsyncMock(return_value=candidate)),patch('app.hardcover_matching.canonical_family',AsyncMock(return_value={456})),patch('app.tasks.SessionLocal',sessions),patch('app.routers.booklore.get_default_booklore_server',return_value=SimpleNamespace(name='library',ebook_library_id=None,audiobook_library_id=None)),patch('app.routers.booklore.get_booklore_books',AsyncMock(return_value=library)),patch('app.routers.hardcover.lookup_book_by_title_author',AsyncMock(return_value=candidate)),patch('app.tasks.asyncio.sleep',AsyncMock()):
        asyncio.run(sync_from_booklore())
    with sessions() as db:
        book=db.query(Book).one()
        assert book.title=='A single story' and book.hardcover_id is None and book.booklore_id==1
        from app.models import HardcoverMatch
        assert db.get(HardcoverMatch,book.id).pending_hardcover_id==456


def test_existing_library_link_keeps_reviewed_match_without_lookup(sessions):
    with sessions() as db:
        db.add(Book(id=304,title='A work',author='A Writer',hardcover_id=123,booklore_id=1))
        db.commit()
    lookup=AsyncMock()
    with patch('app.tasks.SessionLocal',sessions),patch('app.routers.booklore.get_default_booklore_server',return_value=SimpleNamespace(name='library',ebook_library_id=None,audiobook_library_id=None)),patch('app.routers.booklore.get_booklore_books',AsyncMock(return_value=[{'id':1,'title':'A work','metadata':{'hardcoverId':'different-slug'}}])),patch('app.routers.hardcover.lookup_book_by_title_author',lookup):
        asyncio.run(sync_from_booklore())
    lookup.assert_not_called()
    with sessions() as db:assert db.get(Book,304).hardcover_id==123


@pytest.mark.parametrize('existing', [True, False])
def test_verified_canonical_family_reuses_existing_row_and_allows_real_collections(sessions, existing):
    candidate = {'id': 111, 'title': 'Collected Stories', 'slug': 'collected-stories',
                 'compilation': True, 'contributions': [{'author': {'name': 'A Writer'}}]}
    canonical = dict(candidate, id=222)
    if existing:
        with sessions() as db:
            db.add(Book(id=304, title='Collected Stories', author='A Writer', hardcover_id=111))
            db.commit()
    # Different spelling bypasses the literal title match; canonical family must find the row.
    library = [{'id': 1, 'title': 'Collected Stories!', 'metadata': {'authors': ['A Writer']}}]
    with patch('app.hardcover_matching.resolve_work', AsyncMock(return_value=canonical)), patch('app.hardcover_matching.canonical_family', AsyncMock(return_value={111, 222})), patch('app.tasks.SessionLocal', sessions), patch('app.routers.booklore.get_default_booklore_server', return_value=SimpleNamespace(name='library', ebook_library_id=None, audiobook_library_id=None)), patch('app.routers.booklore.get_booklore_books', AsyncMock(return_value=library)), patch('app.routers.hardcover.lookup_book_by_title_author', AsyncMock(return_value=candidate)), patch('app.tasks.asyncio.sleep', AsyncMock()):
        asyncio.run(sync_from_booklore())
    with sessions() as db:
        book = db.query(Book).one()
        assert book.hardcover_id == (111 if existing else 222)
        assert book.id == 304 if existing else book.id > 0
        from app.models import HardcoverMatch
        assert db.get(HardcoverMatch, book.id) is None


def test_slug_fallback_cannot_replace_an_unrelated_identity(sessions):
    with sessions() as db:
        db.add(Book(id=304, title='Original', author='A Writer', hardcover_id=123,
                    hardcover_slug='reused-slug', description='preserved'))
        db.commit()
    candidate = {'id': 456, 'title': 'Different work', 'slug': 'reused-slug',
                 'contributions': [{'author': {'name': 'A Writer'}}]}
    async def resolve(work_id, db):
        return candidate if int(work_id) == 456 else {'id': 123}
    library = [{'id': 1, 'title': 'Different work', 'metadata': {'authors': ['A Writer']}}]
    with patch('app.hardcover_matching.resolve_work', side_effect=resolve), patch('app.hardcover_matching.canonical_family', AsyncMock(return_value={456})), patch('app.tasks.SessionLocal', sessions), patch('app.routers.booklore.get_default_booklore_server', return_value=SimpleNamespace(name='library', ebook_library_id=None, audiobook_library_id=None)), patch('app.routers.booklore.get_booklore_books', AsyncMock(return_value=library)), patch('app.routers.hardcover.lookup_book_by_title_author', AsyncMock(return_value=candidate)), patch('app.tasks.asyncio.sleep', AsyncMock()):
        asyncio.run(sync_from_booklore())
    with sessions() as db:
        book = db.get(Book, 304)
        assert (book.hardcover_id, book.title, book.description, book.booklore_id) == (123, 'Original', 'preserved', None)
        from app.models import HardcoverMatch
        assert db.get(HardcoverMatch, 304).pending_hardcover_id == 456
