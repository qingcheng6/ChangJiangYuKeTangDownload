"""Course/lesson selection independent of Tk and browser threads."""

from typing import Any, Dict, List, Tuple

LessonKey = Tuple[str, str]


class CourseSelection:
    def __init__(self):
        self.courses = []
        self._desired = set()
        self.owner = None
        self._keys = {}

    def replace(self, result: Dict[str, Any]) -> None:
        courses = result["courses"]
        keys = {}
        for course in courses:
            course_id = str(course["id"])
            if course_id in keys:
                raise ValueError("课程标识重复")
            lesson_keys = [(course_id, str(row["id"])) for row in course["lessons"]]
            if len(set(lesson_keys)) != len(lesson_keys):
                raise ValueError("课时标识重复")
            keys[course_id] = lesson_keys
        owner = result.get("owner_fingerprint")
        if self.owner != owner:
            self._desired.clear()
        if result.get("status") == "complete":
            self._desired.intersection_update(key for values in keys.values() for key in values)
        self.owner = owner
        self.courses = courses
        self._keys = keys

    @property
    def selected(self):
        available = {key for values in self._keys.values() for key in values}
        return self._desired & available

    def course_state(self, course_id: str) -> str:
        keys = self._keys[course_id]
        count = sum(key in self.selected for key in keys)
        if count == 0:
            return "unchecked"
        return "checked" if count == len(keys) else "partial"

    def toggle_course(self, course_id: str) -> None:
        self.toggle_courses((course_id,))

    def toggle_courses(self, course_ids) -> None:
        keys = {key for course_id in course_ids for key in self._keys[course_id]}
        if keys <= self._desired:
            self._desired.difference_update(keys)
        else:
            self._desired.update(keys)

    def toggle_lesson(self, key: LessonKey) -> None:
        if key not in self._keys.get(key[0], []):
            raise ValueError("课时不在当前目录中")
        if key in self.selected:
            self._desired.remove(key)
        else:
            self._desired.add(key)

    def select_all(self) -> None:
        self._desired = {key for values in self._keys.values() for key in values}

    def clear(self) -> None:
        self._desired.clear()

    def tasks(self) -> List[Dict[str, Any]]:
        """Return selected records in their original display order for stage 3."""
        selected = self.selected
        return [dict(course_id=str(course["id"]), course_name=course["name"],
                     class_name=course.get("class_name", ""), lesson=dict(lesson))
                for course in self.courses for lesson in course["lessons"]
                if (str(course["id"]), str(lesson["id"])) in selected]
