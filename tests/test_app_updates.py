from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from keyscope.jobs import Job, JobManager
from keyscope.score import parse_score, plan_score
from keyscope.converter import convert_score


class ApplicationUpdateTests(unittest.TestCase):
    def test_history_video_name_and_older_entries(self):
        with tempfile.TemporaryDirectory() as temp, patch('keyscope.jobs.ROOT', Path(temp)):
            manager=JobManager()
            summary={'id':'test','kind':'inference','status':'completed','stage':'Completed',
                     'created_at':'2026-01-01T12:00:00','progress':1,'metrics':{},'elapsed':2}
            manager.index=[{'id':'test'}]
            for config, expected in (({'video_path':str(Path(temp)/'song & chords.mp4')}, 'song & chords.mp4'), ({}, '')):
                with patch.object(manager, 'get', return_value={**summary,'config':config}):
                    result=manager.list()[0]
                    self.assertEqual(result['video'], expected)
                    self.assertNotIn('config', result)
            with patch.object(manager, 'get', return_value=summary):
                self.assertEqual(manager.list()[0]['video'], '')

    def test_default_merge_gap_is_eighty_ms(self):
        self.assertEqual(plan_score(parse_score('0 Q\n.03 Q\n.06 Q'))[1], 1)
        self.assertEqual(plan_score(parse_score('0 Q\n.08 Q\n.161 Q'))[1], 2)
        self.assertEqual(plan_score(parse_score('0 Q\n.03 Q\n.06 Q'),merge_ms=10)[1], 3)

    def test_format_dispatch_retains_existing_notation(self):
        score='0 G\n.5 D,Z\n2 A'
        default=convert_score(score)
        selected=convert_score(score, format='fingertip')
        self.assertEqual(default, selected)
        self.assertEqual(selected['format'], 'fingertip')
        self.assertIn('(DZ)', selected['text'])
        self.assertIn('/', selected['text'])
        for unknown in ('other', '', None, []):
            with self.assertRaises(ValueError):convert_score(score, format=unknown)

    def test_elapsed_advances_without_progress_and_freezes_at_completion(self):
        with tempfile.TemporaryDirectory() as temp, patch('keyscope.jobs.time.perf_counter') as clock:
            clock.return_value=100
            job=Job('inference', {'output_dir':temp})
            clock.return_value=102
            self.assertEqual(job.snapshot()['elapsed'], 2)
            job.update(stage='Running inference', progress=.5)
            clock.return_value=110
            self.assertEqual(job.snapshot()['elapsed'], 10)
            job.update(stage='Saving outputs', progress=1)
            clock.return_value=112
            self.assertEqual(job.snapshot()['elapsed'], 12)
            job.update(status='completed')
            clock.return_value=150
            job.update(artifacts=[])
            self.assertEqual(job.snapshot()['elapsed'], 12)
            job.set_preview(b'first');version=job.snapshot()['preview_version']
            self.assertEqual(job.snapshot()['preview_version'], version)
            job.set_preview(b'next')
            self.assertEqual(job.snapshot()['preview_version'], version+1)


if __name__ == '__main__':unittest.main()
