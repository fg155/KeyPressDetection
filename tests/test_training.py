"""Regression checks for removing training while retaining existing files."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from keyscope import config, jobs, engine

class InferenceOnlyTests(unittest.TestCase):
    def test_training_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(jobs,'ROOT',Path(temp)):
            manager=jobs.JobManager()
            with self.assertRaisesRegex(ValueError,'Training has been removed'):
                manager.start('training',{'output_dir':temp})
            self.assertFalse(manager.index)
            self.assertEqual(list(Path(temp).iterdir()),[])

    def test_unknown_job_type_rejected(self):
        with self.assertRaisesRegex(ValueError,'Only inference'):
            config.validate_task('finetune',{})

    def test_training_configuration_and_runner_removed(self):
        self.assertNotIn('epochs',config.DEFAULTS)
        self.assertNotIn('train_batch_size',config.DEFAULTS)
        self.assertFalse(hasattr(engine,'run_training'))

    def test_old_training_files_retained_on_history_read(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(jobs,'ROOT',Path(temp)):
            root=Path(temp);folder=root/'old-job';folder.mkdir()
            checkpoint=folder/'checkpoint.pth';checkpoint.write_bytes(b'preserve me')
            metadata=folder/'job.json';original=json.dumps({'id':'old-job','kind':'training','status':'completed'})
            metadata.write_text(original,'utf-8')
            (root/'history.json').write_text(json.dumps([{'id':'old-job','path':'old-job/job.json'}]),'utf-8')
            manager=jobs.JobManager()
            self.assertEqual(manager.list(),[])
            self.assertEqual(manager.get('old-job')['kind'],'training')
            self.assertEqual(metadata.read_text('utf-8'),original)
            self.assertEqual(checkpoint.read_bytes(),b'preserve me')

if __name__=='__main__':unittest.main()
