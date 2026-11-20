"""Export only the static pages actually exposed in the authorized report."""
import hashlib
import json
import os
import uuid
from urllib.parse import urlsplit
from playwright.sync_api import TimeoutError
from . import selectors as S
from .browser import NeedsHuman, PageChanged, Stopped, check_stop, navigate, wait_condition
from .extractor import ReportWatch, _wait_state, _state
from .scanner import valid_id
from .downloader import resource_key, _fetch, _atomic_image
from .files import FileProblem, Manifest, image_info
from .pdf_work import PdfWork
from .quiz_pdf import A4, write_pdf, validate_pdf, sha_file, pdf_path
from .naming import lesson_key, base_lesson_key
from .quiz_grid import (courseware_field, courseware_layout, grid_fingerprint, layout_suffix,
                        matching_page_groups, validate_grid_pdf, write_grid_pdf)


def ordered_slides(slides):
    unique = {}
    pages = {}
    groups = {}
    positions = {}
    current_group, anchor = '', 0
    for index, slide in enumerate(slides):
        if slide.get('visible') is False:
            continue
        kind = slide.get('kind')
        if kind == 'capture' and slide.get('visible') in (None, True):
            dt = slide.get('dt')
            if type(dt) is not int or dt < 1:
                raise PageChanged('课堂截图缺少稳定时间标识，未猜测页面归属')
            slide = dict(slide, slide_id='capture_' + str(dt))
            identity = ('capture', dt)
            group, number, after = current_group, anchor, 1
        elif slide.get('visible') is True and kind == 'slide':
            group = slide.get('presentation_id') or ''
            if group:
                group = valid_id(group)
            sid = valid_id(slide['slide_id'])
            number = slide['page']
            if type(number) is not int or number < 1:
                raise PageChanged('课件页码无效，无法确认原始页序')
            identity = ('slide', group, sid)
            page_key = (group, number)
            if page_key in pages and pages[page_key] != sid:
                raise PageChanged('同一份课件的同一页码对应不同静态页，未猜测课件顺序')
            pages[page_key] = sid
            current_group, anchor = group, number
            after = 0
        else:
            raise PageChanged('课件可见状态或渲染类型尚未验证')
        groups.setdefault(group, len(groups))
        if identity in unique:
            old_cover = unique[identity][1].get('cover')
            if old_cover and slide.get('cover') and resource_key(old_cover) != resource_key(slide['cover']):
                raise PageChanged('同一课件页存在不同静态图，未丢弃可能的展示内容')
            if kind == 'slide' and unique[identity][1]['page'] != number:
                raise PageChanged('重复课件页的页码不一致')
        else:
            unique[identity] = (index, slide)
            positions[identity] = (groups[group], number, after, index)
    return [unique[key] for key in sorted(unique, key=positions.__getitem__)]


def preview_matches(slides, preview):
    """Match every provided static event, including captures with generated ids."""
    def keys(rows):
        result = []
        for slide in rows:
            if slide.get('visible') is False:
                continue
            if slide.get('kind') == 'capture' and slide.get('visible') in (None, True):
                dt = slide.get('dt')
                if type(dt) is not int or dt < 1:
                    raise PageChanged('课堂截图时间标识无效')
                result.append(('capture', dt))
            elif slide.get('kind') == 'slide' and slide.get('visible') is True:
                result.append(('slide', slide['slide_id'], slide.get('presentation_id') or '', slide['page']))
            else:
                raise PageChanged('课件预览含未验证的渲染类型')
        return result
    return isinstance(preview, list) and keys(slides) == keys(preview)


