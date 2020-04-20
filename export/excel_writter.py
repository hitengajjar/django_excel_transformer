import logging
import os
import openpyxl
from box import Box
from openpyxl.styles import Alignment
from openpyxl.utils import quote_sheetname
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from panopticum.panopticum.models import User
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
                                                  index=ws_details.sheet_pos)
                    if ws_details.sheet_properties is not None:
                        sheet.sheet_properties = ws_details.sheet_properties

        return sheet

    def update_sheet(self, ws_details: TableFormat, datadict):
        sheet_name = ws_details.get_tablename()
        logging.debug('Creating/Updating sheet_name [%s]', sheet_name)
        if len(datadict) <= 0:
            logging.error('No values to insert for [%s]', sheet_name)
            return

        column_nms = self._create_column_names(datadict[0])
        if column_nms is None:
            raise Exception("Couldn't retrieve columns from sheet [{0}".format(sheet_name))

        sheet = self._get_sheet_by_name(ws_name=sheet_name, read=False, ws_details=ws_details)
        sheet.append(list(column_nms))

        row_no = 1
        for row in datadict:
            row_no += 1
            sheet.append([v for k, v in row.items()]) if isinstance(row, dict) \
                else sheet.append([v for k, v in vars(row).items() if k != '_state'])

        # Adjusting column and cell settings.
        count = 1
        column_letter = 'A'
        for col in column_nms:
            setting = ws_details.get_column(col)
            if count <= 26:
                column_letter: str = chr(64 + count)
            else:
                column_letter: str = chr(64 + int(count / 26)) + chr(
                    64 + (int(count % 26) if int(count % 26) != 0 else 1))
            self._style_column(sheet, column_letter, setting)
            count += 1

        last_column = column_letter

        # Add table style to the data
        medium_style: TableStyleInfo = openpyxl.worksheet.table.TableStyleInfo(name='TableStyleMedium2',
                                                                               showRowStripes=True,
                                                                               showLastColumn=False)
        table = openpyxl.worksheet.table.Table(ref="A1:{0}{1}".format(last_column, row_no),
                                               displayName=sheet_name.replace(" ", ""),
                                               tableStyleInfo=medium_style)

        # Other Worksheet level settings
        sheet.alignment = Alignment(horizontal="justify", wrapText=True)
        sheet.freeze_panes = "A2"
        # try out what is the value shown by sheet.dimensions

        sheet.add_table(table)
        self._wb.save(self._filename)

    @staticmethod
    def _create_column_names(datadict):
        """
        TODO: HG: Standardize this function -- pass django class, and rename to django_class_columns()
        Creates columns with name as found in dictionary
        :param datadict: dictionary with column names
        :return:
        """
        if isinstance(datadict, dict):
            return datadict.keys()
        else:
            try:
                col_names = vars(datadict).copy()
                col_names.pop('_state')
                return col_names.keys()
            except KeyError as e:
                logging.error("error retrieving [_state] key. Exception [%s]", e)
                return None

    @staticmethod
    def _style_column(ws: Worksheet, column_letter: str, formatting):
        """
        Wrap all cells in column
        :param ws:
        :param column_letter:
        :param formatting:
        :return:
        """
        ws.column_dimensions[column_letter].width = formatting.width
        if formatting.comment:
            ws["${0}$1".format(column_letter)].comment = formatting.comment
        cr = formatting.reference
        if cr is not None:
            dv = DataValidation(type="list",
                                formula1="{0}!{1}:{2}".format(quote_sheetname(cr.sheet_name),
                                                              cr.startcell,
                                                              cr.endcell))
            dv.add('{0}2:{0}{1}'.format(column_letter, len(ws[column_letter])))
            ws.add_data_validation(dv)
        col_metadata = dict(startcell="${0}$2".format(column_letter),
                            endcell="${0}${1}".format(column_letter, len(ws[column_letter])))
        formatting.update_sheet_metadata(col_metadata)
        if formatting.wrap is True:
            for cell in ws[column_letter]:
                cell.alignment = Alignment(wrapText=True)

