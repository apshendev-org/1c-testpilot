"""Ролевой пользователь и два пользователя одной базы."""
import pytest

from scenario import new_sale


@pytest.mark.testpilot(user='Пользователь')
def test_sale_as_role_user(testpilot, testpilot_data):
    form = new_sale(testpilot)
    form.find_object(name='ФормаПровести').click()
    testpilot_data.track_window()


@pytest.mark.testpilot(user='Руководитель')
def test_sale_seen_by_other_user(testpilot, testpilot_data):
    form = new_sale(testpilot)
    form.find_object(name='ФормаПровести').click()
    testpilot_data.track_window()
    url = testpilot.get_active_window()['url']
    number = form.find_object(name='Номер').get_data_presentation()
    other = testpilot.as_user('Пользователь')
    other.execute_command(command=url)
    assert other.find_object(cls='ManagedForm', timeout=30).find_object(name='Номер').get_data_presentation() == number
