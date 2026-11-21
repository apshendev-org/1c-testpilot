"""Намеренная ошибка: проведение без партнёра — click отказывает с сообщениями 1С и слепком формы."""
from pathlib import Path

import pytest
from testpilot import ActionError

from scenario import DOC


def test_post_without_partner_fails_with_diagnostics(testpilot, testpilot_data):
    testpilot.execute_command(command=DOC)
    form = testpilot.find_object(cls='ManagedForm', timeout=30)
    try:
        form.find_object(name='ФормаПровести').click()
    except ActionError as error:
        result = error.result
    else:
        testpilot_data.track_window()
        pytest.fail('проведение без партнёра прошло')
    print(result)
    assert result['messages'] and Path(result['snapshot']).is_file(), result
