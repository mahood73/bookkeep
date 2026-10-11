import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { bookMatchesApi, type PendingMatch } from '@/lib/api';
import { HardcoverMatchDialog } from '@/components/books/HardcoverMatchDialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function HardcoverMatchReviews() {
  const [selected, setSelected] = useState<PendingMatch | null>(null);
  const queryClient = useQueryClient();
  const { data = [], isLoading, error } = useQuery({ queryKey: ['hardcover-match-reviews'], queryFn: bookMatchesApi.pending });
  return <Card>
    <CardHeader><CardTitle>Hardcover matches to review</CardTitle><CardDescription>Library candidates that could not safely replace an existing identity. You can also correct a match from a book's details page.</CardDescription></CardHeader>
    <CardContent className="space-y-4">
      {isLoading && <p>Loading matches...</p>}
      {error && <p role="alert">Could not load matches: {error.message}</p>}
      {!isLoading && !error && data.length === 0 && <p className="text-sm text-muted-foreground">No matches need review.</p>}
      {data.map(row => <div key={row.id} className="flex items-center justify-between gap-4 border-b pb-3">
        <div><p className="font-medium">{row.title}</p><p className="text-sm">{row.author}</p><p className="text-sm text-muted-foreground">{row.reason}</p></div>
        <Button variant="outline" onClick={() => setSelected(row)}>Review</Button>
      </div>)}
      {selected && <HardcoverMatchDialog bookId={selected.id} candidateId={selected.candidate_id} open onOpenChange={open => { if (!open) setSelected(null); }} onApplied={() => {
        queryClient.invalidateQueries({ queryKey: ['hardcover-match-reviews'] });
        queryClient.invalidateQueries({ queryKey: ['book'] });
        queryClient.invalidateQueries({ queryKey: ['requests'] });
        setSelected(null);
      }} />}
    </CardContent>
  </Card>;
}
