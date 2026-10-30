"""Live naming acceptance, with fresh course-page order and private QA output."""
import hashlib
import sys
from copy import deepcopy
from pathlib import Path
from queue import Empty
from threading import Event

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ykt import selectors as S
from ykt.accounts import Accounts
from ykt.browser import open_browser
from ykt.downloader import verify_account
from ykt.files import Manifest, safe_prefixed_name
from ykt.naming import NamingPlan, NamingControl, lesson_key, prepare_positions, snapshot
from ykt.scanner import scan_lessons
from ykt.storage import read_json, write_json
from ykt.worker import ScanWorker
from ykt.quiz_pdf import verified_pdf
from ykt.courseware import verified_courseware


def main():
    base=ROOT/'.local/v23'
    a=Accounts(ROOT,'https://changjiang.yuketang.cn')
    row=next(r for r in a.rows if r['legacy'])
    cache=read_json(a.site_dir(row)/'courses.json')
    course=deepcopy(next(c for c in cache['courses'] if c['id']=='25393631'))
    with open_browser(a.site_dir(row)/'browser',lambda _:None) as (_,page):
        verify_account(page,a.origin,row['owner'],Event(),lambda _:None)
        scan_lessons(page,course,a.origin,Event(),lambda _:None)
        dom=[]
        for activity in page.locator(S.LOG_LIST).locator(S.LOG_ACTIVITY).all():
            if activity.locator(S.CLASSROOM_ICON).count():
                dom.append(' '.join(activity.locator(S.LOG_TITLE).inner_text().split()))
        expected=[' '.join(l['name'].split()) for l in course['lessons']]
        assert dom==expected, 'Default page order differs from scanned order'
    course['status']='complete'
    catalog=dict(cache,courses=[course])
    finished=[(i,l) for i,l in enumerate(course['lessons']) if l.get('is_finished') is True]
    assert len(finished)>=3
    selected=[finished[0],finished[2]]
    tasks=[dict(course_id=course['id'],course_name=course['name'],lesson=l) for _,l in selected]
    output=base/'real_output'
    proof=dict(schema_version=1,course_page_default_dom_order_matches=True,
        complete_course_lessons=len(course['lessons']),selected_page_positions=[i+1 for i,_ in selected],
        cases={},all_three_mode_pdf_content_sha256_equal=True)
    payloads={}
    def save():write_json(base/'real_naming_verified.json',proof)
    def products():
        return {str(p.relative_to(output)):(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
                for p in output.rglob('*') if p.suffix.lower() in ('.pdf','.jpg','.png')}
    def run(mode,label):
        before=products()
        worker=ScanWorker(a.origin,a.site_dir(row),account_id=row['id'],expected_owner=row['owner'],layout='flat')
        worker.set_naming_mode(mode)
        worker.start_download(tasks,output,row['owner'],dict(quiz_images=True,quiz_pdf=True,courseware_pdf=True),catalog=catalog)
        result=None;errors=[]
        while worker.running or not worker.events.empty():
            try:kind,data=worker.events.get(timeout=.25)
            except Empty:continue
            if kind=='download_result':result=data
            elif kind in ('error','needs_human'):errors.append(kind);worker.stop()
        worker.thread.join()
        assert result and result['success']==2 and not errors,(label,result,errors)
        manifest=Manifest(output,row['owner'],a.origin,layout='flat')
        data=manifest.read_existing()
        assert len(data['courses'])==1
        planned=deepcopy(tasks);prepare_positions(planned,catalog)
        control=NamingControl();control.set(mode);NamingPlan(control,planned)
        paths=[]
        for task in planned:
            key=lesson_key(task);lesson=data['lessons'][key];prefix=snapshot(task,mode)['prefix']
            stem=safe_prefixed_name(task['lesson']['name'],prefix,manifest.budget)
            parent=manifest.resolve(data['courses'][task['course_id']])
            assert manifest.resolve(lesson['directory'])==parent/'习题图片'/stem
            for record in lesson['resources'].values():
                if record['status'] in ('complete','duplicate'):
                    assert manifest.verified(record)
                    image=manifest.resolve(record['path'])
                    assert image.parent==parent/'习题图片'/stem
                    assert image.name.startswith(prefix+'习题_')
                    paths.append(record['path'])
            if lesson['quiz_pdf'].get('status')=='no_images':
                assert lesson['quiz_pdf']['pages']==0 and not lesson['quiz_pdf'].get('path')
                assert not manifest.resolve(lesson['directory']).exists()
            else:
                assert verified_pdf(manifest,lesson['quiz_pdf'])
            assert verified_courseware(manifest,lesson['courseware_pdf'],Event(),task)
            for feature,suffix in (('quiz_pdf','_习题合集.pdf'),('courseware_pdf','_课件.pdf')):
                if lesson[feature].get('status')=='no_images':
                    continue
                path=manifest.resolve(lesson[feature]['path'])
                assert path==parent/(stem+suffix)
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                identity=(task['lesson']['id'],feature)
                if identity in payloads:assert payloads[identity]==digest
                else:payloads[identity]=digest
                paths.append(lesson[feature]['path'])
        after=products()
        assert all(after[path]==value for path,value in before.items())
        if label.endswith('repeat'):
            assert result['downloaded']==0 and after==before
        assert not list(output.rglob('*.part'))
        proof['cases'][label]=dict(result=result,paths=paths,old_products_unchanged=True,
                                  worker_closed=not worker.running)
        save();print('V23_REAL_MODE',label,'passed',flush=True)
    for mode in ('original','date','sequence'):run(mode,mode)
    run('date','date_repeat')
    proof['original_date_sequence_independent_entries']=6
    save();print('V23_REAL_NAMING_ACCEPTANCE_PASSED',flush=True)


if __name__=='__main__':main()
