"""Diagnose actual serial lesson transitions without persisting signed URLs."""
import sys
import argparse
from pathlib import Path
from threading import Event
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ykt.accounts import Accounts
from ykt.browser import open_browser
from ykt.downloader import verify_account
from ykt.extractor import extract_lesson, _state
from ykt.courseware import extract_courseware
from ykt import selectors as S
from ykt.storage import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--second', action='store_true')
    parser.add_argument('--course', default='25393631')
    parser.add_argument('--skip', type=int, default=0)
    parser.add_argument('--count', type=int, default=3)
    parser.add_argument('--label', default='probe')
    args = parser.parse_args()
    a = Accounts(ROOT, 'https://changjiang.yuketang.cn')
    row = (a.get(read_json(ROOT / '.local/v2_stage4/second_account.json')['account_id'])
           if args.second else next(r for r in a.rows if r['legacy']))
    cache = read_json(a.site_dir(row) / 'courses.json')
    course = next(c for c in cache['courses'] if c['id'] == args.course)
    tasks = [dict(course_id=course['id'], course_name=course['name'], lesson=l)
             for l in course['lessons'] if l.get('is_finished') is True][args.skip:args.skip + args.count]
    stop = Event()
    proof = dict(schema_version=1, cases=[])
    def save():
        write_json(ROOT / '.local/courseware_batch_fix' / (args.label + '.json'), proof)
    with open_browser(a.site_dir(row) / 'browser', lambda _: None) as (_, page):
        verify_account(page, a.origin, row['owner'], stop, lambda _: None)
        for task in tasks:
            current = dict(task=task, responses=[], log=[])
            proof['cases'].append(current)
            def response(r):
                u = urlsplit(r.url)
                if u.path.startswith(S.REPORT_API_PREFIX):
                    current['responses'].append(dict(endpoint=u.path.rsplit('/', 1)[-1],
                        lesson_id=parse_qs(u.query).get('lesson_id'), status=r.status))
                    if u.path.endswith('/review') and r.status == 200:
                        data = r.json().get('data', {})
                        rows = data.get('timelineList', [])
                        current['review_keys'] = list(data)
                        current['timeline'] = [{k: v for k, v in x.items() if k not in ('cover', 'image', 'url')
                            and (v is None or isinstance(v, (int, bool)) or
                                 (isinstance(v, str) and '://' not in v))} for x in rows]
            page.on('response', response)
            try:
                quiz = extract_lesson(page, a.origin, task, stop, current['log'].append)
                current['quiz_pages'] = quiz['pages']
                resources = extract_courseware(page, a.origin, task, stop, current['log'].append)
                current['courseware_pages'] = len(resources)
                current['slide_ids'] = [r['slide_id'] for r in resources]
                current['status'] = 'complete'
            except Exception as exc:
                current.update(status='failed', error_type=type(exc).__name__)
                if type(exc).__name__ in ('PageChanged', 'NeedsHuman'):
                    current['reason'] = str(exc)
                try:
                    frame = page.locator(S.REPORT_IFRAME).element_handle().content_frame()
                    state = _state(frame)
                    if state:
                        for slide in state['slides']:
                            slide.pop('cover', None)
                        current['state'] = state
                    preview = frame.locator(S.REPORT_VIEW).evaluate("""e=>{
                        const s=e.__vue__?._setupState;const val=x=>x?.__v_isRef?x.value:x;
                        const rows=val(s.swiperList);return {setupKeys:Object.keys(s),
                          rows:rows.map(x=>({keys:Object.keys(x),id:String(x.id),page:x.index,
                            visible:x.visible,type:x.type,dt:x.dt}))};}""")
                    current['preview'] = preview
                    current['tabs'] = frame.locator(S.QUIZ_TABS).inner_text()
                    current['special_dom'] = []
                    for index, slide in enumerate(state['slides']):
                        if slide['kind'] == 'slide':
                            continue
                        item = frame.locator(S.QUIZ_ITEMS).nth(index)
                        dom = item.evaluate("""e=>({tag:e.tagName,cls:e.className,
                          descendants:[...e.querySelectorAll('*')].map(x=>({tag:x.tagName,cls:x.className})),
                          images:[...e.querySelectorAll('img')].map(x=>({attrs:[...x.attributes].map(a=>a.name),
                            width:x.naturalWidth,height:x.naturalHeight}))})""")
                        data = item.evaluate(S.QUIZ_RESOURCE_DATA)
                        dom.update(index=index, kind=slide['kind'], dt=slide['dt'],
                                   resources=len(data['resources']), unsupported=data['unsupported'])
                        current['special_dom'].append(dom)
                except Exception:
                    current['state_unavailable'] = True
            finally:
                page.remove_listener('response', response)
                save()
            print('REAL_BATCH_PROBE', task['lesson']['id'], current['status'],
                  current.get('reason', ''), current.get('courseware_pages', ''), flush=True)
    print('PROBE_CONTEXT_CLOSED', flush=True)


if __name__ == '__main__':
    main()
