"""Admin-only reviewed Hardcover identity corrections."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from app import database, models, cache, hardcover_matching as matching
from app.auth import require_admin
from app.jwt import SECRET_KEY, ALGORITHM

router = APIRouter(dependencies=[Depends(require_admin)])

class MatchSelection(BaseModel):
    hardcover_id: int = Field(gt=0)

class MatchConfirmation(BaseModel):
    review_token: str

def book_fingerprint(book):
    values = {column.name: getattr(book, column.name) for column in models.Book.__table__.columns}
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()

def summary(book):
    return {'id': book.id, 'title': book.title, 'author': book.author, 'hardcover_id': book.hardcover_id,
            'file_isbn': book.isbn, 'booklore_id': book.booklore_id}

async def check_conflicts(db, book_id, target):
    ids = await matching.canonical_family(target, db)
    conflict = db.query(models.Book).filter(models.Book.hardcover_id.in_(ids), models.Book.id != book_id).first()
    if conflict:
        raise HTTPException(409, f'Hardcover work already belongs to Bookkeep book {conflict.id}. Review the duplicate before correcting this match.')

@router.get('/pending')
def pending_matches(db: Session = Depends(database.get_db)):
    rows = db.query(models.Book, models.HardcoverMatch).join(models.HardcoverMatch, models.HardcoverMatch.book_id == models.Book.id).filter(models.HardcoverMatch.pending_reason.isnot(None)).order_by(models.Book.id).all()
    return [dict(summary(book), candidate_id=review.pending_hardcover_id, reason=review.pending_reason) for book, review in rows]

@router.post('/{book_id}/preview')
async def preview_match(book_id: int, selection: MatchSelection, db: Session = Depends(database.get_db), user: models.User = Depends(require_admin)):
    book = db.get(models.Book, book_id)
    if not book:
        raise HTTPException(404, 'Book not found')
    work = await matching.resolve_work(selection.hardcover_id, db)
    await check_conflicts(db, book_id, int(work['id']))
    claims = {'purpose': 'hardcover-match-review', 'book_id': book_id, 'user_id': user.id,
              'fingerprint': book_fingerprint(book), 'work': work,
              'exp': datetime.now(timezone.utc) + timedelta(minutes=15)}
    token = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    return {'current': summary(book), 'proposed': matching.metadata_for_work(work),
            'compilation': bool(work.get('compilation')), 'selected_id': selection.hardcover_id,
            'retained_request_editions': [r.edition_id for r in book.requests if r.edition_id], 'review_token': token}

@router.post('/{book_id}/apply')
async def apply_match(book_id: int, confirmation: MatchConfirmation, db: Session = Depends(database.get_db), user: models.User = Depends(require_admin)):
    try:
        claims = jwt.decode(confirmation.review_token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(409, 'Review expired or invalid. Preview the match again.')
    if claims.get('purpose') != 'hardcover-match-review' or claims.get('book_id') != book_id or claims.get('user_id') != user.id:
        raise HTTPException(409, 'Review does not belong to this book and admin')
    work = await matching.resolve_work(claims['work']['id'], db)
    if work != claims['work']:
        raise HTTPException(409, 'Hardcover metadata changed. Preview the match again.')
    book = db.query(models.Book).filter(models.Book.id == book_id).with_for_update().populate_existing().first()
    if not book:
        raise HTTPException(404, 'Book not found')
    if book_fingerprint(book) != claims['fingerprint']:
        raise HTTPException(409, 'Book changed since review. Preview the match again.')
    await check_conflicts(db, book_id, int(work['id']))
    old_hardcover_id = book.hardcover_id
    for field, value in matching.metadata_for_work(work).items():
        setattr(book, field, value)
    review = db.get(models.HardcoverMatch, book_id)
    if review is None:
        review = models.HardcoverMatch(book_id=book_id)
        db.add(review)
    review.reviewed_hardcover_id = int(work['id'])
    review.reviewed_by = user.id
    review.reviewed_at = datetime.now(timezone.utc)
    review.updated_at = review.reviewed_at
    review.pending_hardcover_id = None
    review.pending_reason = None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Conflicting match changed concurrently. Preview again.')
    for resource in ('book_details', 'search', 'series', 'requests_by_hardcover', 'requests_by_hardcover_batch'):
        await cache.clear_cache_pattern(resource+'*')
    return {'book_id': book_id, 'hardcover_id': book.hardcover_id, 'previous_hardcover_id': old_hardcover_id}
