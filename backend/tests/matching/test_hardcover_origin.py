"""Known catalogue identities survive first library import without rediscovery."""
from types import SimpleNamespace
from fastapi import HTTPException
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import models, tasks
from app.database import Base
from app.routers import book_matches

@pytest.fixture
def sessions():
    engine=create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        db.add(models.User(id=1,email='fixture@example.invalid',username='fixture',is_admin=True))
        db.commit()
    yield factory
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('library_hardcover_id,needs_review',[(None,False),(123,False),(456,True)])
@pytest.mark.parametrize('provider_available',[True,False])
async def test_hardcover_list_identity_survives_first_library_import_without_a_new_guess(sessions,monkeypatch,library_hardcover_id,needs_review,provider_available):
    correct=123
    wrong=456
    with sessions() as db:
        db.add(models.UserHardcoverSync(user_id=1,is_enabled=True,sync_to_read=True,default_format='ebook'))
        db.commit()
    work={'id':correct,'title':'Requested Book','slug':'requested-book',
          'description':'Hardcover description','pages':198,
          'contributions':[{'author':{'id':10,'name':'A Writer','slug':'a-writer'}}]}
    async def graphql(query,variables,token):
        if 'books_by_pk' in query:
            return {'books_by_pk':work}
        return {'me':[{'user_books':[{'book':{'id':correct,'title':'Requested Book'}}]}]}
    monkeypatch.setattr(tasks,'SessionLocal',sessions)
    monkeypatch.setattr(tasks,'_hardcover_graphql',graphql)
    monkeypatch.setattr('app.routers.settings.get_hardcover_token',lambda db:('fixture-token',False))
    monkeypatch.setattr(tasks.asyncio,'sleep',AsyncMock())
    await tasks.sync_hardcover_lists_for_user(1)
    with sessions() as db:
        book=db.query(models.Book).one()
        book_id=book.id
        assert book.hardcover_id==correct
        assert db.query(models.BookRequest).one().source=='hardcover_sync'
    library=[{'id':99,'title':'Requested Book','metadata':{'authors':['A Writer'],'isbn13':'fixture-isbn','description':'File description','pageCount':12}}]
    if library_hardcover_id is not None:
        library[0]['metadata']['hardcoverId']=library_hardcover_id
    candidate={'id':wrong,'title':'A Writer Complete Works','slug':'wrong-collection',
               'compilation':True,'contributions':[{'author':{'name':'A Writer'}}]}
    lookup=AsyncMock(return_value=candidate)
    monkeypatch.setattr('app.routers.booklore.get_default_booklore_server',lambda db:SimpleNamespace(name='fixture',url='https://fixture.invalid',ebook_library_id=None,audiobook_library_id=None))
    monkeypatch.setattr('app.routers.booklore.get_booklore_books',AsyncMock(return_value=library))
    monkeypatch.setattr('app.routers.hardcover.lookup_book_by_title_author',lookup)
    async def resolve(work_id,db):
        return work if int(work_id)==correct else candidate
    fetched_ids=[]
    async def query(query, variables, db):
        fetched_ids.append(variables['id'])
        if not provider_available:
            raise HTTPException(503,'fixture provider unavailable')
        return {'books_by_pk': await resolve(variables['id'], db)}
    monkeypatch.setattr('app.routers.hardcover.execute_graphql', query)
    await tasks.sync_from_booklore()
    with sessions() as db:
        book=db.get(models.Book,book_id)
        assert book.hardcover_id==correct
        assert book.booklore_id==99
        if library_hardcover_id is None:
            assert book.description=='Hardcover description'
            assert book.page_count==198
        pending=book_matches.pending_matches(db)
        if needs_review:
            assert [(row['hardcover_id'],row['candidate_id']) for row in pending]==[(correct,wrong)]
        else:
            assert pending==[]
        lookup.assert_not_awaited()
        if library_hardcover_id is None:
            assert fetched_ids==[correct]

