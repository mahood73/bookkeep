import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { downloadsApi } from './api';

Object.defineProperty(globalThis, 'localStorage', {
  value: { getItem: () => null }, configurable: true,
});
afterEach(() => mock.restoreAll());

test('retry sends only the stored task ID and never deletes first', async () => {
  const calls: { url: string; method?: string; body?: BodyInit | null }[] = [];
  mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, method: options.method, body: options.body });
    return Response.json({ task_id: 8, status: 'downloading', message: 'Download retry started' });
  });
  assert.equal((await downloadsApi.retryTask(7)).task_id, 8);
  assert.deepEqual(calls, [{ url: '/api/downloads/tasks/7/retry', method: 'POST', body: undefined }]);
});

test('failed retry retains an actionable validation message without another request', async () => {
  const network = mock.method(globalThis, 'fetch', async () => Response.json({
    detail: [{ loc: ['body', 'size_bytes'], msg: 'Field required', type: 'missing',
               input: { private_value: 'must not appear in the toast' } }],
  }, { status: 422 }));
  await assert.rejects(downloadsApi.retryTask(7), { message: 'size_bytes: Field required' });
  assert.equal(network.mock.callCount(), 1);
});

for (const [body, status, expected] of [
  [{ detail: 'Download already active' }, 409, 'Download already active'],
  [{ detail: { message: 'Retry import instead' } }, 400, 'Retry import instead'],
  [{ message: 'Service unavailable' }, 503, 'Service unavailable'],
  [null, 500, 'API request failed: 500'],
  [{ detail: { unexpected: { secret: 'hidden' } } }, 422, 'API request failed: 422'],
] as const) {
  test(`API errors stay readable for status ${status}: ${exp…5619 tokens truncated…rApi = {
  getAll: () =>
    apiRequest<Array<any>>('/api/readarr/'),

  getById: (id: number) =>
    apiRequest<any>(`/api/readarr/${id}`),

  create: (server: any) =>
    apiRequest<any>('/api/readarr/', {
      method: 'POST',
      body: JSON.stringify(server),
    }),

  update: (id: number, server: any) =>
    apiRequest<any>(`/api/readarr/${id}`, {
      method: 'PUT',
      body: JSON.stringify(server),
    }),

  delete: (id: number) =>
    apiRequest<void>(`/api/readarr/${id}`, {
      method: 'DELETE',
    }),

  testConnection: (config: { hostname: string; port: number; use_ssl: boolean; api_key: string; url_base?: string }) =>
    apiRequest<{
      success: boolean;
      error?: string;
      quality_profiles?: Array<{ id: number; name: string }>;
      root_folders?: Array<{ path: string; freeSpace?: number; totalSpace?: number }>;
      tags?: Array<{ id: number; label: string }>;
    }>('/api/readarr/test-connection', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  getConfiguredFormats: () =>
    apiRequest<{ ebook: boolean; audiobook: boolean }>('/api/readarr/configured-formats'),

  getAvailability: (hardcoverId: number) =>
    apiRequest<{ ebook: boolean; audiobook: boolean }>(`/api/readarr/availability/${hardcoverId}`),

  getAvailabilityBatch: (hardcoverIds: number[], isbnMap?: Record<number, string[]>) =>
    apiRequest<{ results: Array<{ hardcover_id: number; ebook: boolean; audiobook: boolean }> }>(
      '/api/readarr/availability/batch',
      {
        method: 'POST',
        body: JSON.stringify({ hardcover_ids: hardcoverIds, isbn_map: isbnMap }),
      }
    ),

  getAvailabilityByReadarrId: (readarrBookId: number, format: 'ebook' | 'audiobook') =>
    apiRequest<{ available: boolean; readarr_book_id: number; format: string }>(
      `/api/readarr/availability/readarr/${readarrBookId}?format=${format}`
    ),

  getManageLink: (hardcoverId: number, format?: 'ebook' | 'audiobook') =>
    apiRequest<{ url: string | null; format: string | null; readarr_book_id: number | null }>(
      `/api/readarr/manage-link/${hardcoverId}${format ? `?format=${format}` : ''}`
    ),
};

// Jobs API endpoints
export interface Job {
  name: string;
  type: string;
  interval_seconds: number;
  last_execution: string | null;
  next_execution: string | null;
  is_enabled?: boolean;
}

export interface IntervalOption {
  value: number;
  label: string;
}

export interface JobRunStatus {
  run_id: string;
  job_name: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  error: string | null;
}

export const jobsApi = {
  getAll: () =>
    apiRequest<Array<Job>>('/api/jobs/', {
      method: 'GET',
    }),

  getIntervals: () =>
    apiRequest<Array<IntervalOption>>('/api/jobs/intervals', {
      method: 'GET',
    }),

  update: (jobName: string, intervalSeconds: number) =>
    apiRequest<Job>(`/api/jobs/${jobName}`, {
      method: 'PUT',
      body: JSON.stringify({ interval_seconds: intervalSeconds }),
    }),

  run: (jobName: string) =>
    apiRequest<{
      message: string;
      job_name: string;
      run_id: string;
      triggered_at: string;
    }>(`/api/jobs/${jobName}/run`, {
      method: 'POST',
    }),

  getStatus: (runId: string) =>
    apiRequest<JobRunStatus>(`/api/jobs/status/${runId}`, {
      method: 'GET',
    }),
};

// Booklore API endpoints
export interface BookloreServer {
  id: number;
  name: string;
  url: string;
  username: string;
  is_default: boolean;
  ebook_library_id: number | null;
  audiobook_library_id: number | null;
  created_at: string;
  updated_at?: string;
}

export interface BookloreTestResponse {
  success: boolean;
  error?: string;
  libraries?: Array<{ id: number; name: string }>;
}

export const bookloreApi = {
  getAll: () =>
    apiRequest<Array<BookloreServer>>('/api/booklore/'),

  getById: (id: number) =>
    apiRequest<BookloreServer>(`/api/booklore/${id}`),

  create: (server: { name: string; url: string; username: string; password: string; is_default?: boolean; ebook_library_id?: number | null; audiobook_library_id?: number | null }) =>
    apiRequest<BookloreServer>('/api/booklore/', {
      method: 'POST',
      body: JSON.stringify(server),
    }),

  update: (id: number, server: { name?: string; url?: string; username?: string; password?: string; is_default?: boolean; ebook_library_id?: number | null; audiobook_library_id?: number | null }) =>
    apiRequest<BookloreServer>(`/api/booklore/${id}`, {
      method: 'PUT',
      body: JSON.stringify(server),
    }),

  delete: (id: number) =>
    apiRequest<void>(`/api/booklore/${id}`, {
      method: 'DELETE',
    }),

  testConnection: (config: { url: string; username: string; password: string }) =>
    apiRequest<BookloreTestResponse>('/api/booklore/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  getBooks: (serverId: number) =>
    apiRequest<Array<any>>(`/api/booklore/${serverId}/books`),

  checkBook: (serverId: number, hardcoverId: number) =>
    apiRequest<{ available: boolean; book?: any }>(`/api/booklore/${serverId}/check/${hardcoverId}`),
};

// Audiobookshelf API endpoints
export interface AudiobookshelfServer {
  id: number;
  name: string;
  url: string;
  is_default: boolean;
  library_id: string | null;
  created_at: string;
  updated_at?: string;
}

export interface AudiobookshelfTestResponse {
  success: boolean;
  error?: string;
  libraries?: Array<{ id: string; name: string; mediaType: string }>;
}

export const audiobookshelfApi = {
  getAll: () =>
    apiRequest<Array<AudiobookshelfServer>>('/api/audiobookshelf/'),

  getById: (id: number) =>
    apiRequest<AudiobookshelfServer>(`/api/audiobookshelf/${id}`),

  create: (server: { name: string; url: string; api_key: string; is_default?: boolean; library_id?: string | null }) =>
    apiRequest<AudiobookshelfServer>('/api/audiobookshelf/', {
      method: 'POST',
      body: JSON.stringify(server),
    }),

  update: (id: number, server: { name?: string; url?: string; api_key?: string; is_default?: boolean; library_id?: string | null }) =>
    apiRequest<AudiobookshelfServer>(`/api/audiobookshelf/${id}`, {
      method: 'PUT',
      body: JSON.stringify(server),
    }),

  delete: (id: number) =>
    apiRequest<void>(`/api/audiobookshelf/${id}`, {
      method: 'DELETE',
    }),

  testConnection: (config: { url: string; api_key: string }) =>
    apiRequest<AudiobookshelfTestResponse>('/api/audiobookshelf/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  getItems: (serverId: number) =>
    apiRequest<Array<any>>(`/api/audiobookshelf/${serverId}/items`),
};

// Download Settings API endpoints
export interface ProwlarrServer {
  id: number;
  name: string;
  host: string;
  port: number;
  use_ssl: boolean;
  api_key: string;
  url_base: string | null;
  enabled: boolean;
  is_default: boolean;
  indexer_ids: number[] | null;
}

export interface ProwlarrIndexer {
  id: number;
  name: string;
  protocol: string;
  privacy: string;
  enabled: boolean;
}

export interface DownloadClient {
  id: number;
  name: string;
  type: string;
  protocol: string;
  host: string;
  port: number;
  use_ssl: boolean;
  username: string | null;
  password: string;
  api_key: string | null;
  url_base: string | null;
  enabled: boolean;
  priority: number;
  category: string | null;
  ebook_category: string | null;
  audiobook_category: string | null;
  path_mappings_json: string | null;
}

export interface ProwlarrTestResponse {
  success: boolean;
  error?: string;
  indexers?: Array<any>;
  total_indexers?: number;
}

export interface DownloadClientTestResponse {
  success: boolean;
  error?: string;
  version?: string;
  api_version?: string;
}

export const downloadSettingsApi = {
  // Prowlarr endpoints
  getProwlarrServers: () =>
    apiRequest<Array<ProwlarrServer>>('/api/download-settings/prowlarr'),

  createProwlarrServer: (server: { name: string; host: string; port?: number; use_ssl?: boolean; api_key: string; url_base?: string; enabled?: boolean; is_default?: boolean; indexer_ids?: number[] }) =>
    apiRequest<ProwlarrServer>('/api/download-settings/prowlarr', {
      method: 'POST',
      body: JSON.stringify(server),
    }),

  updateProwlarrServer: (id: number, server: { name?: string; host?: string; port?: number; use_ssl?: boolean; api_key?: string; url_base?: string; enabled?: boolean; is_default?: boolean; indexer_ids?: number[] }) =>
    apiRequest<ProwlarrServer>(`/api/download-settings/prowlarr/${id}`, {
      method: 'PUT',
      body: JSON.stringify(server),
    }),

  deleteProwlarrServer: (id: number) =>
    apiRequest<{ message: string }>(`/api/download-settings/prowlarr/${id}`, {
      method: 'DELETE',
    }),

  testProwlarrConnection: (config: { host: string; port: number; use_ssl: boolean; api_key: string; url_base?: string }) =>
    apiRequest<ProwlarrTestResponse>('/api/download-settings/prowlarr/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  getProwlarrIndexers: (serverId: number) =>
    apiRequest<{ indexers: ProwlarrIndexer[] }>(`/api/download-settings/prowlarr/${serverId}/indexers`),

  // Download Client endpoints
  getDownloadClients: () =>
    apiRequest<Array<DownloadClient>>('/api/download-settings/download-clients'),

  createDownloadClient: (client: { name: string; type: string; protocol: string; host: string; port: number; use_ssl?: boolean; username?: string; password?: string; api_key?: string; url_base?: string; enabled?: boolean; priority?: number; category?: string; ebook_category?: string; audiobook_category?: string; path_mappings_json?: string }) =>
    apiRequest<DownloadClient>('/api/download-settings/download-clients', {
      method: 'POST',
      body: JSON.stringify(client),
    }),

  updateDownloadClient: (id: number, client: { name?: string; type?: string; protocol?: string; host?: string; port?: number; use_ssl?: boolean; username?: string; password?: string; api_key?: string; url_base?: string; enabled?: boolean; priority?: number; category?: string; ebook_category?: string; audiobook_category?: string; path_mappings_json?: string }) =>
    apiRequest<DownloadClient>(`/api/download-settings/download-clients/${id}`, {
      method: 'PUT',
      body: JSON.stringify(client),
    }),

  deleteDownloadClient: (id: number) =>
    apiRequest<{ message: string }>(`/api/download-settings/download-clients/${id}`, {
      method: 'DELETE',
    }),

  testDownloadClient: (config: { type: string; protocol: string; host: string; port: number; use_ssl: boolean; username?: string; password?: string; api_key?: string; url_base?: string }) =>
    apiRequest<DownloadClientTestResponse>('/api/download-settings/download-clients/test', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
};

// Downloads API endpoints
export interface ReleaseInfo {
  title: string;
  download_url: string;
  protocol: string;
  indexer: string;
  size_bytes: number;
  seeders: number | null;
  format: string | null;
  language: string | null;
  quality_score: number;
  published_date: string | null;
  already_downloaded: boolean;
  info_url: string | null;
}

export interface SearchResponse {
  book_id: number;
  releases: ReleaseInfo[];
  total: number;
}

export interface DownloadResponse {
  task_id: number;
  status: string;
  message: string;
}

export interface DownloadTask {
  id: number;
  book_id: number;
  format: string;
  source: string;
  release_title: string;
  download_url: string;
  protocol: string;
  state: string;
  progress: number;
  download_path: string | null;
  import_status?: string;
  import_message?: string;
  imported_at?: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  message?: string;
}

export interface DownloadAttempt {
  source_name: string;
  source_type: string;
  url: string;
  started_at: string;
  ended_at: string | null;
  success: boolean;
  error: string | null;
  bytes_downloaded: number;
}

export interface DownloadLog {
  task_id: number;
  started_at: string | null;
  completed_at: string | null;
  final_result: string | null;
  attempts: DownloadAttempt[];
  message?: string;
}

export const downloadsApi = {
  // Search for releases
  // source: 'prowlarr' | 'direct' | undefined (undefined = all sources)
  searchReleases: (bookId: number, formatType: 'ebook' | 'audiobook', source?: 'prowlarr' | 'direct') => {
    let url = `/api/downloads/search/${bookId}?format_type=${formatType}`;
    if (source) {
      url += `&source_filter=${source}`;
    }
    return apiRequest<SearchResponse>(url, { method: 'POST' });
  },

  // Manually download a specific release
  downloadRelease: (request: {
    book_id: number;
    format_type: string;
    download_url: string;
    protocol: string;
    release_title: string;
    indexer: string;
    size_bytes: number;
  }) =>
    apiRequest<DownloadResponse>('/api/downloads/download', {
      method: 'POST',
      body: JSON.stringify(request),
    }),

  // Retry the server-stored release without reconstructing or deleting it in the browser.
  retryTask: (taskId: number) =>
    apiRequest<DownloadResponse>(`/api/downloads/tasks/${taskId}/retry`, { method: 'POST' }),

  // Automatically download the best release
  autoDownload: (bookId: number, formatType: 'ebook' | 'audiobook') =>
    apiRequest<DownloadResponse>(`/api/downloads/auto-download/${bookId}?format_type=${formatType}`, {
      method: 'POST',
    }),

  // Get download tasks
  getTasks: (skip?: number, limit?: number, state?: string) => {
    const params = new URLSearchParams();
    if (skip !== undefined) params.set('skip', String(skip));
    if (limit !== undefined) params.set('limit', String(limit));
    if (state) params.set('state', state);
    const query = params.toString();
    return apiRequest<DownloadTask[]>(`/api/downloads/tasks${query ? `?${query}` : ''}`);
  },

  // Get download log for a specific task (direct downloads only)
  getTaskLog: (taskId: number) =>
    apiRequest<DownloadLog>(`/api/downloads/tasks/${taskId}/log`),

  // Manually import a download to the configured destination
  importDownload: (taskId: number) =>
    apiRequest<{ success: boolean; message: string; destination_path: string }>(
      `/api/downloads/import/${taskId}`,
      { method: 'POST' }
    ),

  // Delete a single download task
  deleteTask: (taskId: number) =>
    apiRequest<{ success: boolean; message: string }>(
      `/api/downloads/task/${taskId}`,
      { method: 'DELETE' }
    ),

  // Clear all eligible download tasks
  clearTasks: () =>
    apiRequest<{ success: boolean; message: string; deleted_count: number }>(
      '/api/downloads/tasks/clear',
      { method: 'DELETE' }
    ),
};

// Direct Download Settings types
export interface DirectDownloadSettings {
  id: number;
  enabled: boolean;
  annas_archive_enabled: boolean;
  annas_archive_mirror: string | null;
  zlibrary_enabled: boolean;
  zlibrary_email: string | null;
  zlibrary_password_set: boolean;
  zlibrary_domain: string | null;
  requests_per_minute: number;
  flaresolverr_url: string | null;
}

export interface DirectDownloadTestResponse {
  success: boolean;
  providers_count: number;
  providers_status: Record<string, boolean>;
  message?: string;
}

// Direct Download API
export const directDownloadApi = {
  getSettings: () =>
    apiRequest<DirectDownloadSettings>('/api/direct-downloads/settings'),

  updateSettings: (data: {
    enabled: boolean;
    annas_archive_enabled: boolean;
    annas_archive_mirror?: string;
    zlibrary_enabled: boolean;
    zlibrary_email?: string;
    zlibrary_password?: string;
    zlibrary_domain?: string;
    requests_per_minute: number;
    flaresolverr_url?: string | null;
  }) =>
    apiRequest<DirectDownloadSettings>('/api/direct-downloads/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  testConnection: () =>
    apiRequest<DirectDownloadTestResponse>('/api/direct-downloads/test', {
      method: 'POST',
    }),

  testFlaresolverr: (url: string) =>
    apiRequest<{ success: boolean; message: string }>('/api/direct-downloads/test-flaresolverr', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  resetSettings: () =>
    apiRequest<{ success: boolean; message: string }>('/api/direct-downloads/settings', {
      method: 'DELETE',
    }),
};

// Hardcover Sync types
export interface HardcoverSyncConfig {
  is_enabled: boolean;
  sync_to_read: boolean;
  sync_list_ids: number[];
  default_format: string;
  last_synced_at: string | null;
  has_token: boolean;           // true if any token available (personal or global)
  has_personal_token: boolean;  // true only if user set their own token
  using_app_token: boolean;     // true if falling back to global app token
}

export interface HardcoverList {
  id: number;
  name: string;
}

// Hardcover Sync API
export const hardcoverSyncApi = {
  getConfig: () =>
    apiRequest<HardcoverSyncConfig>('/api/hardcover-sync/config'),

  updateConfig: (data: {
    hardcover_api_token?: string;
    clear_token?: boolean;
    is_enabled?: boolean;
    sync_to_read?: boolean;
    sync_list_ids?: number[];
    default_format?: string;
  }) =>
    apiRequest<HardcoverSyncConfig>('/api/hardcover-sync/config', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  getLists: () =>
    apiRequest<HardcoverList[]>('/api/hardcover-sync/lists'),

  runSync: () =>
    apiRequest<{ message: string }>('/api/hardcover-sync/run', {
      method: 'POST',
    }),
};
