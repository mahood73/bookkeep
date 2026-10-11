import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import fork_release


class ReleaseTests(unittest.TestCase):
    def test_numbering_ignores_upstream_and_other_versions(self):
        self.assertEqual(fork_release.next_tag(['v1.6.2', 'v1.6.2-hoodhaus.4',
            'v1.6.2-hoodhaus.12', 'v1.7.0-hoodhaus.99'], '1.6.2'), 'v1.6.2-hoodhaus.13')

    def test_refuses_another_repository_or_branch_before_api_access(self):
        for repo, ref in [('upstream/bookkeep', 'refs/heads/develop'),
                          ('mahood73/bookkeep', 'refs/heads/main')]:
            with patch.dict(os.environ, {'GITHUB_REPOSITORY': repo, 'GITHUB_REF': ref}), patch.object(fork_release, 'api') as api:
                with self.assertRaises(SystemExit):
                    fork_release.main()
                api.assert_not_called()

    def test_reservation_records_tag_only_after_creation_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            env = {'GITHUB_REPOSITORY': 'mahood73/bookkeep', 'GITHUB_REF': 'refs/heads/develop',
                   'GITHUB_SHA': 'a'*40, 'GITHUB_OUTPUT': str(output), 'RELEASE_ACTION': 'reserve'}
            with patch.dict(os.environ, env), patch.object(fork_release, 'api', side_effect=[[{'name':'v1.6.2-hoodhaus.4'}], {}]) as api:
                fork_release.main()
                self.assertEqual(output.read_text(), 'tag=v1.6.2-hoodhaus.5\n')
                self.assertEqual(api.call_args.args, ('git/refs', {'ref':'refs/tags/v1.6.2-hoodhaus.5', 'sha':'a'*40}))
            output.unlink()
            with patch.dict(os.environ, env), patch.object(fork_release, 'api', side_effect=[[], RuntimeError('tag conflict')]):
                with self.assertRaises(RuntimeError):
                    fork_release.main()
                self.assertFalse(output.exists())

    def test_release_rejects_a_tag_for_another_commit(self):
        env = {'GITHUB_REPOSITORY': 'mahood73/bookkeep', 'GITHUB_REF': 'refs/heads/develop',
               'GITHUB_SHA': 'a'*40, 'RELEASE_ACTION': 'publish',
               'RELEASE_TAG': 'v1.6.2-hoodhaus.5', 'IMAGE_DIGEST': 'sha256:'+'b'*64}
        with patch.dict(os.environ, env), patch.object(fork_release, 'api', return_value={'object': {'sha':'c'*40}}) as api:
            with self.assertRaises(SystemExit):
                fork_release.main()
            self.assertEqual(api.call_count, 1)

    def test_release_records_digest_and_never_sets_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / 'summary'
            env = {'GITHUB_REPOSITORY': 'mahood73/bookkeep', 'GITHUB_REF': 'refs/heads/develop',
                   'GITHUB_SHA': 'a'*40, 'RELEASE_ACTION': 'publish',
                   'RELEASE_TAG': 'v1.6.2-hoodhaus.5', 'IMAGE_DIGEST': 'sha256:'+'b'*64,
                   'GITHUB_STEP_SUMMARY': str(summary)}
            with patch.dict(os.environ, env), patch.object(fork_release, 'api', side_effect=[{'object': {'sha':'a'*40}}, {}]) as api:
                fork_release.main()
                path, body = api.call_args.args
                self.assertEqual(path, 'releases')
                self.assertEqual(body['make_latest'], 'false')
                self.assertIn('ghcr.io/mahood73/bookkeep:v1.6.2-hoodhaus.5@sha256:'+'b'*64, body['body'])
                self.assertIn('sha256:'+'b'*64, summary.read_text())


if __name__ == '__main__':
    unittest.main()
