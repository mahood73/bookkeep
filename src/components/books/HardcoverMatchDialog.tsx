import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { bookMatchesApi, type MatchPreview } from '@/lib/api';
import { toast } from 'sonner';

interface Props {
  bookId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId?: number | null;
  onApplied: (hardcoverId: number) => void;
}

export function HardcoverMatchDialog({ bookId, open, onOpenChange, candidateId, onApplied }: Props) {
  const [selection, setSelection] = useState('');
  const [preview, setPreview] = useState<MatchPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    setSelection(candidateId ? String(candidateId) : '');
    setPreview(null);
    setError('');
  }, [open, bookId, candidateId]);

  async function inspect() {
    setBusy(true);
    setError('');
    setPreview(null);
    try {
      setPreview(await bookMatchesApi.preview(bookId, Number(selection)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not preview match');
    } finally { setBusy(false); }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setError('');
    try {
      const result = await bookMatchesApi.apply(bookId, preview.review_token);
      toast.success('Hardcover match corrected');
      onOpenChange(false);
      onApplied(result.hardcover_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply match');
      setPreview(null);
    } finally { setBusy(false); }
  }

  return <Dialog open={open} onOpenChange={busy ? undefined : onOpenChange}>
    <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>Correct Hardcover match</DialogTitle>
        <DialogDescription>Choose a Hardcover work, review its details, then confirm. Existing requests, downloads and library links are kept.</DialogDescription>
      </DialogHeader>
      <div className="space-y-4">
        <Label htmlFor="hardcover-match-id">Hardcover book ID</Label>
        <div className="flex gap-2">
          <Input id="hardcover-match-id" type="number" min="1" step="1" value={selection} disabled={busy}
            onChange={event => { setSelection(event.target.value); setPreview(null); setError(''); }} />
          <Button onClick={inspect} disabled={busy || !/^\d+$/.test(selection) || Number(selection) < 1}>{busy ? 'Working...' : 'Review match'}</Button>
        </div>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        {preview && <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div><p className="font-semibold">Current match</p><p>{preview.current.title}</p><p>{preview.current.author}</p><p>ID: {preview.current.hardcover_id ?? 'Local only'}</p></div>
            <div><p className="font-semibold">Proposed match</p><p>{preview.proposed.title}</p><p>{preview.proposed.author}</p><p>ID: {preview.proposed.hardcover_id}</p>
              {preview.proposed.hardcover_slug && <a className="underline" target="_blank" rel="noopener noreferrer" href={`https://hardcover.app/books/${preview.proposed.hardcover_slug}`}>Open on Hardcover</a>}
            </div>
          </div>
          {preview.selected_id !== preview.proposed.hardcover_id && <p className="text-sm">The selected ID redirects to canonical work {preview.proposed.hardcover_id}.</p>}
          <p className="text-sm">Collection label: {preview.compilation ? 'Collection' : 'Not labelled as a collection'}. Review the title and author carefully; these labels may be incomplete.</p>
          <p className="text-sm text-muted-foreground">File ISBN {preview.current.file_isbn ?? 'not set'} will be kept. Default editions will come from the corrected work. {preview.retained_request_editions.length ? `Existing request edition selections (${preview.retained_request_editions.join(', ')}) will be retained; review them separately before further requests.` : 'No existing requests have selected editions.'}</p>
          <p className="text-sm">This reviewed match will be protected from later library sync.</p>
          <Button onClick={confirm} disabled={busy}>Confirm corrected match</Button>
        </div>}
      </div>
    </DialogContent>
  </Dialog>;
}
