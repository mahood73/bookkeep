"""Exercise workflow job conditions for validation and release events."""
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / 'workflows/docker-build-publish.yml'


def selected(job, context):
    source = WORKFLOW.read_text()
    block = re.search(r'^  ' + job + r':\n(.*?)(?=^  \w+:|\Z)', source, re.M | re.S)[1]
    condition = re.search(r'^    if: >-\n((?:      .*\n)+)', block, re.M)[1]
    expression = ' '.join(condition.split())
    for name, value in context.items():
        expression = expression.replace(name, repr(value))
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', ' not ', expression)
    return bool(eval(expression.strip(), {'__builtins__': {}}, {}))


class WorkflowPaths(unittest.TestCase):
    def test_each_supported_event_selects_only_one_build_path(self):
        cases = [
            ('pull_request', 'refs/pull/5/merge', False, ['build']),
            ('push', 'refs/heads/develop', False, ['publish']),
            ('workflow_dispatch', 'refs/heads/develop', False, ['build']),
            ('workflow_dispatch', 'refs/heads/develop', True, ['publish']),
            ('workflow_dispatch', 'refs/heads/feature', False, ['build']),
            ('workflow_dispatch', 'refs/heads/feature', True, []),
            ('push', 'refs/heads/main', False, []),
            ('push', 'refs/tags/v1.6.2-hoodhaus.6', False, []),
        ]
        for event, ref, publish, expected in cases:
            for repository in ('mahood73/bookkeep', 'boludo00/bookkeep'):
                with self.subTest(event=event, ref=ref, publish=publish, repository=repository):
                    context = {'github.repository': repository, 'github.event_name': event,
                               'github.ref': ref, 'inputs.publish': publish}
                    jobs = [job for job in ('build', 'publish') if selected(job, context)]
                    self.assertEqual(jobs, expected if repository == 'mahood73/bookkeep' else [])


if __name__ == '__main__':
    unittest.main()
