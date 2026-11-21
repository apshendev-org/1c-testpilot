"""Намеренная ошибка записи: click отказывает с сообщениями 1С и слепком формы."""
from pathlib import Path

import pytest
from testpilot import ActionError

from scenario import DOC


def test_save_without_partner_fails_with_diagnostics(testpilot):
    testpilot.execute_command(command=DOC)
    form = testpilot.find_object(cls='ManagedForm', timeout=30)
    with pytest.raises(ActionError) as failure:
        form.find_object(name='ФормаЗаписать').click()
    result = failure.value.result
    print(result)
    assert result['messages'] and Path(result['snapshot']).is_file(), result
