// Render useful API messages without serializing submitted values or error objects.
function messageFrom(value: unknown, depth = 0): string | undefined {
  if (depth > 4) return undefined;
  if (typeof value === 'string') return value.trim() || undefined;
  if (Array.isArray(value)) {
    const messages = value.map(item => messageFrom(item, depth + 1)).filter(Boolean);
    return messages.length ? messages.join('; ') : undefined;
  }
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>;
    const message = messageFrom(item.msg ?? item.message ?? item.detail ?? item.error, depth + 1);
    if (!message) return undefined;
    const location = Array.isArray(item.loc)
      ? item.loc.filter(part => (typeof part === 'string' || typeof part === 'number') && part !== 'body').join('.')
      : '';
    return location ? `${location}: ${message}` : message;
  }
  return undefined;
}

export function apiErrorMessage(payload: unknown, status: number): string {
  return messageFrom(payload) ?? `API request failed: ${status}`;
}
