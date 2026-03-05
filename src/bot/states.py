from aiogram.fsm.state import State, StatesGroup


class RequestAccessState(StatesGroup):
    waiting_subject = State()
    waiting_message = State()


class UploadNotebookState(StatesGroup):
    waiting_student = State()
    waiting_file = State()


class StudentFlowState(StatesGroup):
    waiting_mode = State()
    waiting_difficulty = State()
