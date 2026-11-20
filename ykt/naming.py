"""Optional naming snapshots; a running lesson never changes its own paths."""
from datetime import datetime, timedelta, timezone
from threading import Lock

MODES = {'original': '原命名', 'date': '日期前缀', 'sequence': '课程序号'}
LOCAL_TIME = timezone(timedelta(hours=8))


def valid_identifiers(course_id, lesson):
    if not isinstance(lesson, dict):
        return False
    values = (course_id, lesson.get('id'), lesson.get('courseware_id'))
    return all(isinstance(v, str) and v.isascii() and v.isdigit() and int(v) > 0 for v in values)


def base_lesson_key(task):
    return task['course_id'] + ':' + task['lesson']['id'] + ':' + task['lesson']['courseware_id']


def lesson_key(task):
    base = base_lesson_key(task)
    naming = task.get('_naming', {})
    mode = naming.get('mode', 'original')
    return base if mode == 'original' else base + '|' + mode + '|' + naming.get('prefix', '')


def named(task, label):
    return task.get('_naming', {}).get('prefix', '') + label


def chinese_number(number):
    if type(number) is not int or number < 1:
        raise ValueError('课次序号无效')
    for unit, text in ((100000000, '亿'), (10000, '万')):
        if number >= unit:
            high, low = divmod(number, unit)
            return chinese_number(high) + text + (('零' if low < unit // 10 else '') + chinese_number(low) if low else '')
    digits = '零一二三四五六七八九'
    units = ('', '十', '百', '千')
    result, zero = '', False
    for place in range(3, -1, -1):
        digit = number // (10 ** place) % 10
        if digit:
            if zero:
                result += '零'
            result += digits[digit] + units[place]
            zero = False
        elif result:
            zero = True
    return result[1:] if result.startswith('一十') else result


def date_prefix(value):
    try:
        # The verified LOG_DATA.create_time is milliseconds since Unix epoch.
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return datetime.fromtimestamp(value / 1000, LOCAL_TIME).strftime('%m%d') + '_'
    except (ValueError, OSError, OverflowError):
        pass
    return ''


def prepare_positions(tasks, catalog):
    """Full displayed course order, never the selected subset or date sorting."""
    if catalog is None:
        return
    positions = {}
    for course in catalog.get('courses', []):
        count, seen = 0, set()
        for lesson in course.get('lessons', []):
            lid, cw = str(lesson.get('id', '')), str(lesson.get('courseware_id', ''))
            if not valid_identifiers(str(course['id']), lesson) or lid in seen:
                continue
            seen.add(lid)
            count += 1
            positions[(str(course['id']), lid, cw)] = count
    for task in tasks:
        task['_course_position'] = positions.get((task['course_id'], task['lesson']['id'], task['lesson']['courseware_id']))


def snapshot(task, mode):
    if mode not in MODES:
        raise ValueError('未知命名模式')
    prefix, warning = '', ''
    if mode == 'date':
        prefix = date_prefix(task['lesson'].get('created_at'))
        if not prefix:
            warning = '授课日期无法提取，当前课时回退原命名'
    elif mode == 'sequence':
        position = task.get('_course_position')
        if type(position) is int and position > 0:
            prefix = '（' + chinese_number(position) + '）'
        else:
            warning = '缺少完整课程页序，当前课时回退原命名；请重新扫描课程'
    return dict(mode=mode, prefix=prefix, warning=warning)


class NamingControl:
    def __init__(self):
        self.lock = Lock()
        self.mode = 'original'

    def set(self, mode):
        if mode not in MODES:
            raise ValueError('未知命名模式')
        with self.lock:
            self.mode = mode

    def get(self):
        with self.lock:
            return self.mode


class NamingPlan:
    def __init__(self, control, tasks):
        self.control, self.tasks = control, tasks
        self.registered = False
        for task in tasks:
            for field in ('_naming_bound', '_naming_previous_key', '_naming_created_pending'):
                task.pop(field, None)
            self._set(task, control.get())

    def _set(self, task, mode):
        previous = lesson_key(task)
        info = snapshot(task, mode)
        if mode == 'original':
            task.pop('_naming', None)
        else:
            task['_naming'] = info
        if previous != lesson_key(task):
            task['_naming_previous_key'] = previous
        return info

    def bind(self, task, emit):
        if task.get('_naming_bound'):
            return
        info = self._set(task, self.control.get())
        task['_naming_bound'] = True
        emit('[命名] {} / {}：{}{}'.format(task['course_name'], task['lesson']['name'], MODES[info['mode']],
             '，前缀 ' + info['prefix'] if info['prefix'] else ''))
        if info['warning']:
            emit('[命名] ' + info['warning'])

    def finish_pending(self, request, origin, layout):
        remaining = [t for t in self.tasks if not t.get('_naming_bound')]
        features = [f for f in ('quiz_pdf', 'courseware_pdf') if request['options'].get(f)]
        if not self.registered or not features:
            return
        mode = self.control.get()
        for task in remaining:
            self._set(task, mode)
        # Only move placeholders created by this request. Historical results
        # and historical unfinished work in other modes always remain intact.
        from .quiz_export import _record_pending_pdfs
        _record_pending_pdfs(request, origin, layout, features)
