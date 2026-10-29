"""Selectors verified against user-supplied saved DOM; live status in PROJECT_STATE.

Do not add speculative fallback selectors. A changed page must fail visibly.
"""

INDEX_PATH = "/v2/web/index"
STUDENT_TAB_NAME = "我听的课"
COURSE_PANEL = "#pane-student"
COURSE_CARD = ".lesson-cardS"
COURSE_NAME = "h1"
COURSE_CLASS = ".className"
COURSE_TEACHER = ".teacherName"
LOG_PANEL = "#pane-log"
LOG_LIST = ".logs-list:visible"
LOG_DAY = ".studentCard"
LOG_DATE = ".date-box"
LOG_ACTIVITY = ".activity-box"
LOG_TIME = ".time"
LOG_TITLE = ".activity-info h2"
CLASSROOM_ICON = 'use[*|href="#icon-ketang"]'

# Live verified 2026-10-28: IndexView / StudentLogView, read-only Vue 2 data.
INDEX_VIEW = ".index__view"
LOG_VIEW = ".studentLog__view"
SCROLLER = ".viewContainer"
ARCHIVE_DIALOG = ".archiveDialog"
ARCHIVE_CARD = ".archiveCardS"
ARCHIVE_API_PATH = "/v2/api/web/classroom_archive"
COURSE_API_PATH = "/v2/api/web/courses/list"
STUDENT_IDENTITY = "2"  # Observed query identity=2 on the actual student catalog.
# Verified by normal card navigation and direct archived-course navigation.
COURSE_PATH = "/v2/web/studentLog/{classroom_id}"

LOGIN_READY = """() => {
 const e=document.querySelector('#tab-student');
 return !!e && e.getAttribute('role')==='tab' &&
   !!document.querySelector('.index__view') && e.getClientRects().length>0;
}"""

INDEX_READY = """() => {
 const v=document.querySelector('.index__view')?.__vue__;
 return v?.$options.name==='IndexView' && v.tab2Request===true &&
 v.isLoading===false && Array.isArray(v.originalTableData2);
}"""

INDEX_DATA = """e => {
 const v=e.__vue__;
 if(v?.$options.name!=='IndexView' || !Array.isArray(v.originalTableData2))
   throw Error('IndexView schema changed');
 return {account:String(v.user_id), courses:v.originalTableData2.map(x=>({
   id:String(x.classroom_id), name:x.course.name, class_name:x.name,
   teacher:x.teacher?.name || '', archived:false
 }))};
}"""

LOG_READY = """expected => {
 const v=document.querySelector('.studentLog__view')?.__vue__;
 return v?.$options.name==='StudentLogView' && String(v.classroomId)===expected &&
 v.loaded===true && v.isLoading===false && Array.isArray(v.sourceData) &&
 typeof v.hasMore==='boolean';
}"""

LOG_DATA = """e => {
 const v=e.__vue__;
 if(v?.$options.name!=='StudentLogView' || !Array.isArray(v.sourceData) ||
    typeof v.hasMore!=='boolean') throw Error('StudentLogView schema changed');
 return {classroom_id:String(v.classroomId), page:v.page, has_more:v.hasMore,
   loaded:v.loaded, loading:v.isLoading, lessons:v.sourceData.filter(x=>x.type===14)
   .map(x=>({id:String(x.id), courseware_id:String(x.courseware_id),
      name:x.title.trim(), created_at:x.create_time,
      is_finished:typeof x.is_finished==='boolean'?x.is_finished:null}))};
}"""

SCROLL_END = """e => {
 e.scrollTop=0;
 e.scrollTop=e.scrollHeight;
 // Short lists may fit the viewport. Trigger the same observed scroll listener.
 e.dispatchEvent(new Event('scroll'));
}"""

LOG_ADVANCED = """old => {
 const v=document.querySelector('.studentLog__view')?.__vue__;
 return v && v.loaded && !v.isLoading && Array.isArray(v.sourceData) &&
 (!v.hasMore || (v.page>old.page && v.sourceData.length>old.count));
}"""

