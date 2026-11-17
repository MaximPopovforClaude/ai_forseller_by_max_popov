"""Bounded XLSX import with no formula evaluation; preview is non-mutating."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from openpyxl import Workbook, load_workbook
from .balance import validate_payload

HEADERS = {
 'stock': [('code','Код товара'),('name','Название'),('quantity','Количество'),('cost','Себестоимость единицы')],
 'assets': [('code','Код записи'),('name','Название'),('category','Категория'),('amount','Сумма'),('due','Срок погашения'),('note','Примечание')],
 'settlement': [('before_spp','Продано до СПП'),('after_spp','Продано после СПП'),('unaccrued_net','До начисления к получению'),('accrued','Начислено не выплачено'),('note','Источник сверки')],
}
CATEGORIES = {'material':'Материальный актив','intangible':'Нематериальный актив','receivable':'Нам должны',
              'cash':'Деньги','loan':'Основной долг кредита','interest':'Начисленные проценты','payable':'Мы должны'}


def template(kind):
    if kind not in HEADERS: raise ValueError('Неверный шаблон')
    w=Workbook();s=w.active;s.title='Данные';s.append([label for _,label in HEADERS[kind]])
    h=w.create_sheet('Инструкция')
    h.append(['Суммы в рублях. Снимок на дату, не обороты за период. Компания и дата выбираются на сайте.'])
    h.append(['Код — текст; сохраняйте ведущие нули. Формулы не принимаются. Повторные коды запрещены.'])
    h.append(['Склад: полный остаток одного физического склада. FBS, включённый в файл, не прибавлять повторно.'])
    h.append(['Активы: полный реестр компании на дату. Новая версия заменяет показ старой, история сохраняется.'])
    h.append(['Расчёты: суммы до начисления и начисленные должны не пересекаться; пусто = неизвестно, 0 = подтверждённый ноль.'])
    for code,name in CATEGORIES.items(): h.append([code,name])
    s.freeze_panes='A2'
    for col in s.columns: s.column_dimensions[col[0].column_letter].width=28
    b=BytesIO();w.save(b);return b.getvalue()


def parse(raw,kind):
    if kind not in HEADERS: raise ValueError('Неверный вид файла')
    if len(raw)>5*1024*1024: raise ValueError('Файл больше 5 МБ')
    try:
        with ZipFile(BytesIO(raw)) as z:
            if len(z.infolist())>200 or sum(i.file_size for i in z.infolist())>30*1024*1024:
                raise ValueError('Слишком большой распакованный XLSX')
            if any('externallinks/' in i.filename.lower() or 'vbaproject' in i.filename.lower() for i in z.infolist()):
                raise ValueError('Внешние ссылки и макросы не поддерживаются')
        w=load_workbook(BytesIO(raw),read_only=True,data_only=False,keep_links=False)
        try:
            s=w['Данные'] if 'Данные' in w.sheetnames else w.worksheets[0];s.reset_dimensions()
            it=s.iter_rows();head=next(it,None)
            labels=[str(x.value or '').strip().lower() for x in head or []]
            required=HEADERS[kind];cols=[]
            for key,label in required:
                if label.lower() not in labels: raise ValueError(f'Нет столбца «{label}»')
                if labels.count(label.lower()) != 1: raise ValueError(f'Столбец «{label}» повторяется')
                cols.append((key,labels.index(label.lower())))
            out=[]
            for i,row in enumerate(it,2):
                if i>20001: raise ValueError('Не более 20 000 строк')
                if len(row)>50: raise ValueError('Не более 50 столбцов')
                if any(cell.data_type=='f' for cell in row): raise ValueError(f'Строка {i}: замените формулы значениями')
                d={k:row[j].value if j<len(row) else None for k,j in cols}
                if all(v is None or v=='' for v in d.values()): continue
                if kind=='assets':
                    d['category']=next((k for k,v in CATEGORIES.items() if v==d['category']),d['category'])
                    if hasattr(d.get('due'),'date'): d['due']=str(d['due'].date())
                out.append(d)
            return validate_payload(kind,{'rows':out,'exclusive':kind=='settlement'})
        finally:w.close()
    except (BadZipFile,KeyError,StopIteration):
        raise ValueError('Не удалось прочитать XLSX. Используйте шаблон') from None
