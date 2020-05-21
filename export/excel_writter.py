import logging
import os
import openpyxl
from box import Box
from openpyxl.styles import Alignment
from openpyxl.utils import quote_sheetname
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet
from pyexcel_xlsx import save_data, get_data
from openpyxl.comments import Comment

# from panopticum.models import User
from .excel_format import ColFormat, TableFormat


class XlsWriter(object):
    def __init__(self, filename, overwrite=False):
        if os.path.isfile(filename) and overwrite is False:
            raise FileExistsError("[%s] file already exists without overwrite flag", filename)
        self._filename = filename
        self._wb = openpyxl.Workbook()
        self._wb.save(filename)  # Can raise PermissionError

    def _get_sheet_by_name(self, ws_name: str, read: bool = False, ws_details: TableFormat = None):
        """
        Creates sheet if doesn't exist
        :param ws_name:
        :param read:
        :param ws_details:
        :return:
        """
        try:
            sheet = self._wb[ws_name]
        except KeyError as e:
            if read:
                raise e
            else:
                try:
                    sheet = self._wb.get_sheet_by_name('Sheet')
                    sheet.title = ws_name
                except KeyError:
                    sheet = self._wb.create_sheet(title=ws_name,
                                                  index=ws_details.sheet_position)
                    if ws_details.formatters.sheet_props is not None:
                        sheet.sheet_properties = ws_details.formatters.sheet_props

        return sheet

    def update_sheet_1(self, sheet_nm, datalst):
        data = get_data('test.xlsx')
        data.update({sheet_nm: datalst})
        save_data('test.xlsx', data)

    def update_sheet(self, sheet_nm, columns, data, tf):
        """
        Create or Update excel sheet with db data and cf.
        :param sheet_nm: sheet name
        :param columns: column names
        :param data: Database data that needs to be exported
        :param tf: Table cf. Can be None
        :param cf: Column cf - has all the columns. Can be None
        :return:
        """
        logging.debug('Creating/Updating name [%s]', sheet_nm)
        if not columns or not data:
            logging.error('[%s] required but received None' % ('columns' if not columns else 'data'))

        sheet = self._get_sheet_by_name(ws_name=sheet_nm, read=False, ws_details=tf)
        sheet.append(columns)
        if len(data) <= 0:
            logging.error('No values to insert for [%s]', sheet_nm)
            sheet["$1$1"].comment = "No data available for insert"
        else:
            for d in data:
                sheet.append(d)
            for col in columns:
                cf = tf.get_column(col, default=True)

                sheet.column_dimensions[cf.column_number].width = cf.formatters.width
                if cf.formatters.comment:
                    sheet["${0}$1".format(cf.column_number)].comment = cf.formatters.comment
                cr = cf.formatters.reference
                if cr is not None:
                    dv = DataValidation(type="list",
                                        formula1="{0}!{1}:{2}".format(quote_sheetname(cr.sheet_name),
                                                                      cr.startcell,
                                                                      cr.endcell))
                    dv.add('{0}2:{0}{1}'.format(cf.column_number, len(data)))
                    sheet.add_data_validation(dv)
                if tf.formatters.alignment.wrapText is True:
                    for cell in sheet[cf.column_number]:
                        cell.alignment = Alignment(wrapText=True)

            # Other Worksheet level settings
            sheet.alignment = tf.formatters.alignment
            sheet.freeze_panes = tf.formatters.freeze_panes
            sheet.add_table(openpyxl.worksheet.table.Table(ref="%s" % sheet.dimensions,
                                                   displayName=sheet_nm.replace(" ", ""),
                                                   tableStyleInfo=tf.formatters.table_style_info))
        self._wb.save(self._filename)
        return


    # def update_sheet_ori(self, ws_details: TableFormat, datadict):
    #     sheet_name = ws_details.get_tablename()
    #     logging.debug('Creating/Updating name [%s]', sheet_name)
    #     if len(datadict) <= 0:
    #         logging.error('No values to insert for [%s]', sheet_name)
    #         return
    #
    #     column_nms = self.get_column_names(datadict[0])
    #     if column_nms is None:
    #         raise Exception("Couldn't retrieve columns from sheet [{0}".format(sheet_name))
    #
    #     sheet = self._get_sheet_by_name(ws_name=sheet_name, read=False, ws_details=ws_details)
    #     sheet.append(list(column_nms))
    #
    #     row_no = 1
    #     for row in datadict:
    #         row_no += 1
    #         sheet.append([v for k, v in row.items()]) if isinstance(row, dict) \
    #             else sheet.append([v for k, v in vars(row).items() if k != '_state'])
    #
    #     # Adjusting column and cell settings.
    #     count = 1
    #     column_letter = 'A'
    #     for col in column_nms:
    #         setting = ws_details.get_column(col)
    #         if count <= 26:
    #             column_letter: str = chr(64 + count)
    #         else:
    #             column_letter: str = chr(64 + int(count / 26)) + chr(
    #                 64 + (int(count % 26) if int(count % 26) != 0 else 1))
    #         self.style_column(sheet, column_letter, setting)
    #         count += 1
    #
    #     last_column = column_letter
    #
    #     # Add table style to the data
    #     medium_style: TableStyleInfo = openpyxl.worksheet.table.TableStyleInfo(name='TableStyleMedium2',
    #                                                                            showRowStripes=True,
    #                                                                            showLastColumn=False)
    #     table = openpyxl.worksheet.table.Table(ref="%s" % sheet.dimensions,
    #                                            displayName=sheet_name.replace(" ", ""),
    #                                            tableStyleInfo=medium_style)
    #
    #     # Other Worksheet level settings
    #     sheet.alignment = Alignment(horizontal="justify", wrapText=True)
    #     sheet.freeze_panes = "A2"
    #     # try out what is the value shown by sheet.dimensions
    #
    #     sheet.add_table(table)
    #     self._wb.save(self._filename)

    # @staticmethod
    # def get_column_names(datadict):
    #     """
    #     TODO: HG: Standardize this function -- pass django class, and rename to django_class_columns()
    #     Creates columns with name as found in dictionary
    #     :param datadict: dictionary with column names
    #     :return:
    #     """
    #     if isinstance(datadict, dict):
    #         return datadict.keys()
    #     else:
    #         try:
    #             col_names = vars(datadict).copy()
    #             col_names.pop('_state')
    #             return col_names.keys()
    #         except KeyError as e:
    #             logging.error("error retrieving [_state] key. Exception [%s]", e)
    #             return None

    # @staticmethod
    # def style_column(ws: Worksheet, column_letter: str, cf):
    #     """
    #     Wrap all cells in column
    #     :param ws:
    #     :param column_letter:
    #     :param cf:
    #     :return:
    #     """
    #     ws.column_dimensions[column_letter].width = cf.width
    #     if cf.comment:
    #         ws["${0}$1".format(column_letter)].comment = cf.comment
    #     cr = cf.reference
    #     if cr is not None:
    #         dv = DataValidation(type="list",
    #                             formula1="{0}!{1}:{2}".format(quote_sheetname(cr.sheet_name),
    #                                                           cr.startcell,
    #                                                           cr.endcell))
    #         dv.add('{0}2:{0}{1}'.format(column_letter, len(ws[column_letter])))
    #         ws.add_data_validation(dv)
    #     col_metadata = dict(startcell="${0}$2".format(column_letter),
    #                         endcell="${0}${1}".format(column_letter, len(ws[column_letter])))
    #     cf.update_sheet_metadata(col_metadata)
    #     if cf.wrap is True:
    #         for cell in ws[column_letter]:
    #             cell.alignment = Alignment(wrapText=True)
