from video_fixture import make_video
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import numpy as np
from keyscope import jobs, engine, hardware
from keyscope.config import DEFAULTS, ROOT
from keyscope.score_library import list_scores, list_score_folders, delete_scores


class OutputTests(unittest.TestCase):
    def make_folder(self, root, name, status='completed'):
        folder=root/name;folder.mkdir()
        (folder/'score_keys.txt').write_text('0 Q','utf-8')
        (folder/'score_detections.csv').write_text('frame,keys','utf-8')
        (folder/'job.json').write_text(json.dumps({'status':status}),'utf-8')
        (folder/'task.log').write_text('Finished.','utf-8')
        nested=folder/'nested';nested.mkdir();(nested/'preview.jpg').write_bytes(b'preview')
        return folder

    def test_folder_delete_removes_all_contents_and_rejects_stale_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a=self.make_folder(root,'one');b=self.make_folder(root,'two')
            files=list_score_folders(root)['files']
            (b/'score_detections.csv').write_text('Changed sibling CSV','utf-8')
            with self.assertRaises(ValueError):delete_scores(root,files)
            self.assertTrue(a.exists());self.assertTrue(b.exists())
            result=delete_scores(root,[f for f in files if f['path']==str(a)])
            self.assertEqual(result,{'deleted':[str(a)],'errors':[]})
            self.assertFalse(a.exists());self.assertTrue(b.exists())
            self.assertTrue((b/'score_keys.txt').exists())

    def test_deletion_rejects_escape_root_active_and_linked_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);a=self.make_folder(root,'selected');sub=root/'empty';sub.mkdir()
            record=list_score_folders(root)['files'][0]
            for directory,files,protected in [(sub,[record],[]),(root,[{**record,'path':str(root)}],[]),
                    (root,[record],[a]),(root,[record],[a/'nested']), (root,[record],[root])]:
                with self.assertRaises(ValueError):delete_scores(directory,files,protected)
            self.assertTrue(a.exists())
            with patch.object(Path,'is_symlink',return_value=True):
                with self.assertRaises(ValueError):delete_scores(root,[record])
            with patch.object(Path,'is_junction',return_value=True):
                with self.assertRaises(ValueError):delete_scores(root,[record])
            self.assertTrue(a.exists())

    def test_folder_inventory_includes_stopped_jobs_but_not_running_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for status in ('completed','cancelled','failed','interrupted','running','stopping'):
                folder=self.make_folder(root,status,status)
                if status!='completed':(folder/'score_keys.txt').unlink()
            self.assertEqual({Path(f['path']).name for f in list_score_folders(root)['files']},
                             {'completed','cancelled','failed','interrupted'})
            self.assertEqual(len(list_scores(root)['files']),1)
            legacy=self.make_folder(root,'legacy-training')
            (legacy/'job.json').write_text('{"kind":"training","status":"completed"}','utf-8')
            self.assertNotIn(str(legacy),[f['path'] for f in list_score_folders(root)['files']])

    def test_application_folder_cannot_be_offered_for_deletion(self):
        from keyscope import score_library
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);app=root/'application';app.mkdir()
            with patch.object(score_library,'ROOT',app):
                self.make_folder(app,'runtime');self.make_folder(app,'models')
                (app/'runs').mkdir();job=self.make_folder(app/'runs','job')
                self.assertEqual([f['path'] for f in list_score_folders(app)['files']],[str(job)])
                self.assertEqual(list_score_folders(root)['files'],[])

    def test_incomplete_jobs_and_part_files_not_listed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'score.txt.part').write_text('0 Q','utf-8')
            (root/'score.txt').write_text('0 Q','utf-8')
            for status in ('running','stopping','failed','interrupted'):
                (root/'job.json').write_text(json.dumps({'status':status}),'utf-8')
                self.assertEqual(list_scores(root)['files'],[])
            (root/'job.json').write_text('{"status":"completed"}','utf-8')
            self.assertEqual(len(list_scores(root)['files']),1)

    def test_delete_removes_live_and_saved_history_without_recreating_folder(self):
        for live in (True,False):
            with self.subTest(live=live),tempfile.TemporaryDirectory() as temp, patch.object(jobs,'ROOT',Path(temp)):
                root=Path(temp);manager=jobs.JobManager()
                job=jobs.Job('inference',{**DEFAULTS,'output_dir':str(root/'runs')})
                path=job.output/'score_keys.txt';path.write_text('0 Q','utf-8');job.artifact(path,'Detection log')
                job.update(status='completed');job.save()
                if live:manager.jobs[job.id]=job
                manager.index=[{'id':job.id,'path':str(job.output/'job.json')}]
                result=manager.delete_scores(root/'runs',list_score_folders(root/'runs')['files'])
                self.assertFalse(result['errors']);self.assertEqual(result['removed_jobs'],[job.id])
                self.assertFalse(job.output.exists());self.assertEqual(manager.list(),[])
                self.assertEqual(json.loads(manager.index_path.read_text('utf-8')),[])
                with self.assertRaises(ValueError):manager.get(job.id)

    def test_cancel_before_mid_and_after_last_batch_discards_outputs(self):
        for mode in ('before','mid','late','complete'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp, patch.object(jobs,'ROOT',Path(temp)):
                manager=jobs.JobManager()
                cfg={**DEFAULTS,'model_path':'models/faster_rcnn.onnx','device':'cpu','output_dir':temp,'video_path':make_video(temp)}
                job=jobs.Job('inference',cfg);manager.jobs[job.id]=job;manager.active=job.id;job.save()
                calls=[0]
                def predict(model,arrays,*args):
                    calls[0]+=1
                    self.assertEqual(list_scores(temp)['files'],[])
                    self.assertFalse(list(job.output.glob('*.txt')))
                    self.assertFalse(list(job.output.glob('*.csv')))
                    self.assertFalse((job.output/'preview.jpg').exists())
                    if mode=='mid' and calls[0]==3:job.cancel.set()
                    return [np.array([[48,58,169,186,.99]]) for _ in arrays]
                real_run=engine.run_inference
                def run(current):
                    real_run(current)
                    if mode=='late':current.cancel.set()
                if mode=='before':job.cancel.set()
                with patch('keyscope.backends.ONNXModel',return_value=Mock(batch_size=1,precision='FP32',setup_seconds=0,backend='cpu',device_name='CPU')), \
                     patch.object(hardware,'select_directml',return_value=None), \
                     patch.object(engine,'predict',side_effect=predict), \
                     patch.object(engine,'run_inference',side_effect=run):
                    manager._run(job)
                if mode=='complete':
                    self.assertEqual(job.state['status'],'completed')
                    self.assertEqual(len(job.state['artifacts']),4)
                    self.assertEqual(len(list_scores(temp)['files']),1)
                    self.assertFalse(list(job.output.glob('*.part')))
                else:
                    self.assertEqual(job.state['status'],'cancelled')
                    self.assertEqual({p.name for p in job.output.iterdir()},{'job.json','task.log'})
                    self.assertEqual(job.state['artifacts'],[]);self.assertFalse(job.state['has_preview'])

    def test_late_stop_rejected_without_cancelling_completed_job(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(jobs,'ROOT',Path(temp)):
            manager=jobs.JobManager();job=jobs.Job('inference',{**DEFAULTS,'output_dir':temp})
            manager.jobs[job.id]=job;manager.active=job.id;job.update(status='completed')
            with self.assertRaises(ValueError):manager.stop(job.id)
            self.assertFalse(job.cancel.is_set())


if __name__=='__main__':unittest.main()