def extract_courseware(page, origin, task, stop, emit):
    cid = valid_id(task['course_id'])
    lesson = task['lesson']
    if lesson.get('is_finished') is False:
        raise PageChanged('课堂尚未结束，课件报告暂不可用')
    cw, lid = valid_id(lesson['courseware_id']), valid_id(lesson['id'])
    target_path = S.REPORT_PATH.format(course_id=cid, courseware_id=cw, lesson_id=lid)
    for attempt in range(4):
        try:
            with ReportWatch(page, origin, cw) as watch:
                navigate(page, origin + target_path, stop, emit, retries=0)
                if urlsplit(page.url).path != target_path:
                    raise NeedsHuman('课件报告跳转至其他页面，请人工检查登录或授权')
                wait_condition(page, S.REPORT_FRAME_READY, stop)
                frame = page.locator(S.REPORT_IFRAME).element_handle().content_frame()
                if frame is None or urlsplit(frame.url).hostname != urlsplit(origin).hostname:
                    raise NeedsHuman('课件报告跳转，请人工检查登录或授权')
                state = _wait_state(page, frame, watch, cid, stop)
                if state['selected'] != 0:
                    frame.locator(S.QUIZ_TABS).get_by_text(S.COURSEWARE_TAB_NAME, exact=True).click(timeout=10000)
                state = _wait_state(page, frame, watch, cid, stop, all_slides=True)
                items = frame.locator(S.QUIZ_ITEMS)
                if items.count() != watch.count:
                    raise PageChanged('课件列表未完整加载')
                preview = frame.locator(S.REPORT_VIEW).evaluate(S.COURSEWARE_PREVIEW_DATA)
                if not preview_matches(state['slides'], preview):
                    raise PageChanged('课件预览与可见放映记录不一致')
                hidden = sum(s.get('visible') is False for s in state['slides'])
                for index, slide in enumerate(state['slides']):
                    if slide.get('visible') is False and items.nth(index).locator(S.QUIZ_IMAGE_REGION).count():
                        raise PageChanged('隐藏页与实际页面状态冲突')
                if hidden:
                    emit('平台未显示{}条隐藏记录，未请求其图片'.format(hidden))
                selected = ordered_slides(state['slides'])
                resources = []
                for index, slide in selected:
                    check_stop(stop)
                    watch.check()
                    item = items.nth(index)
                    item.scroll_into_view_if_needed(timeout=10000)
                    if item.locator(S.COURSEWARE_UNSUPPORTED).count():
                        raise PageChanged('课件含Canvas、视频或交互内容，当前结构未可靠导出')
                    data = item.evaluate(S.QUIZ_RESOURCE_DATA)
                    if data['unsupported'] or len(data['resources']) != 1:
                        raise PageChanged('课件不是已验证的单图静态页；Canvas、视频或交互内容未可靠导出')
                    candidates = data['resources'][0]['candidates']
                    if not candidates:
                        raise PageChanged('课件图片没有可用资源入口')
                    resources.append(dict(candidates=candidates, slide_id=slide['slide_id'], page=slide['page'], frame=frame))
                watch.check()
                final = _state(frame)
                if (urlsplit(page.url).path != target_path or not final or
                        final['lesson_id'] != cw or final['course_id'] != cid or
                        final['selected'] != 0 or final['shown'] != watch.count):
                    raise PageChanged('提取过程中课时或课件视图已变化，未保存可能串用的内容')
                emit('报告{}条放映事件，核对{}个可访问静态页；按课件分组/原始页码排序，课堂截图跟随对应页面，重复放映去重'.format(watch.count,len(resources)))
                emit('仅导出报告实际提供的静态页；未放映或未提供的原始课件页不推测、不补抓')
                return resources
        except TimeoutError:
            if attempt == 3:
                raise PageChanged('课件页面连续加载超时') from None
            emit('课件加载超时，重试 {}/3'.format(attempt+1))
            if stop.wait(attempt+1):
                check_stop(stop)

LANDSCAPE = (A4[1], A4[0])
PURPOSE = 'courseware_pdf_temporary_images'
COURSEWARE_VERSION = 2


