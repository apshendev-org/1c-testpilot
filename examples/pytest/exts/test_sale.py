"""Реализация на демо-данных: заполнить, провести; после теста документ удаляется в режиме загрузки."""
from scenario import new_sale


def test_sale(testpilot, testpilot_data):
    form = new_sale(testpilot)
    form.find_object(name='ФормаПровести').click()
    testpilot_data.track_window()