class Exporter(object):
    xlsdoc: XlsWriter

    def __init__(self, xlsdoc, opr=None):
        self.xlsdoc = xlsdoc
        self._opr = opr  # TODO: HG: Use this effectively
        pass

    @staticmethod
    def _create_multientry_str(iterables):
        tmp_str: str = ""
        if isinstance(iterables, list):
            for i in iterables:
                tmp_str += "* " + i + "\n"
        else:  # TODO: HG: Check object type
            for d in iterables.all() if iterables is not None else []:
                tmp_str += "* " + d.name + "\n"
        return tmp_str[:-1]  # remove last character '\n'

    @staticmethod
    def _create_email_str(person: User) -> str:
        """ Returns formatted Person object in format "firstname lastname <email@address>" """
        return (person.first_name
                + " "
                + person.last_name
                + " <"
                + person.email
                + ">") if person is not None else ""

    def _create_multiemail_str(self, people):
        """ Returns multiple formatted Person objects. It uses _create_email_str() function defined above"""
        tmp_str: str = ""
        for d in people.all() if people is not None else []:
            tmp_str += "* " + self._create_email_str(d) + ";" + "\n"
        return tmp_str[:-2]  # remove last character ','



    def export_data(self, mapper):
        def get_table_formatter(sheet, defaults) -> Box:
            t_fmt = TableFormat(sheet.sheet_name, sheet_pos=1)
            t_style = Box(default_box=True)
            t_style.tabColor = None
            t_style.read_only = True
            t_style.table_style = openpyxl.worksheet.table.TableStyleInfo(name='TableStyleMedium2',
                                                                               showRowStripes=True,
                                                                               showLastColumn=False)

            def get_tbl_style(t_style: Box, fmt):
                # Helper function to fill up table style
                t_tbl_style = {}
                if 'tab_color' in fmt:
                    t_style.tabColor = fmt.tab_color
                if 'read_only' in fmt:
                    t_style.read_only = False if fmt['read_only'] == 'false' else True
                if 'table_style' in fmt:
                    tbl_style = fmt.table_style
                    tbl_style_keys = tbl_style.keys() & set(
                        ['name', 'show_first_column', 'show_last_column', 'show_row_stripes', 'show_column_stripes'])
                    for f in tbl_style_keys:
                        t_tbl_style[f] = tbl_style[f]

                    t_style.table_style = t_tbl_style
                return t_style
            if defaults and 'formatting' in defaults:
                t_style = get_tbl_style(t_style, defaults.formatting)
            if sheet and 'formatting' in sheet:
                t_style = get_tbl_style(t_style, sheet.formatting)
            return t_style

        def get_column_formatter(data, defaults):
            c_style = Box(default_box=True)
            c_style.chars_wrap = 20
            c_style.comment = Box(default_box=True,
                                  text = '', author = 'admin@github.com', height_len=110, width_len=230)
            def get_tbl_style(c_style: Box, data):
                # Helper function to fill up table style
                if 'chars_wrap' in data:
                    c_style.chars_wrap = data.chars_wrap
                if 'comment' in data:
                    comment_keys = data.comment.keys() & set(
                        ['text', 'author', 'height_len', 'width_len'])
                    for f in comment_keys:
                        c_style.comment[f] = comment_keys[f]
                return c_style

        for model_nm in reversed([k for k in mapper.sheets.keys()]):
            sheet = mapper.sheets[model_nm]
            t_style = get_table_formatter(sheet, mapper.defaults)
            table_fmt = TableFormat(sheet.sheet_name, sheet_pos=1)
            if 'tabColor' in t_style:
                table_fmt = t_style.tabColor
            for f in sheet.dataset_obj.data:
                c_style = get_column_formatter(f.formatter, mapper.defaults.data)
                table_fmt.reg_col(c_style)
            self.xlsdoc.update_sheet(table_fmt, )  # TODO:HG: Resume from here.