def verified_courseware(manifest, meta, stop, task=None, grid=None):
    try:
        path = manifest.resolve(meta['path'])
        bound = meta.get('lesson_key')
        expected = None if task is None else task['course_id']+':'+task['lesson']['id']+':'+task['lesson']['courseware_id']
        spec = courseware_layout(grid)
        if meta.get('grid_layout') != spec:
            return False
        basic_valid = (isinstance(bound, str) and len(bound.split(':')) == 3 and all(x.isdigit() for x in bound.split(':'))
            and (expected is None or bound == expected)
            and meta['status']=='complete' and meta['version']==COURSEWARE_VERSION and meta['scope']=='report_static_pages'
            and type(meta['pages']) is int and meta['pages']>0
            and path.suffix.lower()=='.pdf' and path.stat().st_size==meta['size']
            and sha_file(path,stop)==meta['sha256'])
        if not basic_valid:
            return False
        pages = meta['pages']
        slides = len(meta['sequence'])
        if spec is None:
            return slides == pages and validate_pdf(path,pages,stop,page_size=LANDSCAPE)
        checks = meta['grid_page_checks']
        suffix = '_课件' + layout_suffix(spec, unit='张') + '.pdf'
        return (path.name.endswith(suffix) and matching_page_groups(checks,pages,slides,spec)
                and validate_grid_pdf(path,pages,spec,checks,stop))
    except (KeyError,TypeError,ValueError,OSError,FileProblem):
        return False


