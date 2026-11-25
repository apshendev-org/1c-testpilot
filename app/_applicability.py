"""К каким элементам применимо действие: столбец «Применим к типам» docs/TOOLS.md.

APPLIES — типы 1С из документации короткими кодами (TYPES), тест сверяет таблицу с docs/TOOLS.md.
Классы — как `class` в ответах find_objects и последний сегмент ключа. Уточнение вида поля (KINDS)
повторяет проверки, которые уже есть в самих действиях. Таблица — подсказка агенту, а не запрет:
окончательно решает клиент тестирования.
"""
import difflib

# код -> (тип 1С, классы элементов)
TYPES = {
    'F':   ('ТестируемоеПолеФормы', ('EditField',)),
    'B':   ('ТестируемаяКнопкаФормы', ('Button',)),
    'T':   ('ТестируемаяТаблицаФормы', ('Table',)),
    'G':   ('ТестируемаяГруппаФормы', ('Group',)),
    'D':   ('ТестируемаяДекорацияФормы', ('Decoration',)),
    'A':   ('ТестируемоеДополнениеЭлементаФормы', ('Additional',)),
    'M':   ('ТестируемаяФорма', ('ManagedForm',)),
    'W':   ('ТестируемоеОкноКлиентскогоПриложения', ('MainFrame', 'SecondaryFrame', 'HomePage')),
    'CB':  ('ТестируемаяКнопкаКомандногоИнтерфейса', ('CIButton',)),
    'CG':  ('ТестируемаяГруппаКомандногоИнтерфейса', ('Navigation', 'SubSystems', 'SWINOpened')),
    'CI':  ('ТестируемыйКомандныйИнтерфейсОкна', ('CI',)),
    'APP': ('ТестируемоеПриложение', ()),        # действие без элемента
}

APPLIES = {
    'activate': ('CG', 'G', 'D', 'CB', 'B', 'T', 'M', 'A', 'W', 'F', 'CI'),
    'activate_window': ('W',),
    'add_rows': ('T',),
    'answer_dialog': ('W',),
    'begin_edit_current_area': ('F',),
    'calendar_next_month': ('F',),
    'calendar_next_year': ('F',),
    'calendar_previous_month': ('F',),
    'calendar_previous_year': ('F',),
    'can_be_expanded': ('T',),
    'cancel_edit': ('A', 'F'),
    'change_row': ('T',),
    'choose_from_drop_list': ('F',),
    'choose_row': ('T',),
    'choose_user_message': ('W',),
    'clear': ('A', 'F'),
    'clear_file_dialog_result': ('APP',),
    'click': ('G', 'D', 'CB', 'B', 'F'),
    'click_formatted_doc_hyperlink': ('F',),
    'click_formatted_string_hyperlink': ('D', 'F'),
    'click_html_hyperlink': ('F',),
    'click_view_status_item': ('A',),
    'close_drop_list': ('F',),
    'close_user_messages_panel': ('W',),
    'close_window': ('W',),
    'collapse': ('G', 'T'),
    'compare_snapshot': ('M',),
    'connect': ('APP',),
    'copy_row': ('T',),
    'create': ('F',),
    'create_snapshot': ('M',),
    'current_check': ('B',),
    'current_mode_is_edit': ('T', 'F'),
    'current_modified': ('M',),
    'current_opened': ('G',),
    'decrease_value': ('F',),
    'delete_row': ('T',),
    'delete_rows': ('T',),
    'delete_view_status_item': ('A',),
    'deselect_all_rows': ('T',),
    'deselect_row': ('T',),
    'disconnect': ('APP',),
    'drop_list_is_open': ('F',),
    'end_edit_current_area': ('F',),
    'end_edit_row': ('T',),
    'execute_choice_from_choice_list': ('F',),
    'execute_choice_from_list': ('M',),
    'execute_choice_from_menu': ('M', 'F'),
    'execute_command': ('W',),
    'expand': ('G', 'T'),
    'find_default_button': ('M',),
    'find_object': ('CG', 'G', 'D', 'CB', 'B', 'T', 'M', 'A', 'W', 'F', 'APP', 'CI'),
    'find_objects': ('CG', 'G', 'D', 'CB', 'B', 'T', 'M', 'A', 'W', 'F', 'APP', 'CI'),
    'find_rows': ('T',),
    'find_text': ('F',),
    'get_active_window': ('APP',),
    'get_area_text': ('F',),
    'get_cell_text': ('T',),
    'get_child_objects': ('CG', 'G', 'D', 'CB', 'B', 'T', 'M', 'A', 'W', 'F', 'APP', 'CI'),
    'get_choice_list': ('M', 'F'),
    'get_command_bar': ('G', 'D', 'T', 'M', 'A', 'F'),
    'get_command_interface': ('W',),
    'get_context': ('M',),
    'get_context_menu': ('G', 'D', 'T', 'A', 'F'),
    'get_current_area_address': ('F',),
    'get_current_area_field': ('F',),
    'get_current_area_text': ('F',),
    'get_current_element': ('M',),
    'get_current_error': ('APP',),
    'get_current_item': ('T',),
    'get_current_page': ('G',),
    'get_current_row': ('T',),
    'get_data_presentation': ('F',),
    'get_doc_area_horizontal_size': ('F',),
    'get_doc_area_vertical_size': ('F',),
    'get_edit_text': ('A', 'F'),
    'get_formatted_string_hyperlinks': ('D', 'F'),
    'get_html': ('F',),
    'get_linked_window': ('CB',),
    'get_list_settings': ('T',),
    'get_list_settings_fields': ('T',),
    'get_max_action_time': ('APP',),
    'get_parent': ('CG', 'G', 'D', 'CB', 'B', 'T', 'M', 'A', 'F', 'CI'),
    'get_performance': ('APP',),
    'get_selected_rows': ('T',),
    'get_state_presentation': ('F',),
    'get_text': ('F',),
    'get_tooltip': ('G', 'D', 'T', 'A', 'F'),
    'get_user_message_texts': ('W',),
    'get_view_status_item_texts': ('A',),
    'go_one_level_down': ('T',),
    'go_one_level_up': ('T',),
    'goto_date': ('F',),
    'goto_first_row': ('T',),
    'goto_last_row': ('T',),
    'goto_next_element': ('M',),
    'goto_next_item': ('T',),
    'goto_next_row': ('T',),
    'goto_next_window': ('W',),
    'goto_previous_element': ('M',),
    'goto_previous_item': ('T',),
    'goto_previous_row': ('T',),
    'goto_previous_window': ('W',),
    'goto_row': ('T',),
    'goto_start_page': ('W',),
    'goto_value': ('F',),
    'included_in_merged_area': ('F',),
    'increase_value': ('F',),
    'input_html': ('F',),
    'input_text': ('A', 'F'),
    'is_enabled': ('G', 'D', 'B', 'T', 'M', 'A', 'F'),
    'is_expanded': ('T',),
    'is_readonly': ('G', 'D', 'T', 'M', 'A', 'F'),
    'is_visible': ('G', 'D', 'B', 'T', 'A', 'F'),
    'list_snapshots': ('M',),
    'open_drop_list': ('F',),
    'open_field': ('F',),
    'open_user_messages_panel': ('W',),
    'read_document': ('F',),
    'read_fields': ('F',),
    'read_rows': ('T',),
    'record_cancel': ('APP',),
    'record_finish': ('APP',),
    'record_pause': ('APP',),
    'record_resume': ('APP',),
    'record_start': ('APP',),
    'run_scenario': ('APP',),
    'search': ('T',),
    'select_all_rows': ('T',),
    'select_option': ('F',),
    'select_row': ('T',),
    'set_area_text': ('F',),
    'set_cell_text': ('T',),
    'set_check': ('F',),
    'set_current_area': ('F',),
    'set_fields': ('F',),
    'set_file_dialog_result': ('APP',),
    'set_list_settings': ('T',),
    'set_max_action_time': ('APP',),
    'set_order': ('T',),
    'set_row_values': ('T',),
    'start_choosing': ('F',),
    'start_choosing_from_choice_list': ('F',),
    'switch_row_delete_mark': ('T',),
    'table_add_row': ('T',),
    'text_within_area_bounds': ('F',),
    'title_is_shown': ('F',),
    'wait_for_closing': ('M',),
    'wait_for_drop_list_generation': ('F',),
    'wait_for_object_displayed': ('APP',),
    'write_content_to_file': ('F',),
}

