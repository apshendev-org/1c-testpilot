"""Состав элементов форм обработки Testpilot — из исходников onec/Testpilot/src/Testpilot/Forms/<Форма>/Ext/Form.xml
(изменение helper-request-form, задачи 2.1–2.3): что клиент тестирования перечисляет в окнах Helper и Request.

В записях спайка testpilot-helper-restore форма Request — копия разметки Helper (поле ClientRequest), а кнопка
Helper зовётся RunServer; состава новой обработки нет ни в одной записи, поэтому имена элементов тесты берут
из разметки, а ключи окон, ответы протокола и последовательность активных окон — из записи.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

FORMS = Path(__file__).resolve().parents[1] / 'onec' / 'Testpilot' / 'src' / 'Testpilot' / 'Forms'
NS = '{http://v8.1c.ru/8.3/xcf/logform}'
# Элемент разметки → (class, type) в ответе find_objects: записи slow-start.jsonl (InputField, Button),
# 05-protocol-only.jsonl (FormattedDocumentField).
KINDS = {'InputField': ('EditField', 'InputField'),
         'FormattedDocumentField': ('EditField', 'FormattedDocumentField'),
         'Button': ('Button', 'UsualButton')}


def items(form):
    """[(имя, class, type)] дочерних элементов формы — по порядку разметки."""
    root = ET.parse(FORMS / form / 'Ext' / 'Form.xml').getroot()
    out = []
    for item in root.find(NS + 'ChildItems'):
        cls, typ = KINDS[item.tag[len(NS):]]
        out.append((item.get('name'), cls, item.findtext(NS + 'Type') or typ))
    return out


def commands(form):
    """Имена команд формы: кнопка и команда с одним именем (Form.Command.<имя>)."""
    root = ET.parse(FORMS / form / 'Ext' / 'Form.xml').getroot()
    return [command.get('name') for command in root.find(NS + 'Commands')]


def objects(window_key, form_guid, form_name, title, form, handles=None):
    """Объекты окна формы, как их перечисляет find_objects: окно, форма, её элементы."""
    handles = handles or {}
    form_key = f'{window_key}.ManagedForm[{form_guid}]'
    out = [dict(key=window_key, name=form_guid, handle=handles.get('', 'w'), **{'class': 'SecondaryFrame'},
                type=None, title=title, form_name=None),
           dict(key=form_key, name=form_guid, handle=handles.get('', 'f'), **{'class': 'ManagedForm'},
                type=None, title=title, form_name=form_name)]
    for name, cls, typ in items(form):
        out.append(dict(key=f'{form_key}.{cls}[{name}]', name=name, handle=handles.get(name, name),
                        **{'class': cls}, type=typ, title=name, form_name=None))
    return out
