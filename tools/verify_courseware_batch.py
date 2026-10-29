"""Real serial batch acceptance; audit identities, page bytes and output paths."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import io
from queue import Empty
from threading import Event
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pypdf import PdfReader
from PIL import Image, ImageOps
from ykt import courseware as C, selectors as S
from ykt.accounts import Accounts
from ykt.extractor import _state
from ykt.files import Manifest
from ykt.downloader import resource_key
from ykt.selection import CourseSelection
from ykt.storage import read_json, write_json
from ykt.worker import ScanWorker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', choices=('single', 'multi'), required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--courseware-only', action='store_true')
    parser.add_argument('--second', action='store_true')
    parser.add_argument('--writing', action='store_true')
    parser.add_argument('--remaining-writing', action='store_true')
    args = parser.parse_args()
    base = ROOT / '.local/courseware_batch_fix'
    a = Accounts(ROOT, 'https://changjiang.yuketang.cn')
    account = (a.get(read_json(ROOT / '.local/v2_stage4/second_account.json')['account_id'])
               if args.second else next(r for r in a.rows if r['legacy']))
    catalog = read_json(a.site_dir(account) / 'courses.json')
    ids = [('25393631', 10)] if args.scenario == 'single' else [('25393631', 5), ('25394317', 5)]
    if args.writing:
        assert args.scenario == 'multi'
        ids = [('25391135', 5), ('25393631', 5)]
    if args.remaining_writing:
        assert args.second
        ids = [('25391135', 2)]
    model = CourseSelection()
    model.replace(catalog)
    for cid, count in ids:
        c = next(c for c in catalog['courses'] if c['id'] == cid)
        offset = 5 if args.remaining_writing else 0
        lessons = [l for l in c['lessons'] if l.get('is_finished') is True][offset:offset + count]
        assert len(lessons) == count
        for lesson in lessons:
            model.toggle_lesson((cid, lesson['id']))
    tasks = model.tasks()
    expected_count = sum(count for _, count in ids)
    assert len(tasks) == expected_count
    selected = base / args.label
    assert selected.parent == base and args.label not in ('.', '..')
    proof = dict(schema_version=1, scenario=args.scenario, selected_tasks=tasks,
                 options=dict(quiz_images=not args.courseware_only, quiz_pdf=not args.courseware_only,
                              courseware_pdf=True), extracted={}, written={}, feature_results=[], errors=[])
    proof_path = base / (args.label + '.json')
    active = {}
    original_extract, original_write = C.extract_courseware, C.write_pdf
    def key(task):
        return task['course_id'] + ':' + task['lesson']['id'] + ':' + task['lesson']['courseware_id']
    def extract(page, origin, task, stop, emit):
        identity = key(task)
        active['key'] = identity
        resources = original_extract(page, origin, task, stop, emit)
        assert urlsplit(page.url).path == S.REPORT_PATH.format(course_id=task['course_id'],
            courseware_id=task['lesson']['courseware_id'], lesson_id=task['lesson']['id'])
        frame = page.locator(S.REPORT_IFRAME).element_handle().content_frame()
        state = _state(frame)
        assert state['course_id'] == task['course_id'] and state['lesson_id'] == task['lesson']['courseware_id']
        assert state['selected'] == 0 and state['shown'] == state['all']
        proof['extracted'][identity] = dict(course_id=state['course_id'], lesson_id=state['lesson_id'],
            selected=state['selected'], events=state['all'], pages=len(resources),
            sequence=[dict(slide_id=r['slide_id'], page=r['page'],
                           resource_id=resource_key(r['candidates'][0])) for r in resources])
        write_json(proof_path, proof)
        return resources
    def write(path, paths, stop, page_size=C.LANDSCAPE):
        result = original_write(path, paths, stop, page_size=page_size)
        pdf = PdfReader(path, strict=True)
        assert len(pdf.pages) == len(paths)
        hashes = []
        formats = []
        def pixels(data):
            with Image.open(io.BytesIO(data)) as image:
                fmt = image.format
                normalized = ImageOps.exif_transpose(image).convert('RGBA')
                rgb = Image.new('RGB', normalized.size, 'white')
                rgb.paste(normalized, mask=normalized.getchannel('A'))
                return fmt, rgb.size, hashlib.sha256(rgb.tobytes()).hexdigest()
        for source, page in zip(paths, pdf.pages):
            data = source.read_bytes()
            obj = page['/Resources']['/XObject']['/Im0'].get_object()
            digest = hashlib.sha256(data).hexdigest()
            if str(obj['/Filter']) == '/DCTDecode':
                assert hashlib.sha256(obj.get_data()).hexdigest() == digest
                # pypdf page.images may re-encode a JPEG for its convenience
                # wrapper. Audit the actual embedded bytes instead.
                embedded_bytes = obj.get_data()
            else:
                embedded_bytes = page.images[0].data
            original = pixels(data)
            embedded = pixels(embedded_bytes)
            assert original[1:] == embedded[1:], 'Source pixels changed during PDF generation'
            formats.append(original[0])
            hashes.append(digest)
        proof['written'][active['key']] = dict(pages=len(paths), source_sha256=hashes,
            page_size=list(page_size), direct_jpeg_bytes_and_all_source_pixels_match=True, formats=formats)
        write_json(proof_path, proof)
        return result
    # Instrument only this process, without replacing site responses or source data.
    C.extract_courseware, C.write_pdf = extract, write
    worker = ScanWorker(a.origin, a.site_dir(account), account_id=account['id'],
                        expected_owner=account['owner'], layout='flat')
    logs = []
    worker.start_download(tasks, selected, account['owner'], proof['options'])
    try:
        while worker.running or not worker.events.empty():
            try:
                kind, data = worker.events.get(timeout=.25)
            except Empty:
                continue
            if kind == 'log':
                logs.append(data)
            elif kind == 'resource_state' and data.get('feature') == 'courseware_pdf':
                proof['feature_results'].append(data)
                print('BATCH_COURSEWARE', data['lesson_id'], data['status'], data.get('pages'),
                      data.get('error') or '', flush=True)
                write_json(proof_path, proof)
            elif kind in ('error', 'needs_human'):
                proof['errors'].append(dict(kind=kind, reason=data))
                worker.stop()
            elif kind == 'download_result':
                proof['result'] = data
    finally:
        worker.thread.join()
        C.extract_courseware, C.write_pdf = original_extract, original_write
        proof['worker_closed'] = not worker.running
        write_json(proof_path, proof)
        (base / (args.label + '.log')).write_text('\n'.join(logs), encoding='utf-8')
    m = Manifest(selected, account['owner'], a.origin, layout='flat')
    data = m.read_existing()
    paths = []
    for task in tasks:
        identity = key(task)
        lesson = data['lessons'][identity]
        meta = lesson.get('courseware_pdf', {})
        assert meta.get('status') == 'complete', (identity, meta.get('error'))
        assert meta['sequence'] == proof['extracted'][identity]['sequence']
        assert C.verified_courseware(m, meta, Event(), task)
        path = m.resolve(meta['path'])
        assert path.parent == m.resolve(data['courses'][task['course_id']])
        paths.append(path)
    assert len(set(paths)) == expected_count and not proof['errors']
    assert proof['result']['success'] == expected_count
    assert not list(selected.rglob('*.part'))
    proof['all_selected_complete_unique_and_bound_to_requested_lesson'] = True
    if expected_count == 10:
        proof['all_ten_complete_unique_and_bound_to_requested_lesson'] = True
    write_json(proof_path, proof)
    print('REAL_BATCH_ACCEPTANCE_PASSED', args.scenario, flush=True)


if __name__ == '__main__':
    main()
