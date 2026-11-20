"""Portable V2 regression; local HTTP failures are not platform test results."""
import io
import socket
import tempfile
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright
from ykt.browser import NeedsHuman
from ykt.downloader import download
from ykt.files import Manifest, image_info
from ykt.quiz_pdf import merge_lesson, verified_pdf
from ykt.storage import read_json
from ykt.accounts import Accounts

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://changjiang.yuketang.cn'

class V2DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='v2_portable_')
        self.root=Path(self.temp.name).resolve();self.owner='c'*64;self.stop=threading.Event()
        self.task=dict(course_id='1',course_name='CON',lesson=dict(id='2',courseware_id='3',name='A:B / 😀'))
        self.logs=[]
        image=Image.new('RGB',(320,240),'navy');stream=io.BytesIO();image.save(stream,'JPEG');self.jpeg=stream.getvalue()

    def tearDown(self):
        self.assertEqual(self.root,Path(self.temp.name).resolve())
        self.assertEqual(self.root.parent,Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith('v2_portable_'))
        self.temp.cleanup()

    def test_local_network_disconnect_503_retry_and_resume(self):
        counts=Counter();image=self.jpeg;fail={'enabled':True}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                counts['requests']+=1
                if fail['enabled']:
                    if counts['requests'] in (1,3):
                        self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                    self.send_response(503);self.end_headers();return
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(image)));self.end_headers();self.wfile.write(image)
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port)+'/fixture?token=LOCAL_TEST_SECRET'
        resources=dict(resources=[dict(candidates=[url],slide_id='10',page=1)],unsupported=[],pages=1)
        try:
            with sync_playwright() as pw:
                request=pw.request.new_context(timeout=5000)
                class Context:pass
                context=Context();context.request=request
                class Page:
                    def is_closed(self):return False
                with patch('ykt.downloader.verify_account'),patch('ykt.downloader.extract_lesson',return_value=resources):
                    first=download(context,Page(),ORIGIN,[self.task],self.root,self.owner,self.stop,self.logs.append)
                    self.assertEqual(first['failed'],1);self.assertEqual(first['downloaded'],0)
                    m=Manifest(self.root,self.owner,ORIGIN);lesson=next(iter(m.read_existing()['lessons'].values()))
                    self.assertEqual(next(iter(lesson['resources'].values()))['attempts_last_run'],3)
                    # HTTP client itself may replay a disconnected GET; the
                    # application retry budget is the persisted 3 attempts.
                    self.assertGreaterEqual(counts['requests'],3)
                    fail['enabled']=False
                    again=download(context,Page(),ORIGIN,[self.task],self.root,self.owner,self.stop,self.logs.append)
                    self.assertEqual(again['success'],1);self.assertEqual(again['downloaded'],1)
                request.dispose()
            self.assertNotIn('LOCAL_TEST_SECRET',' '.join(self.logs)+m.path.read_text('utf-8'))
            self.assertFalse(list(m.root.rglob('*.part')))
        finally:server.shutdown();server.server_close();thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_http_auth_failure_requires_human_without_retrying_around_it(self):
        from ykt.downloader import _fetch
        calls=[]
        class Response:
            status=403
            def dispose(self):calls.append('dispose')
        class Request:
            def get(self,*args,**kwargs):calls.append('get');return Response()
        class Context:request=Request()
        with self.assertRaises(NeedsHuman):_fetch(Context(),{},'https://local.invalid/fixture',ORIGIN,self.stop)
        self.assertEqual(calls,['get','dispose'])

    def test_same_names_reserved_names_pdf_and_unknown_file_collision(self):
        from ykt.downloader import _atomic_image
        tasks=[self.task,dict(self.task,course_id='4'),dict(self.task,lesson=dict(self.task['lesson'],id='5'))]
        with Manifest(self.root,self.owner,ORIGIN) as m:
            locations=[]
            for task in tasks:
                lesson=m.lesson(task);directory=m.directory_for(task,lesson);locations.append(directory)
                record=dict(status='pending',resource_id='a'*64);lesson['resources']['a'*64]=record
                info=image_info(self.jpeg);path=m.output_path(task,lesson,record,info,1,'a'*64)
                _atomic_image(m,path,record,self.jpeg,self.stop);record.update(info,status='complete')
                lesson.update(status='complete',quiz_pages=1,warnings=[],pdf_sequence=[dict(resource_id='a'*64,slide_id='10',page=1)])
            m.save()
            self.assertEqual(len(set(locations)),3)
            self.assertTrue(all('CON' in str(p) and ':' not in p.name and '/' not in p.name for p in locations))
            # An unknown user's PDF is preserved, a fresh owned name is used.
            unknown=locations[0]/'A_B _ 😀_习题合集.pdf';unknown.write_bytes(b'user existing file')
            result=merge_lesson(m,self.task,m,m.lesson(self.task),self.stop,self.logs.append)
            self.assertEqual(unknown.read_bytes(),b'user existing file')
            self.assertNotEqual(m.resolve(result['path']),unknown)
            self.assertTrue(verified_pdf(m,result,self.stop))

    def test_stop_before_pdf_still_lists_selected_pdf_tasks_for_resume(self):
        # Real orchestration and atomic image save; only site/network boundaries
        # use a labeled local fixture. This is not a live website result.
        from ykt.resource_export import export_resources
        from ykt.recovery import unfinished
        resources=dict(resources=[dict(candidates=['https://local.invalid/image'],slide_id='10',page=1)],unsupported=[],pages=1)
        future=dict(self.task,lesson=dict(self.task['lesson'],id='4',name='future lesson'))
        request=dict(tasks=[self.task,future],directory=self.root,owner=self.owner,
                     options=dict(quiz_images=True,quiz_pdf=True,courseware_pdf=True))
        def progress(value):
            if value['downloaded']>=1:self.stop.set()
        class Page:
            def is_closed(self):return False
        with patch('ykt.resource_export.verify_account'),patch('ykt.quiz_export.verify_account'),patch('ykt.downloader.verify_account'),patch('ykt.downloader.extract_lesson',return_value=resources),patch('ykt.downloader._fetch',return_value=self.jpeg):
            result=export_resources(None,Page(),ORIGIN,request,self.root/'site','local-unit','legacy',self.stop,self.logs.append,
                                    lambda *_:None,lambda *_:None,progress)
        self.assertEqual(result['status'],'stopped')
        rows=unfinished(self.root,self.owner,ORIGIN,features=['quiz_pdf','courseware_pdf'])
        self.assertEqual([(r['course_id'],r['lesson_id']) for r in rows],[('1','2'),('1','4')])
        self.assertTrue(any('习题PDF' in reason for reason in rows[0]['reasons']))
        self.assertTrue(any('课件PDF' in reason for reason in rows[0]['reasons']))

    def test_atomic_json_retries_a_brief_windows_shared_reader(self):
        from ykt.storage import write_json
        path=self.root/'shared.json';write_json(path,dict(schema_version=1,value='old'))
        held=path.open('rb');release=threading.Timer(.12,held.close);release.start()
        try:
            write_json(path,dict(schema_version=1,value='new'))
        finally:
            release.join();held.close()
        self.assertEqual(read_json(path)['value'],'new')

    def test_atomic_json_persistent_windows_lock_keeps_old_data(self):
        from ykt.storage import write_json
        path=self.root/'shared.json';write_json(path,dict(schema_version=1,value='old'))
        before=path.read_bytes()
        with path.open('rb'):
            with self.assertRaises(PermissionError):write_json(path,dict(schema_version=1,value='new'))
            self.assertEqual(path.read_bytes(),before)
        self.assertEqual(read_json(path)['value'],'old')

    def test_two_account_output_and_state_keys_are_independent(self):
        from ykt.tasks import TaskLedger,task_key
        store=Accounts(self.root,ORIGIN);first=store.get();second=store.add(first['name'])
        self.assertNotEqual(store.image_directory(first,self.root),store.image_directory(second,self.root))
        self.assertNotEqual(store.site_dir(first),store.site_dir(second))
        for f in ('quiz_images','quiz_pdf','courseware_pdf'):
            self.assertNotEqual(task_key(first['id'],self.task,f),task_key(second['id'],self.task,f))
        for mask in range(1,8):
            options={f:bool(mask&(1<<i)) for i,f in enumerate(('quiz_images','quiz_pdf','courseware_pdf'))}
            with TaskLedger(store.site_dir(second),second['id'],ORIGIN) as ledger:
                ledger.begin([self.task],options)
                counts=ledger.counts()
                self.assertEqual({f:c['total'] for f,c in counts.items()},{f:int(v) for f,v in options.items()})
                self.assertTrue(all(c['success']==0 for c in counts.values()))

if __name__=='__main__':unittest.main()
