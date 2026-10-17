import assert from 'node:assert/strict';
import { mock, test } from 'node:test';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Routes } from 'react-router-dom';
import { StaticRouter } from 'react-router-dom/server';
import { UserProvider } from '@/contexts/UserContext';
import BookDetails from './BookDetails';

// Server rendering needs only the visibility/storage browser boundaries.
Object.defineProperty(globalThis, 'document', { value: { hidden: false }, configurable: true });
Object.defineProperty(globalThis, 'localStorage', {
  value: { getItem: () => null },
  configurable: true,
});
const network = mock.method(globalThis, 'fetch', async () => {
  throw new Error('Book details tests must not contact a network');
});

function renderBook(ebook: string | null, audiobook: string | null = null, available = { ebook: false, audiobook: false }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  client.setQueryData(['hardcover', 'book', '15095'], {
    id: '15095', hardcoverId: 15095, title: 'The Gentleman', author: 'Forrest Leo',
    description: 'A fixture book.', cover: '/fixture.jpg', genres: [], rating: 3.9,
  });
  client.setQueryData(['book', 'by-hardcover', 15095], {
    id: 123, hardcover_id: 15095, ebook_available: available.ebook, audiobook_available: available.audiobook,
  });
  client.setQueryData(['requests', 'by-hardcover', 15095], { ebook, audiobook, book_id: 123 });
  client.setQueryData(['direct-downloads', 'settings'], { enabled: true });
  client.setQueryData(['hardcover', 'book-prompts', 15095, 4, 30], []);
  client.setQueryData(['oidc-config-logout'], {});
  client.setQueryData(['currentUser'], {
    id: 1, username: 'fixture-reader', is_admin: false,
    can_request_ebook: true, can_request_audiobook: true, can_download: true,
  });
  try {
    const html = renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <UserProvider>
          <StaticRouter location="/book/15095">
            <Routes><Route path="/book/:id" element={<BookDetails />} /></Routes>
          </StaticRouter>
        </UserProvider>
      </QueryClientProvider>
    );
    assert.equal(network.mock.callCount(), 0);
    return html.replace(/<[^>]*>/g, '');
  } finally {
    client.clear();
  }
}

test('an approved ebook request does not claim processing or an active download', () => {
  const text = renderBook('approved');
  assert.match(text, /eBook request: Approved/);
  assert.doesNotMatch(text, /Processing|Downloading/);
});


test('approved requests retain manual search and clear actions', () => {
  const text = renderBook('approved');
  assert.match(text, /Direct Download/);
  assert.match(text, /Search Prowlarr/);
  assert.match(text, /Clear Request/);
  assert.doesNotMatch(text, /Request Book/);
});

test('a pending request shows that approval is pending', () => {
  const text = renderBook('pending');
  assert.match(text, /eBook request: Pending approval/);
  assert.doesNotMatch(text, /Processing|Downloading/);
});

test('each format retains its own request status when the other is available', () => {
  const text = renderBook('available', 'approved');
  assert.match(text, /eBook Available/);
  assert.match(text, /eBook request: Available/);
  assert.match(text, /Audiobook request: Approved/);
  assert.doesNotMatch(text, /Processing|Downloading/);
});

test('library availability does not hide a pending request for the other format', () => {
  const text = renderBook(null, 'pending', { ebook: true, audiobook: false });
  assert.match(text, /eBook Available/);
  assert.match(text, /Audiobook request: Pending approval/);
  assert.doesNotMatch(text, /eBook request:/);
});

for (const [status, label] of [['processing', 'Processing'], ['not_found', 'Not found'], ['denied', 'Denied']]) {
  test(`a ${status} state is labelled as a request state`, () => {
    const text = renderBook(null, status);
    assert.match(text, new RegExp(`Audiobook request: ${label}`));
    assert.doesNotMatch(text, /Downloading/);
  });
}

test('missing requests do not fabricate status labels and preserve request/search actions', () => {
  const text = renderBook(null);
  assert.doesNotMatch(text, /request:|Processing/);
  assert.match(text, /Request Book/);
  assert.match(text, /Direct Download/);
  assert.match(text, /Search Prowlarr/);
});

test('an unfamiliar request status does not default to processing', () => {
  const text = renderBook('constructor');
  assert.match(text, /eBook request: Unknown status/);
  assert.doesNotMatch(text, /Processing|Downloading/);
});
