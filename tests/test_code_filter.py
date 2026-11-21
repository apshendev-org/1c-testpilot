import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _code_execution as ce  # noqa: E402


def refused(code):
    with pytest.raises(ce.Failure) as caught:
        ce.validate_code(code)
    return caught.value.result


@pytest.mark.parametrize('code', [
    'Результат = Новый Запрос("ВЫБРАТЬ 1 КАК Х").Выполнить().Выгрузить().Количество();',
    'Выполнить("Результат = 42;");',
    'Результат = Вычислить("42");',
    'Execute("Result = 42;"); Result = Eval("42");',
    'Объект.Записать(); Объект.Удалить();',
    'УстановитьПривилегированныйРежим(Истина); КомандаСистемы("id");',
])
def test_identifiers_are_not_filtered(code):
    ce.validate_code(code)


@pytest.mark.parametrize('name', ['TC1C_CODE_FORBIDDEN_WORDS', 'TC1C_CODE_ALLOWED_WORDS'])
def test_former_word_settings_are_ignored(monkeypatch, name):
    monkeypatch.setenv(name, 'Сообщить')
    monkeypatch.setattr(ce, 'SETTINGS', ce.settings())
    ce.validate_code('Сообщить("х");')


@pytest.mark.parametrize('code', ['', '   \n\t', None, 42])
def test_empty_or_non_text_code_is_rejected(code):
    assert refused(code)['code'] == 'invalid_code'


@pytest.mark.parametrize('code', [
    'Х = "abc;',
    'С = "начало\nВыполнить("x");',
    'С = "начало\n|продолжение',
])
def test_unterminated_string_is_rejected(code):
    assert refused(code)['code'] == 'invalid_code'


@pytest.mark.parametrize('code', [
    'С = "начало\n// "\n|конец";',
    'С = "начало\n\n   // комментарий\n\t|""в кавычках""\n|конец";',
    'С = "начало\r\n// "\r\n|конец";',
    '// комментарий с "кавычкой\rХ = 1;',
])
def test_multiline_strings_and_comments_are_accepted(code):
    ce.validate_code(code)


@pytest.mark.parametrize('query, prepared', [
    ('ВЫБРАТЬ\n\t"строка\nна двух строках" КАК Поле;\nВЫБРАТЬ 2',
     'ВЫБРАТЬ РАЗРЕШЕННЫЕ\n\t"строка\nна двух строках" КАК Поле;\nВЫБРАТЬ РАЗРЕШЕННЫЕ 2'),
    ('SELECT "a;\r\n// b" AS F // SELECT\r\n;SELECT ALLOWED 1',
     'SELECT ALLOWED "a;\r\n// b" AS F // SELECT\r\n;SELECT ALLOWED 1'),
])
def test_query_strings_keep_their_own_rules(query, prepared):
    assert ce.prepare_query(query) == prepared