_SPREADSHEET = ('set_current_area', 'get_current_area_address', 'get_current_area_text', 'get_area_text',
                'get_current_area_field', 'begin_edit_current_area', 'end_edit_current_area',
                'included_in_merged_area', 'text_within_area_bounds', 'get_doc_area_horizontal_size',
                'get_doc_area_vertical_size', 'set_area_text', 'read_document', 'find_text')
_CALENDAR = ('goto_date', 'calendar_next_month', 'calendar_next_year', 'calendar_previous_month',
             'calendar_previous_year')
# вид поля EditField, который проверяет само действие
KINDS = {**dict.fromkeys(_SPREADSHEET, ('SpreadsheetDocumentField',)),
         **dict.fromkeys(_CALENDAR, ('CalendarField',)),
         'input_html': ('FormattedDocumentField',),
         'get_html': ('FormattedDocumentField', 'HTMLDocumentField')}


def classes(action):
    """Классы элементов действия по порядку TYPES; пусто — действие без элемента или не описано."""
    codes = APPLIES.get(action, ())
    return [cls for code in TYPES if code in codes for cls in TYPES[code][1]]


def line(action):
    """Строка «Applies to» для документации действия или пустая строка."""
    found = classes(action)
    if not found:
        return ''
    kinds = KINDS.get(action)
    text = ', '.join('EditField (%s)' % ', '.join(kinds) if kinds and c == 'EditField' else c for c in found)
    return '\nApplies to: ' + text + '.'


def suggest(action, element_class, available, group_of=None, limit=5):
    """Действия из `available`, применимые к классу элемента: ближайшие по имени, затем той же группы."""
    fit = [a for a in available if a != action and element_class in classes(a)]
    if not fit:
        return []
    ratio = {a: difflib.SequenceMatcher(None, action, a).ratio() for a in fit}
    group = group_of.get(action) if group_of else None
    ranked = sorted(fit, key=lambda a: (-(ratio[a] >= 0.5), -(group is not None and group_of.get(a) == group),
                                        -ratio[a], a))
    return ranked[:limit]
