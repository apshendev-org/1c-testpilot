import os
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

import _admin_client as A  # noqa: E402
import _code_execution as E  # noqa: E402
import _runtime as R  # noqa: E402

PROFILES = """profiles:
  ib: {base: 'srv\\dev-ib', server: true, user: Администратор}
  admin2: {base: 'srv\\dev-ib', server: true, user: Админ2}
  'роль:kfk_user': {base: 'srv\\dev-ib', server: true, user: kfk_user}
  other: {base: 'srv\\other-ib', server: true, user: kfk_user}
"""


@pytest.fixture(autouse=True)
def profiles(tmp_path, monkeypatch):
    path = tmp_path / 'profiles.yaml'
    path.write_text(PROFILES, encoding='utf8')
    monkeypatch.setenv('TC1C_PROFILES_FILE', str(path))


def runtime(profile, **caller):
    """Runtime stub of the current connection: its profile and the calling Runtime's admin settings."""
    return SimpleNamespace(_state={'profile': profile},
                           _execution=SimpleNamespace(get=lambda: SimpleNamespace(**caller) if caller else None))


@pytest.mark.parametrize('own, caller, expected', [
    ('роль:kfk_user', {}, 'ib'),
    ('роль:kfk_user', {'admin_profile': 'admin2'}, 'admin2'),
    ('роль:kfk_user', {'admin_profile': 'роль:kfk_user'}, 'ib'),   # назначен сам клиент — берётся ib
])
def test_admin_profile_of_the_same_base(own, caller, expected):
    assert A.profile(runtime(own, **caller)) == expected


@pytest.mark.parametrize('own', ['other', 'ib', None])
def test_no_admin_profile_names_the_needed_one(own):
    with pytest.raises(E.Failure) as error:
        A.profile(runtime(own))
    assert error.value.result['code'] == 'admin_client_unavailable' and error.value.result['profile'] == 'ib'


def test_caller_resolver_supplies_admin_client():
    admin = SimpleNamespace(call=lambda action, check, **kw: dict(ok=True, rows=[kw['query']]))
    S = runtime('роль:kfk_user', admin_profile='ib', admin=lambda name: admin)
    result = A.call(S, 'execute_query', dict(query='ВЫБРАТЬ 1', parameters=None))
    assert result == dict(ok=True, rows=['ВЫБРАТЬ 1'], delegated_to='ib')


def missing_helper():
    raise E.Failure('helper_not_ready', 'no processing')


def test_server_code_without_helper_goes_to_admin(monkeypatch):
    calls = []
    monkeypatch.setattr(R._admin_client, 'call', lambda S, action, arguments: calls.append((action, arguments)) or {'ok': True})
    assert R._with_admin('execute_code', dict(code='Результат = 1;', context='server'), missing_helper) == {'ok': True}
    assert calls == [('execute_code', dict(code='Результат = 1;', context='server'))]


def test_client_code_without_helper_is_refused(monkeypatch):
    monkeypatch.setattr(R._admin_client, 'call', lambda *a: pytest.fail('client code must not be delegated'))
    with pytest.raises(E.Failure) as error:
        R._with_admin('execute_code', dict(code='Результат = 1;', context='client'), missing_helper)
    assert error.value.result['code'] == 'client_code_unavailable'


def test_other_failures_are_not_delegated(monkeypatch):
    def broken():
        raise E.Failure('invalid_code', 'bad')
    with pytest.raises(E.Failure) as error:
        R._with_admin('execute_code', dict(code='', context='server'), broken)
    assert error.value.result['code'] == 'invalid_code'


def test_forbidden_external_processing_is_closed_at_startup():
    box = 'SecondaryFrame[b]'
    text = 'Текущему пользователю запрещен запуск внешних обработок.'
    objects = [dict(key=box + '.ManagedForm[m]', form_name='MessageBox', **{'class': 'ManagedForm'}),
               dict(key=box + '.ManagedForm[m].Decoration[Message]', name='Message', title=text, **{'class': 'Decoration'}),
               dict(key=box + '.ManagedForm[m].Button[Button0]', name='Button0', title='ОК', handle='h', **{'class': 'Button'})]
    clicked = []
    S = SimpleNamespace(_APPLICATION_ROOT=None, _search_objects=lambda c, root: objects,
                        _window=lambda c: dict(key=box), tc_click=lambda **kw: clicked.append(kw) or dict(ok=True))
    with pytest.raises(E.Failure) as error:
        E.prepare(S, SimpleNamespace(), 'Testpilot.epf', time.monotonic() + 1)
    assert error.value.result['code'] == 'helper_forbidden' and error.value.result['execution_reason'] == text
    assert [c['key'] for c in clicked] == [box + '.ManagedForm[m].Button[Button0]']


def _bsp_warning(clicks):
    """Стартовая форма БСП ПредупреждениеБезопасности: ответы кнопок — из clicks (имя -> результат tc_click)."""
    box = 'SecondaryFrame[w]'
    form = box + '.ManagedForm[f]'
    objects = [dict(key=form, form_name='ОбщаяФорма.ПредупреждениеБезопасности', **{'class': 'ManagedForm'})]
    objects += [dict(key=f'{form}.Button[{name}]', name=name, handle=name, **{'class': 'Button'})
                for name in ('ЗапретитьОткрытиеВнешнихОтчетовИОбработок', 'НеЗапрещать', 'ЯОзнакомлен')]
    clicked = []

    def click(**kw):
        name = kw['key'].rsplit('[', 1)[1][:-1]
        clicked.append(name)
        return clicks.get(name, dict(ok=True))

    S = SimpleNamespace(_APPLICATION_ROOT=None, _search_objects=lambda c, root: objects,
                        _window=lambda c: dict(key=box), tc_click=click)
    return S, clicked


def test_bsp_security_warning_acknowledged_at_startup():
    S, clicked = _bsp_warning({})
    assert E.discover(S, SimpleNamespace(), startup=True) == (None, [])
    assert clicked == ['ЯОзнакомлен']


def test_bsp_security_warning_after_update_keeps_external_processing():
    # Страница «После обновления»: ЯОзнакомлен на скрытой странице, кнопку запрета не нажимаем.
    S, clicked = _bsp_warning({'ЯОзнакомлен': dict(ok=True, target_hidden=True)})
    assert E.discover(S, SimpleNamespace(), startup=True) == (None, [])
    assert clicked == ['ЯОзнакомлен', 'НеЗапрещать']


def test_bsp_security_warning_without_answer_blocks_startup():
    S, clicked = _bsp_warning({'ЯОзнакомлен': dict(ok=False), 'НеЗапрещать': dict(ok=True, target_hidden=True)})
    with pytest.raises(E.Failure) as error:
        E.discover(S, SimpleNamespace(), startup=True)
    assert error.value.result['code'] == 'helper_startup_blocked'
    assert error.value.result['dialog'] == 'ПредупреждениеБезопасности'
    assert 'ЗапретитьОткрытиеВнешнихОтчетовИОбработок' not in clicked
