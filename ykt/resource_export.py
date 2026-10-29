"""Serial per-lesson scheduling, used only when courseware export is selected."""
from .browser import Stopped, check_stop
from .courseware import export_courseware
from .downloader import download, verify_account
from .quiz_export import export_quizzes


def export_resources(context,page,origin,request,site_dir,account_id,layout,stop,emit,image_done,feature_done,progress):
    result=dict(total=len(request['tasks']),completed=0,success=0,failed=0,status='running',
                downloaded=0,skipped=0,image_failed=0,no_images=0,current_course='—',current_lesson='—')
    verify_account(page,origin,request['owner'],stop,emit)
    try:
        for task in request['tasks']:
            check_stop(stop)
            result.update(current_course=task['course_name'],current_lesson=task['lesson']['name'])
            progress(dict(result))
            successful=True
            def transfer(update):
                current=dict(result)
                for metric in ('downloaded','skipped','image_failed'):current[metric]+=update[metric]
                progress(current)
            if request['options'].get('quiz_images') or request['options'].get('quiz_pdf'):
                if request['options'].get('quiz_pdf'):
                    quiz=export_quizzes(context,page,origin,dict(request,tasks=[task]),site_dir,account_id,layout,
                                        stop,emit,image_done,feature_done,transfer)
                else:
                    quiz=download(context,page,origin,[task],request['directory'],request['owner'],stop,emit,
                                  on_progress=transfer,on_lesson=image_done,layout=layout)
                for metric in ('downloaded','skipped','image_failed','no_images'):result[metric]+=quiz[metric]
                if quiz['status']=='stopped':raise Stopped()
                successful=quiz['failed']==0
            prefix='[课件PDF] {} / {}：'.format(' '.join(task['course_name'].split()),' '.join(task['lesson']['name'].split()))
            courseware=export_courseware(context,page,origin,task,request['directory'],request['owner'],
                                        site_dir,account_id,layout,stop,lambda message:emit(prefix+message))
            feature_done(task,'courseware_pdf',courseware)
            successful=successful and courseware['status'] in ('complete','no_images')
            result['completed']+=1
            result['success' if successful else 'failed']+=1
            progress(dict(result))
        result['status']='partial' if result['failed'] else 'complete'
    except Stopped:
        result['status']='stopped'
        emit('已安全停止，完整产物保留，课件临时图片留待恢复')
    progress(dict(result))
    return result
