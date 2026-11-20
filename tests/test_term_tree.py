"""Test semester grouping through the Tk tree with a small historical cache."""
import gc
import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from ykt.gui import CourseApp


class TermTreeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.cleanup_tk)
        self.app = CourseApp(self.root, Path(directory.name))

    def cleanup_tk(self):
        self.root.destroy()
        del self.app, self.root
        gc.collect()

    @staticmethod
    def course(cid, class_name, lesson_ids):
        course = dict(id=cid, name="同名课程", status="complete", archived=cid == '1',
                      lessons=[dict(id=lid, name='课时 '+lid) for lid in lesson_ids])
        if class_name is not None:
            course['class_name'] = class_name
        return course

    def display(self, courses, status='complete'):
        self.app._display_catalog(dict(origin=self.app.origin, status=status,
                                       owner_fingerprint='a'*64, courses=courses), cached=True)

    def test_tree_order_checks_and_retry_selection(self):
        app = self.app
        courses = [self.course('1','2025秋-归档班',['11']), self.course('2','2026秋-班一',['22','21']),
                   self.course('3',None,['31']), self.course('4','2026春-班二',['41']),
                   self.course('5','前缀 2026秋-班三',['51']), self.course('6','2024春-空班',[]),
                   self.course('7','跨期 2025春 / 2025秋',['71'])]
        self.display(courses)
        terms = [app.term_iid(x) for x in ('2026秋','2026春','2025秋','2024春','未分类学期')]
        self.assertEqual(app.tree.get_children(), tuple(terms))
        self.assertEqual([iid for iid in terms if app.tree.item(iid,'open')], terms[:1])
        self.assertEqual(app.tree.get_children(terms[0]), ('course:2','course:5'))
        self.assertEqual(app.tree.get_children('course:2'), ('lesson:2:22','lesson:2:21'))
        self.assertEqual(app.tree.get_children(terms[-1]), ('course:3','course:7'))
        self.assertEqual(app.tree.set('course:2','detail'), '2026秋-班一')

        app.tree.focus(terms[0])
        app._tree_space(None)
        self.assertEqual(app.selection.selected, {('2','22'),('2','21'),('5','51')})
        self.assertEqual(app.tree.set(terms[0],'selected'), '3 / 3')
        app.toggle('lesson:2:21')
        self.assertEqual(app.tree.item(terms[0],'image'), (str(app.images['partial']),))
        app.toggle('course:2')
        self.assertEqual(app.tree.set(terms[0],'selected'), '3 / 3')
        app.toggle(terms[0])
        self.assertFalse(app.selection.selected)
        app.toggle(terms[3])
        self.assertFalse(app.selection.selected)

        app.select_all()
        self.assertEqual([t['course_id'] for t in app.selection.tasks()], ['1','2','2','3','4','5','7'])
        app.clear_selection()
        app.select_unfinished([dict(course_id='1',lesson_id='11'), dict(course_id='3',lesson_id='31')])
        self.assertEqual(app.selection.selected, {('1','11'),('3','31')})
        for opened in (True,False):
            app.expand_all(opened)
            self.assertTrue(all(app.tree.item(iid,'open') == opened for iid,(kind,_) in app.nodes.items()
                                if kind != 'lesson'))
        self.display(courses)
        self.assertFalse(any(app.tree.item(iid,'open') for iid in terms))
        self.assertEqual(app.selection.selected, {('1','11'),('3','31')})

    def test_scan_progress_recomputes_default_latest_and_keeps_manual_expansion(self):
        app = self.app
        older = self.course('1','2025春',['11'])
        newer = self.course('2','2026秋',['21'])
        self.display([older],status='running')
        self.assertTrue(app.tree.item(app.term_iid('2025春'),'open'))
        self.display([older,newer])
        newest, previous = app.tree.get_children()
        self.assertTrue(app.tree.item(newest,'open'))
        self.assertFalse(app.tree.item(previous,'open'))
        app.tree.focus(previous)
        app.tree.item(previous,open=True)
        app.tree.event_generate('<<TreeviewOpen>>')
        self.display([older,newer])
        self.assertTrue(app.tree.item(previous,'open'))
        app._clear_account_view()
        self.display([older,newer])
        self.assertFalse(app.tree.item(previous,'open'))
