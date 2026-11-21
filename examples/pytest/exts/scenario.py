"""Общие шаги: новая «Демо: Реализация товаров», заполненная только действиями движка."""
DOC = 'e1cib/data/Документ._ДемоРеализацияТоваров'
MARK = 'testpilot-e2e'
HEADER = (('Организация', 'Ромашка ОАО'), ('Партнер', 'Протон'), ('Контрагент', 'Протон'),
          ('МестоХранения', 'Розничный склад'))


def new_sale(client, partner='Протон'):
    client.execute_command(command=DOC)
    form = client.find_object(cls='ManagedForm', timeout=30)
    for name, value in HEADER:
        form.find_object(name=name).select_value(value=partner if name in ('Партнер', 'Контрагент') else value)
    form.find_object(name='Комментарий').input_text(text=MARK)
    form.find_object(name='ТоварыДобавить').click()
    form.find_object(name='ТоварыНоменклатура').select_value(value='1С:Бухгалтерия 8')
    form.find_object(name='Товары', cls='Table').set_row_values(cells=[{'column': 'ТоварыКоличество', 'text': '2'}])
    return form