COURSE_RENDERED = """expected => {
 const v=document.querySelector('.index__view')?.__vue__;
 return v && !v.isLoading && v.originalTableData2?.length===expected &&
   document.querySelectorAll('#pane-student .lesson-cardS').length===expected;
}"""

# Stage 3: verified in the real platform report on 2026-10-29. The iframe is
# owned by Yuketang; this app does not create/embed a page or bypass its access.
REPORT_PATH = "/v2/web/student-lesson-report/{course_id}/{courseware_id}/{lesson_id}"
REPORT_IFRAME = "iframe.lesson-report-mobile"
REPORT_VIEW = ".courseware-cmp-wrap"
QUIZ_TABS = ".tab-wrap"
QUIZ_TAB_NAME = "习题"
QUIZ_ITEMS = ".slides-list .slide-item"
QUIZ_IMAGE_REGION = ".slide-img"
REPORT_API_PREFIX = "/api/v3/classroom-report/student/"
REPORT_API_NAMES = ("review", "detail", "lesson-info")

REPORT_STATE = """e => {
 const s=e.__vue__?._setupState;
 if(!s) return null;
 const val=x=>x?.__v_isRef?x.value:x;
 const info=val(s.lessonSummaryInfo), all=val(s.lessonTimelineSlides), shown=val(s.showSlides);
 if(!info || !Array.isArray(all) || !Array.isArray(shown)) return null;
 return {lesson_id:String(info.lessonId), course_id:String(info.classroomId),
  all:all.length, shown:shown.length, selected:val(s.lessonSelectTab),
  sent:val(s.isSentProblem), has_problem:val(s.lessonStats)?.problemStatistics?.hasProblem,
  slides:shown.map(x=>({slide_id:String(x.id),page:x.index,dt:x.dt,
      sent:x.sendProblem,has_problem:x.hasProblem,cover:x.cover}))};
}"""

# Generic image attributes are examined only inside the verified quiz image
# region. No avatar, report summary, ordinary-slide tab or lesson content frame
# outside that region is used. URLs stay in memory and are never logged.
QUIZ_RESOURCE_DATA = """e => {
 const region=e.querySelector('.slide-img');
 if(!region) return {resources:[],unsupported:['习题图片区域缺失']};
 const resources=[], unsupported=[];
 const abs=u=>{try{return new URL(u,document.baseURI).href}catch{return null}};
 for(const img of region.querySelectorAll('img')) {
   const candidates=[];
   for(const attr of ['data-original','data-original-src','data-full-src','data-src']) {
     const value=img.getAttribute(attr); if(value)candidates.push(abs(value));
   }
   const srcset=img.getAttribute('srcset')||img.getAttribute('data-srcset');
   if(srcset) {
     const entries=srcset.split(',').map(part=>{
       const m=part.trim().match(/^(\\S+)\\s+([\\d.]+)(w|x)$/);
       return m?{url:abs(m[1]),size:Number(m[2])}:null;
     }).filter(Boolean).sort((a,b)=>b.size-a.size);
     candidates.push(...entries.map(x=>x.url));
   }
   if(img.currentSrc)candidates.push(abs(img.currentSrc));
   if(img.getAttribute('src'))candidates.push(abs(img.getAttribute('src')));
   resources.push({candidates:[...new Set(candidates.filter(Boolean))]});
 }
 for(const n of [region,...region.querySelectorAll('*')]) {
   const bg=getComputedStyle(n).backgroundImage;
   for(const match of bg.matchAll(/url\\(["']?([^"')]+)["']?\\)/g)) {
     const url=abs(match[1]);if(url)resources.push({candidates:[url]});
   }
 }
 if(region.querySelector('canvas'))unsupported.push('Canvas 渲染未验证，未导出截图');
 if(region.querySelector('svg'))unsupported.push('内联 SVG 渲染未验证，未转换图片');
 return {resources,unsupported};
}"""
