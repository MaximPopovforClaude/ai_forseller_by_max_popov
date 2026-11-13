"""Synthetic XLSX/ZIP and API upload tests; never load a real shop file."""
import stometric.web
import asyncio
import io
import json
import unittest
import zipfile
from unittest.mock import AsyncMock, Mock, patch
from openpyxl import Workbook
from fastapi import HTTPException
from stometric import promo, api_manager


def xlsx(headers=None, rows=None):
    wb = Workbook()
    wb.active.append(headers or ['Артикул WB', 'Плановая цена для акции', 'Участвует'])
    for row in rows or [[77, 1234.50, 'Да']]: wb.active.append(row)
    stream = io.BytesIO(); wb.save(stream); wb.close()
    return stream.getvalue()


class PromoImport(unittest.TestCase):
    def test_standard_and_normalized_headers(self):
        expected = [{'nm_id':77, 'price':1234.5, 'in_action':True}]
        self.assertEqual(promo.parse_file(xlsx(), 'offer.xlsx'), expected)
        self.assertEqual(promo.parse_file(xlsx([' Артикул\nWB ', 'Плановая\u00a0цена\nдля акции', 'Товар уже участвует в акции'],
                                              [[77, '1\u202f234,50 ₽', 'Да']]), 'offer.xlsx'), expected)

    def test_explicit_wb_id_precedes_seller_article(self):
        rows = promo.parse_file(xlsx(['Артикул', 'Артикул WB', 'Цена для участия'], [[999,77,100]]), 'offer.xlsx')
        self.assertEqual(rows[0]['nm_id'],77)

    def test_archive_skips_macos_metadata(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('__MACOSX/._offer.xlsx', b'not a workbook')
            z.writestr('folder/offer.xlsx',xlsx())
        self.assertEqual(promo.parse_file(stream.getvalue(),'offer.ZIP')[0]['price'],1234.5)

    def test_invalid_archives_and_workbooks_are_validation_errors(self):
        for raw,name in [(b'PKbroken','offer.zip'),(b'plain','offer.zip'),(b'plain','offer.xlsx')]:
            with self.subTest(name=name,raw=raw), self.assertRaises(promo.PromoError): promo.parse_file(raw,name)
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('README.txt','no workbook')
        with self.assertRaisesRegex(promo.PromoError,'нет файла'):promo.parse_file(stream.getvalue(),'offer.zip')

    def test_nonfinite_and_fractional_identifiers_are_not_truncated(self):
        rows=promo.parse_file(xlsx(rows=[['NaN',100,'Да'],['Infinity',100,'Да'],[1.5,100,'Да'],[-1,100,'Да'],[77,'NaN','Нет']]),'offer.xlsx')
        self.assertEqual(rows,[{'nm_id':77,'price':None,'in_action':False}])
        json.dumps(rows,allow_nan=False)

    def test_streaming_failure_closes_workbook(self):
        wb=Mock();wb.worksheets=[Mock()];wb.worksheets[0].iter_rows.side_effect=ValueError('damaged stream')
        with patch.object(promo,'open_xlsx',return_value=wb), self.assertRaises(promo.PromoError):promo.parse_file(b'xlsx','offer.xlsx')
        wb.close.assert_called_once()

    def test_upload_api_validation_does_not_save(self):
        for raw,title,filename in [(xlsx(),' ','offer.xlsx'),(b'PKbroken','Акция','offer.zip')]:
            c=Mock();req=Mock();req.body=AsyncMock(return_value=raw)
            with patch.object(api_manager,'_role',return_value={'workspace_id':4}), self.assertRaises(HTTPException) as err:
                asyncio.run(api_manager.promo_upload(7,req,filename,title,u={'id':2},c=c))
            self.assertEqual(err.exception.status_code,400);c.execute.assert_not_called();c.commit.assert_not_called()

    def test_upload_api_saves_json_and_workspace_audit(self):
        c=Mock();c.execute.return_value.fetchone.return_value={'id':8}
        req=Mock();req.body=AsyncMock(return_value=xlsx())
        with patch.object(api_manager,'_role',return_value={'workspace_id':4}) as role,patch.object(api_manager,'_audit') as audit:
            result=asyncio.run(api_manager.promo_upload(7,req,'offer.xlsx',' Акция ',u={'id':2},c=c))
        role.assert_called_once_with(c,{'id':2},7,'editor')
        args=c.execute.call_args.args[1]
        self.assertEqual((args[0],args[1],args[3],args[4]),(7,'Акция','offer.xlsx',2))
        self.assertEqual(json.loads(args[2])[0]['nm_id'],77)
        self.assertEqual(audit.call_args.args[2:4],(4,'promo/upload'))
        c.commit.assert_called_once();self.assertEqual(result,{'ok':True,'id':8,'items':1})

    def test_permission_checked_before_reading_file(self):
        req=Mock();req.body=AsyncMock()
        with patch.object(api_manager,'_role',side_effect=HTTPException(403,'denied')), self.assertRaises(HTTPException):
            asyncio.run(api_manager.promo_upload(7,req,'offer.xlsx','Акция',u={'id':2},c=Mock()))
        req.body.assert_not_called()


if __name__ == '__main__': unittest.main()
