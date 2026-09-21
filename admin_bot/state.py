from aiogram.fsm.state import State, StatesGroup


class AdminState(StatesGroup):
    waiting_menu_name = State()    # adding menu: waiting for name
    waiting_menu_text = State()    # adding menu: waiting for display text
    waiting_menu_row = State()     # adding menu: waiting for row
    waiting_edit_text = State()    # editing text: waiting for new text
    waiting_dup_name = State()     # duplicate: waiting for new name
    waiting_btn_text = State()     # add button: waiting for text
    waiting_btn_row = State()      # add button: waiting for row
    waiting_btn_type = State()       # add button: waiting for type (submenu/custom)
    waiting_btn_custom_desc = State()  # add button: waiting for custom description
    waiting_swap_second = State()  # swap: waiting for second button
    waiting_materials = State()      # adding material: waiting for forwarded messages
    waiting_material_desc = State()  # adding material: waiting for description
    waiting_text_message = State()   # adding material: waiting for text message content


class BroadcastStates(StatesGroup):
    collecting_messages = State()

class BackupStates(StatesGroup):
    waiting_restore_file = State()


class AdminManageStates(StatesGroup):
    waiting_admin_id = State()
    waiting_admin_scope = State()
