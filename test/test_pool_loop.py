"""Exercise real lifecycle entrypoints with a deterministic terminal transport."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(ROOT / 'bin' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


WARP = load('tincan-warp')
PANE = load('tincan-pane')


class PoolLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve() / 'repo with spaces'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.token = 'a' * 32
        self.state_path = WARP.create_session(self.repo, self.token, 5, 'visible-review-loop', poolside=True)
        self.log = self.repo / '.git' / 'deliveries.jsonl'
        self.fake = self.repo / '.git' / 'fake-pane'
        self.fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['TEST_LOG']).open('a') as stream:
    stream.write(json.dumps({'agent': args[args.index('--agent') + 1], 'prompt': sys.stdin.read()}) + '\\n')
sys.exit(int(os.environ.get('TEST_FAIL', '0')))
''')
        self.fake.chmod(0o755)
        self.env = dict(os.environ, TINCAN_SESSION=self.token, TINCAN_PANE=str(self.fake), TEST_LOG=str(self.log), PYTHONDONTWRITEBYTECODE='1')
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def state(self):
        return json.loads(self.state_path.read_text())

    def update(self, **values):
        state = self.state()
        state.update(values)
        self.state_path.write_text(json.dumps(state))

    def deliveries(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def hook(self, agent, message='', kind='Stop', **fields):
        self.counter += 1
        event = dict(cwd=str(self.repo), session_id=agent + '-session',
                     hook_event_name=kind, last_assistant_message=message)
        if agent == 'poolside':
            event['event_id'] = f'event-{self.counter}'
        event.update(fields)
        script = {'poolside': 'tincan-pool-hook', 'codex': 'tincan-review-hook', 'claude': 'tincan-pool-claude-hook'}[agent]
        result = subprocess.run([str(ROOT / 'bin' / script)], input=json.dumps(event),
                                cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout or '{}')

    def start(self):
        self.hook('poolside', kind='SessionStart')
        self.hook('poolside', kind='UserPromptSubmit', prompt='Implement the requested feature')
        (self.repo / 'feature.txt').write_text('first implementation')
        self.hook('poolside', 'Implemented feature; verified it.')
        self.assertEqual(self.state()['status'], 'awaiting-codex')

    def review(self, codex='APPROVED', claude='APPROVED'):
        self.hook('codex', f'Codex findings\nTINCAN_VERDICT: {codex}')
        self.hook('claude', f'Claude findings\nTINCAN_VERDICT: {claude}')

    def test_full_loop_requires_both_approvals_and_rearms(self):
        self.start()
        self.review(codex='CHANGES_REQUESTED')
        self.assertEqual(self.state()['status'], 'awaiting-poolside')
        self.assertNotIn('approved_content_fingerprint', self.state())
        self.assertIn('Codex findings', self.deliveries()[-1]['prompt'])
        self.assertIn('Claude findings', self.deliveries()[-1]['prompt'])
        (self.repo / 'feature.txt').write_text('fixed')
        self.hook('poolside', 'Fixed blocker and verified')
        self.assertEqual(self.state()['round'], 2)
        self.assertEqual(self.state()['reviews'], {})
        self.review()
        self.assertEqual(self.state()['status'], 'awaiting-poolside-summary')
        self.hook('poolside', 'Completed and approved')
        self.assertEqual(self.state()['status'], 'awaiting-user')
        self.assertEqual(self.state()['round'], 0)
        self.assertEqual([d['agent'] for d in self.deliveries()], ['codex', 'claude', 'poolside'] * 2)
        self.hook('poolside', kind='UserPromptSubmit', prompt='Second feature')
        (self.repo / 'feature.txt').write_text('new task')
        self.hook('poolside', 'Second feature implemented')
        self.assertEqual(self.state()['round'], 1)
        self.assertIn('Second feature', self.deliveries()[-1]['prompt'])

    def test_existing_changes_can_be_submitted_without_more_edits(self):
        (self.repo / 'feature.txt').write_text('existing implementation')
        self.hook('poolside', kind='UserPromptSubmit', prompt='Verify the existing change')
        self.hook('poolside', 'Verified the existing implementation')
        self.assertEqual(self.state()['status'], 'awaiting-codex')

    def test_claude_blocker_returns_to_poolside(self):
        self.start()
        self.review(claude='CHANGES_REQUESTED')
        self.assertEqual(self.state()['status'], 'awaiting-poolside')

    def test_rebuttal_without_edits_is_reviewed_again(self):
        self.start()
        self.review(codex='CHANGES_REQUESTED')
        self.hook('poolside', 'Rebuttal: requirement explicitly permits this.')
        self.assertEqual(self.state()['round'], 2)
        self.assertIn('Rebuttal: requirement', self.deliveries()[-1]['prompt'])

    def test_followup_changes_reviewed_once_then_admin_turn_skipped(self):
        self.start()
        self.review()
        (self.repo / 'feature.txt').write_text('optional improvement')
        self.hook('poolside', 'Adopted one useful suggestion')
        self.assertEqual(self.state()['review_kind'], 'followup')
        self.review()
        self.assertIn('Do not continue optional polishing', self.deliveries()[-1]['prompt'])
        self.hook('poolside', 'Final summary')
        count = len(self.deliveries())
        subprocess.run(['git', 'add', 'feature.txt'], cwd=self.repo, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'done'], cwd=self.repo, check=True)
        self.hook('poolside', 'Committed')
        self.assertEqual(len(self.deliveries()), count)

    def test_missing_or_conflicting_verdicts_fail_closed(self):
        for message in ('Looks good', 'TINCAN_VERDICT: APPROVED\nTINCAN_VERDICT: CHANGES_REQUESTED'):
            with self.subTest(message=message):
                self.update(enabled=True, status='awaiting-user', round=0)
                self.hook('poolside', 'Ready')
                self.hook('codex', message)
                self.assertEqual(self.state()['status'], 'needs-human')
                self.assertFalse(self.state()['enabled'])

    def test_claude_api_failure_reports_to_poolside_and_stops(self):
        self.start()
        self.hook('codex', 'TINCAN_VERDICT: APPROVED')
        self.hook('claude', 'Your organization has disabled Claude subscription access',
                  kind='StopFailure', error='oauth_org_not_allowed')
        self.assertEqual(self.state()['status'], 'needs-human')
        self.assertFalse(self.state()['enabled'])
        self.assertEqual(self.state()['claude_error'], 'oauth_org_not_allowed')
        self.assertNotIn('approved_content_fingerprint', self.state())
        self.assertEqual(self.deliveries()[-1]['agent'], 'poolside')
        self.assertIn('not a code finding', self.deliveries()[-1]['prompt'])
        count = len(self.deliveries())
        self.hook('claude', 'error again', kind='StopFailure', error='oauth_org_not_allowed')
        self.assertEqual(len(self.deliveries()), count)

    def test_claude_failure_outside_its_review_is_ignored(self):
        self.start()
        self.hook('claude', 'API error', kind='StopFailure', error='rate_limit')
        self.assertEqual(self.state()['status'], 'awaiting-codex')
        self.assertEqual(len(self.deliveries()), 1)

    def test_round_limit_stops_without_approval(self):
        self.update(max_rounds=1)
        self.start()
        self.review(claude='CHANGES_REQUESTED')
        self.assertEqual(self.state()['status'], 'needs-human')
        count = len(self.deliveries())
        self.hook('poolside', 'Stopped')
        self.assertEqual(len(self.deliveries()), count)

    def test_unexpected_and_duplicate_hooks_do_not_advance(self):
        self.hook('codex', 'TINCAN_VERDICT: APPROVED')
        self.assertFalse(self.deliveries())
        self.start()
        self.hook('poolside', 'duplicate Stop')
        self.assertEqual(len(self.deliveries()), 1)
        self.hook('claude', 'TINCAN_VERDICT: APPROVED')
        self.assertEqual(len(self.deliveries()), 1)
        self.hook('codex', 'TINCAN_VERDICT: APPROVED')
        self.hook('codex', 'TINCAN_VERDICT: APPROVED')
        self.assertEqual(len(self.deliveries()), 2)

    def test_other_sessions_ignored(self):
        self.start()
        self.env['TINCAN_SESSION'] = 'b' * 32
        self.hook('codex', 'TINCAN_VERDICT: APPROVED')
        self.assertEqual(len(self.deliveries()), 1)
        self.env['TINCAN_SESSION'] = self.token
        self.hook('poolside', 'unrelated session', session_id='other-pool')
        self.assertEqual(len(self.deliveries()), 1)

    def test_delivery_failure_disables_loop(self):
        self.env['TEST_FAIL'] = '1'
        result = self.hook('poolside', 'Ready')
        self.assertTrue(result['continue'])
        self.assertEqual(self.state()['status'], 'handoff-failed')
        self.assertFalse(self.state()['enabled'])

    def test_content_changed_during_review_cannot_be_approved(self):
        self.start()
        self.hook('codex', 'TINCAN_VERDICT: APPROVED')
        (self.repo / 'feature.txt').write_text('changed behind reviewer')
        self.hook('claude', 'TINCAN_VERDICT: APPROVED')
        self.assertEqual(self.state()['status'], 'needs-human')
        self.assertNotIn('approved_content_fingerprint', self.state())

    def test_single_reviewer_modes_use_only_enabled_reviewer(self):
        for reviewer in ('codex', 'claude'):
            with self.subTest(reviewer=reviewer):
                self.update(enabled=True, status='awaiting-user', round=0,
                            no_codex=reviewer != 'codex', no_claude=reviewer != 'claude')
                self.hook('poolside', 'Ready')
                self.assertEqual(self.deliveries()[-1]['agent'], reviewer)
                self.hook(reviewer, 'TINCAN_VERDICT: APPROVED')
                self.assertEqual(self.deliveries()[-1]['agent'], 'poolside')
                self.assertEqual(self.state()['status'], 'awaiting-poolside-summary')
                # Start a genuinely different checkout for the next subcase.
                (self.repo / 'feature.txt').write_text(reviewer)

    def test_user_prompt_blocked_while_reviewers_work(self):
        self.start()
        result = self.hook('poolside', kind='UserPromptSubmit', prompt='Another task')
        self.assertEqual(result['decision'], 'block')
        self.assertEqual(self.state()['task'], 'Implement the requested feature')

    def test_pool_trajectory_supplies_final_report(self):
        trajectory = self.repo / '.git' / 'trajectory.ndjson'
        trajectory.write_text('\n'.join(json.dumps(entry) for entry in [
            {'type': 'assistant_message.end', 'assistant_message_end': {'assistant_message': 'old report'}},
            {'type': 'session.input'},
            {'type': 'assistant_message.end', 'assistant_message_end': {'assistant_message': 'Verified the fix with tests.'}},
        ]))
        self.hook('poolside', trajectory_path=str(trajectory))
        self.assertIn('Verified the fix with tests.', self.deliveries()[-1]['prompt'])
        self.assertNotIn('old report', self.deliveries()[-1]['prompt'])

    def test_launch_wires_native_hooks_and_read_only_codex(self):
        state = self.state()
        claude_settings = json.loads(Path(state['claude_settings']).read_text())
        self.assertIn('StopFailure', claude_settings['hooks'])
        settings = json.loads(Path(state['poolside_settings']).read_text())
        self.assertEqual(settings['hooks']['stop_hook_max_continuations'], 1)
        for name in ('SessionStart', 'UserPromptSubmit', 'Stop'):
            hooks = settings['hooks'][name]
            self.assertIn('tincan-pool-hook', hooks[0]['command'])
            self.assertEqual(hooks[0]['matcher'], '*')
        with mock.patch.object(PANE, 'run_agent', return_value=0) as run:
            PANE.run_poolside(self.repo, self.token)
            argv = run.call_args.args[3]
            self.assertEqual(argv[-3:], ['--', '--settings', state['poolside_settings']])
            PANE.run_codex(self.repo, self.token)
            self.assertIn('read-only', run.call_args.args[3])
            self.assertIn('Poolside implements', run.call_args.args[3][-1])
            PANE.run_claude(self.repo, self.token)
            self.assertIn('--settings', run.call_args.args[3])
            self.assertNotIn('-p', run.call_args.args[3])


class PoolLauncherValidationTests(unittest.TestCase):
    def test_rejects_incompatible_modes(self):
        for flags in (["--no-codex"], ["--no-claude"], ["--poolside", "--brainstorm"]):
            with self.subTest(flags=flags):
                result = subprocess.run([str(ROOT / 'bin/tincan-warp'), "--repo", str(ROOT), "--dry-run", *flags],
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)

    def test_disabled_reviewer_not_required_and_pool_override_used(self):
        import argparse
        args = argparse.Namespace(repo=str(ROOT), poolside=True, brainstorm=False,
                                  no_codex=True, no_claude=False, dry_run=False,
                                  max_rounds=5, tab=False)
        looked_up = []
        def which(name):
            looked_up.append(name)
            return '/fake/' + name
        with (mock.patch.object(WARP, 'parse_args', return_value=args),
              mock.patch.object(WARP, 'repo_root', return_value=ROOT),
              mock.patch.dict(os.environ, {'TINCAN_POOL': 'custom-pool'}),
              mock.patch.object(WARP.shutil, 'which', side_effect=which),
              mock.patch.object(WARP.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '1.0.16', '')) as run,
              mock.patch.object(WARP, 'ensure_hook') as install,
              mock.patch.object(WARP, 'create_session'),
              mock.patch.object(WARP, 'write_config')):
            self.assertEqual(WARP.main(), 0)
            self.assertEqual(looked_up, ['claude', 'custom-pool'])
            install.assert_not_called()
            self.assertEqual(run.call_args_list[0].args[0], ['custom-pool', '--version'])

    def test_old_pool_version_fails_before_launch(self):
        import argparse
        args = argparse.Namespace(repo=str(ROOT), poolside=True, brainstorm=False,
                                  no_codex=False, no_claude=False, dry_run=False)
        with (mock.patch.object(WARP, 'parse_args', return_value=args),
              mock.patch.object(WARP, 'repo_root', return_value=ROOT),
              mock.patch.object(WARP.shutil, 'which', return_value='/fake/bin'),
              mock.patch.object(WARP.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '1.0.15', '')),
              mock.patch.object(WARP, 'create_session') as create):
            with self.assertRaises(SystemExit):
                WARP.main()
            create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
