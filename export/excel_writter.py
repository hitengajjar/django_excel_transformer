import logging
import os

import openpyxl
from openpyxl.styles import Alignment, Protection
from openpyxl.utils import quote_sheetname
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.protection import SheetProtection
from openpyxl.worksheet.table import TableStyleInfo
from openpyxl.cell import Cell

from .excel_format import TableFormat
from box import Box


class XlsWriter(object):
    def __init__(self, filename, overwrite=False):
        if os.path.isfile(filename) and overwrite is False:
            raise FileExistsError(f'[{filename}] file already exists without overwrite flag')
        self._filename = filename
        self._wb = openpyxl.Workbook()
        self._wb.save(filename)  # Can raise PermissionError
        self._sheet_pos = Box(default_box=True)  # maintain sheet position

    def final(self):
        # We will rearrange the sheets as per their position.
        for nm, pos in self._sheet_pos.items():
            sheet = self._wb[nm]
            if pos != -1:
                self._wb.move_sheet(sheet, pos - self._wb.index(sheet))
            else:
                self._wb.move_sheet(sheet, len(self._sheet_pos))

        self._wb.save(self._filename)

    def _get_sheet_by_name(self, ws_name: str, read: bool = False, ws_details: TableFormat = None):
        """
        Get the sheet and create if read = False and sheet doesn't exist.
        :param ws_name:
        :param read:
        :param ws_details:
        :return:
        """
        self._sheet_pos[ws_name] = ws_details.sheet_position

        try:
            sheet = self._wb[ws_name]
            self._wb.remove_sheet(sheet)
        except KeyError as e:
            if read:
                raise e
            else:
                try:
                    sheet = self._wb['Sheet']  # default sheet
                    sheet.title = ws_name
                    return sheet
                except KeyError:
                    pass

        sheet = self._wb.create_sheet(title=ws_name,
                                      index=ws_details.sheet_position - 1 if ws_details.sheet_position != -1 else -1)
        if ws_details.formatters.sheet_props is not None:
            sheet.sheet_properties = ws_details.formatters.sheet_props

        return sheet

    def update_sheet(self, sheet_nm, columns, data, tf):
        """
        Create or Update excel sheet with db data and cf.
        :param sheet_nm: sheet name
        :param columns: column names
        :param data: Database data that needs to be exported
        :param tf: Table cf. Can be None
        :return:
        """
        logging.debug(f'Creating/Updating name [{sheet_nm}]')
        if not columns or not data:
            logging.error(f'[{"columns" if not columns else "data"}] required but received None')

        sheet = self._get_sheet_by_name(ws_name=sheet_nm, read=False, ws_details=tf)
        col_lock = False
        sheet.append(columns)
        if len(data) <= 0:
            logging.error(f'No values to insert for [{sheet_nm}]')
            sheet["$1$1"].comment = 'No data available for insert'
        else:
            for d in data:
                sheet.append(d)
            for col in columns:
                cf = tf.get_column(col, default=True)

                sheet.column_dimensions[cf.column_number].width = cf.formatters.width
                if cf.formatters.comment:
                    sheet[f'${cf.column_number}$1'].comment = cf.formatters.comment
                cr = cf.formatters.get('reference', None)
                if cr and cf.formatters.get('dv', True):
                    dv = DataValidation(type="list",
                                        formula1="{0}!{1}:{2}".format(quote_sheetname(cr.sheet_name),
                                                                      cr.startcell,
                                                                      cr.endcell))
                    dv.add('{0}2:{0}{1}'.format(cf.column_number, len(data) + 1))
                    sheet.add_data_validation(dv)
                if tf.formatters.alignment.wrapText is True:
                    for cell in sheet[cf.column_number]:
                        cell.alignment = Alignment(wrapText=True)
                        if cf.formatters.locked or tf.formatters.locked:
                            col_lock = True
                            cell.protection = Protection(locked=True)
                        else:
                            cell.protection = Protection(locked=False)

            # Other Worksheet level settings
            sheet.alignment = tf.formatters.alignment
            sheet.freeze_panes = tf.formatters.freeze_panes
            sheet.add_table(openpyxl.worksheet.table.Table(ref="%s" % sheet.dimensions,
                                                           displayName=sheet_nm.replace(" ", ""),
                                                           tableStyleInfo=tf.formatters.table_style_info))
            if tf.formatters.locked:
                sheet.protection.sheet = True
            elif col_lock:
                sheet.protection = SheetProtection(sheet=True, selectLockedCells=False,
                                                   selectUnlockedCells=False, objects=True, scenarios=True,
                                                   formatCells=True, formatRows=True, formatColumns=True,
                                                   insertColumns=True, insertRows=True, insertHyperlinks=True,
                                                   deleteColumns=True, deleteRows=True, sort=True, autoFilter=True,
                                                   pivotTables=True,
                                                   password=None)

        self._wb.save(self._filename)
        return
