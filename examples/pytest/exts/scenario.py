"""Общие шаги: новая «Демо: Реализация товаров», заполненная только действиями движка."""
DOC = 'e1cib/data/Документ._ДемоРеализацияТоваров'
MARK = 'testpilot-e2e'
ORGANIZATION = 'Перспектива ЗАО'


def new_sale(client, partner='Протон', contract='Договор Протон с Перспектива'):
    client.execute_command(command=DOC)
    form = client.find_object(cls='ManagedForm', timeout=30)
    for name, value in (('Организация', ORGANIZATION), ('Партнер', partner), ('Контрагент', partner),
                        ('Договор', contract), ('МестоХранения', 'Розничный склад')):
        form.find_object(name=name).select_value(value=value)
    form.find_object(name='Комментарий').input_text(text=MARK)
    form.find_object(name='ТоварыДобавить').click()
    form.find_object(name='ТоварыНоменклатура').select_value(value='1С:Бухгалтерия 8')
    form.find_object(name='Товары', cls='Table').set_row_values(cells=[
        {'column': 'ТоварыКоличество', 'text': '2'}, {'column': 'ТоварыЦена', 'text': '100'}])
    return form
