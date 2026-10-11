"""Verified Hardcover identities, separate from library file identifiers."""
import re
import unicodedata
from datetime import datetime, timezone
from fastapi import HTTPException
from app import models

WORK_FIELDS = '''id title slug canonical_id compilation state description pages
release_date release_year cached_image rating ratings_count users_count activities_count
 default_physical_edition_id default_ebook_edition_id default_audio_edition_id
 contributions { contribution author { id name } }
 book_series { position series { id name } }
 taggings(limit: 10) { tag { tag } }'''

async def resolve_work(work_id, db):
    """Follow canonical aliases; fail closed on missing, cyclic or excessive chains."""
    from app.routers.hardcover import execute_graphql
    visited = []
    for _ in range(12):
        work_id = int(work_id)
        if work_id in visited:
            raise HTTPException(422, 'Hardcover canonical chain contains a cycle')
        visited.append(work_id)
        data = await execute_graphql('query MatchWork($id: Int!) { books_by_pk(id: $id) { '+WORK_FIELDS+' } }', {'id': work_id}, db)
        work = data.get('books_by_pk')
        if not work or int(work['id']) != work_id:
            raise HTTPException(422, 'Hardcover work was not found')
        canonical_id = work.get('canonical_id')
        if not canonical_id or int(canonical_id) == work_id:
            if work.get('state') in ('deleted', 'hidden'):
                raise HTTPException(422, 'Hardcover work is not available')
            return work
        work_id = canonical_id
    raise HTTPException(422, 'Hardcover canonical chain is too long')

def author_names(work):
    contributions = work.get('contributions') or []
    authors = [c['author'] for c in contributions if (c.get('author') or {}).get('name') and c.get('contribution') in (None, 'Author')]
    return authors

def normalized(value):
    return re.sub(r'\W+', ' ', unicodedata.normalize('NFKC', value or '').casefold()).strip()

def agrees_with_library(work, title, author):
    names = author_names(work)
    return normalized(work.get('title')) == normalized(title) and bool(names) and normalized(author) == normalized(', '.join(a['name'] for a in names))

def queue_review(db, book, candidate_id, reason):
    review = db.get(models.HardcoverMatch, book.id)
    if review is None:
        review = models.HardcoverMatch(book_id=book.id)
        db.add(review)
    review.pending_hardcover_id = candidate_id
    review.pending_reason = reason
    review.updated_at = datetime.now(timezone.utc)

async def preserve_library_identity(db, book, candidate_id):
    """Only a reviewed correction may replace a different canonical identity."""
    if book.hardcover_id is None:
        queue_review(db, book, candidate_id, 'Local-only book: choose a match explicitly')
        return True
    review = db.get(models.HardcoverMatch, book.id)
    if review and review.reviewed_at:
        return True
    if int(book.hardcover_id) == int(candidate_id):
        return False
    try:
        existing = await resolve_work(book.hardcover_id, db)
        candidate = await resolve_work(candidate_id, db)
    except HTTPException:
        queue_review(db, book, candidate_id, 'Could not verify Hardcover canonical identities')
        return True
    if existing['id'] == candidate['id']:
        # Keep the stored alias; catalogue refresh can update metadata for this work.
        return True
    queue_review(db, book, candidate['id'], 'Library candidate differs from the existing Hardcover work')
    return True

async def canonical_family(work_id, db):
    """Find reverse aliases too, so a local alias cannot hide an ID conflict."""
    from app.routers.hardcover import execute_graphql
    family = {int(work_id)}
    frontier = list(family)
    for _ in range(12):
        result = await execute_graphql('query MatchAliases($ids: [Int!]!) { books(where: {canonical_id: {_in: $ids}}, limit: 1001) { id } }', {'ids': frontier}, db)
        aliases = result.get('books', [])
        if len(aliases) > 1000:
            raise HTTPException(422, 'Too many Hardcover aliases to verify safely')
        frontier = [int(row['id']) for row in aliases if int(row['id']) not in family]
        if not frontier:
            return family
        family.update(frontier)
    raise HTTPException(422, 'Hardcover alias graph is too deep')

def metadata_for_work(work):
    authors = author_names(work)
    series = (work.get('book_series') or [{}])[0]
    series_info = series.get('series') or {}
    return {
        'hardcover_id': int(work['id']), 'hardcover_slug': work.get('slug'),
        'title': work['title'], 'author': ', '.join(a['name'] for a in authors) or 'Unknown Author',
        'author_id': authors[0].get('id') if authors else None,
        'description': work.get('description'), 'cover_url': work['cached_image'].get('url') if isinstance(work.get('cached_image'), dict) else None,
        'page_count': work.get('pages'), 'published_date': work.get('release_date') or (str(work['release_year']) if work.get('release_year') else None),
        'release_year': work.get('release_year'), 'rating': work.get('rating'),
        'ratings_count': work.get('ratings_count'), 'users_count': work.get('users_count'),
        'activities_count': work.get('activities_count'),
        'default_edition_id': work.get('default_physical_edition_id'),
        'default_physical_edition_id': work.get('default_physical_edition_id'),
        'default_ebook_edition_id': work.get('default_ebook_edition_id'),
        'default_audio_edition_id': work.get('default_audio_edition_id'),
        'series': series_info.get('name'), 'series_id': series_info.get('id'), 'series_position': series.get('position'),
        'genres': ', '.join(t['tag']['tag'] for t in work.get('taggings') or [] if t.get('tag', {}).get('tag')) or None,
    }