def export_courseware(context,page,origin,task,directory,owner,site_dir,account_id,layout,stop,emit,grid=None):
    """One authorized lesson; failures remain independent of quiz products."""
    spec = courseware_layout(grid)
    suffix = '_课件' + layout_suffix(spec, unit='张') + '.pdf'
    with Manifest(directory,owner,origin,layout=layout) as target:
        key=lesson_key(task)
        bound_key=base_lesson_key(task)
        new=key not in target.data['lessons']
        lesson=target.lesson(task)
        if new: lesson['status']='pdf_only'
        meta=lesson.setdefault(courseware_field(spec),{})
        if not isinstance(meta, dict):
            raise FileProblem('课件PDF记录损坏，原清单已保留，请检查后重试')
        result=dict(status='running',resource_state='unknown',error=None,error_type=None)
        try:
            resources=extract_courseware(page,origin,task,stop,emit)
            sequence=[dict(slide_id=r['slide_id'],page=r['page'],resource_id=resource_key(r['candidates'][0])) for r in resources]
            fingerprint=hashlib.sha256(json.dumps(dict(version=COURSEWARE_VERSION,lesson_key=bound_key,sequence=sequence),sort_keys=True).encode()).hexdigest()
            if spec is not None:
                fingerprint = grid_fingerprint(fingerprint, spec)
            if not resources:
                meta.update(status='no_images',pages=0,error=None,error_type=None)
                result.update(status='no_images',resource_state='absent')
                return result
            result['resource_state']='available'
            if meta.get('fingerprint')==fingerprint and verified_courseware(target,meta,stop,task,grid=spec):
                emit('已核对页面范围和本地PDF，完整跳过：' + meta['path'])
                return dict(meta,resource_state='available',skipped=True)
            if spec is not None and meta.get('path') and not meta['path'].endswith(suffix):
                raise FileProblem('课件PDF记录的路径与所选排版不符')
            path=pdf_path(target,task,lesson,meta,suffix=suffix)
            meta.update(status='running',path=str(path.relative_to(target.root)),fingerprint=fingerprint,
                        scope='report_static_pages',sequence=sequence,lesson_key=bound_key)
            if spec is not None:
                meta['grid_layout'] = spec
            target.save()
            with PdfWork(site_dir,account_id,task,owner,origin,purpose=PURPOSE) as work:
                paths=[]
                with Manifest(work.root,owner,origin) as cache:
                    cached=cache.lesson(task)
                    for index,resource in enumerate(resources,1):
                        check_stop(stop)
                        label = '课堂截图' if resource['page'] is None else 'P{}'.format(resource['page'])
                        rid=resource_key(resource['candidates'][0])
                        record=cached['resources'].setdefault(rid,dict(status='pending'))
                        if cache.verified(record):
                            paths.append(cache.resolve(record['path']))
                            emit('校验跳过课件页 {}/{}（{}）'.format(index,len(resources),label))
                            continue
                        for attempt in range(3):
                            record['attempts_last_run']=attempt+1
                            try:
                                data=_fetch(context,resource,resource['candidates'][0],origin,stop)
                                info=image_info(data)
                                local=cache.directory_for(task,cached)/('slide_'+rid[:20]+info['extension'])
                                _atomic_image(cache,local,record,data,stop)
                                record.update(status='complete',size=info['size'],sha256=info['sha256'])
                                cache.save();paths.append(local)
                                emit('已读取课件页 {}/{}（{}）'.format(index,len(resources),label))
                                break
                            except (NeedsHuman,Stopped):
                                raise
                            except Exception as exc:
                                record.update(status='failed',error='课件图片读取或写入失败',error_type=type(exc).__name__)
                                cache.save()
                                if attempt==2: raise FileProblem('课件页{}读取失败，已重试2次；未生成不完整PDF'.format(label)) from None
                                emit('课件页读取失败（{}），重试{}/2'.format(type(exc).__name__,attempt+1))
                                if stop.wait(attempt+1):check_stop(stop)
                        if stop.wait(.15):check_stop(stop)
                path.parent.mkdir(parents=True,exist_ok=True)
                for attempt in range(3):
                    temporary=path.parent/('.courseware_'+uuid.uuid4().hex[:8]+'.part')
                    target.resolve(str(temporary.relative_to(target.root)))
                    meta['attempts_last_run']=attempt+1
                    try:
                        if spec is None:
                            conversions=write_pdf(temporary,paths,stop,page_size=LANDSCAPE)
                            pages = len(sequence)
                            valid = validate_pdf(temporary,pages,stop,page_size=LANDSCAPE)
                        else:
                            conversions, checks = write_grid_pdf(temporary,paths,stop,spec)
                            pages = len(checks)
                            valid = (matching_page_groups(checks,pages,len(sequence),spec)
                                     and validate_grid_pdf(temporary,pages,spec,checks,stop))
                            meta['grid_page_checks'] = checks
                        if not valid:
                            raise FileProblem('课件PDF页数、页面或图像验证失败')
                        digest=sha_file(temporary,stop);size=temporary.stat().st_size
                        check_stop(stop)
                        os.replace(str(temporary),str(path))
                        meta.update(status='complete',version=COURSEWARE_VERSION,pages=pages,size=size,sha256=digest,
                                    conversions=conversions,error=None,error_type=None)
                        target.save();work.discard=True
                        for note in conversions:
                            emit('转换记录：'+note)
                        emit('已保存课件PDF，{}张/{}页：{}'.format(len(sequence), pages, path))
                        return dict(meta,resource_state='available',skipped=False)
                    except Stopped: raise
                    except Exception as exc:
                        if attempt==2:
                            reason = str(exc) if isinstance(exc, FileProblem) else '课件PDF生成或保存失败（{}）'.format(type(exc).__name__)
                            raise FileProblem(reason+'，已重试2次') from None
                        emit('课件PDF失败，重试{}/2'.format(attempt+1))
                        if stop.wait(attempt+1):check_stop(stop)
                    finally:
                        if temporary.is_file():temporary.unlink()
        except (NeedsHuman,Stopped) as exc:
            meta.update(status='needs_human' if isinstance(exc,NeedsHuman) else 'stopped',error='等待人工处理或任务已停止',error_type=type(exc).__name__)
            raise
        except Exception as exc:
            reason=str(exc) if isinstance(exc,(FileProblem,PageChanged)) else '课件导出异常（{}）'.format(type(exc).__name__)
            meta.update(status='failed',error=reason,error_type=type(exc).__name__)
            result.update(status='failed',resource_state='error',error=reason,error_type=type(exc).__name__)
            emit('未完成：'+reason)
            return result
        finally:
            target.save()
