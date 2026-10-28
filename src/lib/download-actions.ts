export function canRetryImport(task: { state: string; import_status?: string; download_path: string | null }): boolean {
  return task.import_status !== 'imported' && (
    task.state === 'complete' || task.state === 'seeding' ||
    (task.state === 'error' && task.import_status === 'failed' && !!task.download_path)
  );
}
