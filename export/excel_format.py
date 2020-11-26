import logging
from typing import Optional

import openpyxl
from box import Box
from openpyxl.styles import Alignment
from openpyxl.worksheet.properties import WorksheetProperties
from openpyxl.comments import Comment
from enum import Enum
import attr
from openpyxl.worksheet.table import TableStyleInfo

from ..common import lower, Registry


class FormatType(Enum):
    TABLE = 1
    COLUMN = 2

@attr.s
class Formatter:
    name = attr.ib(validator=attr.validators.instance_of(str))
    type = attr.ib(validator=attr.validators.instance_of(FormatType))
    formatters = attr.ib(validator=attr.validators.instance_of(Box))

    @staticmethod
    def default(class_name, name):
        return class_name.from_dict(name)

    @classmethod
    def from_dict(cls, name: str, data: Box):
        raise PermissionError(f'Cannot create object of {cls}')

@attr.s
class ColRef(object):
    START_CELL = 'startcell'
    END_CELL = 'endcell'
    name = attr.ib(validator=attr.validators.instance_of(str))
    startcell = attr.ib(validator=attr.validators.instance_of(str))
    endcell = attr.ib(validator=attr.validators.instance_of(str))

    @property
    def sheet_name(self):
        return self.name

    @classmethod
    def from_registry(cls, ref_data):
        """
        Receives ref_data as provided by Parser and will convert to ColRef type.
        It needs to access Registry -> Ref sheet Exporter -> TableFormatter -> ColFormatter
        :param ref_data: reference data if exists
        :return: ColRef instance
        """
        if ref_data is None or len(ref_data) > 1:
            logging.info(f'Received invalid ref_data [{ref_data}]. Excel expects only one sheet.column for '
                         f'datavalidation. Ignoring!')
            return None

        es = Registry.exporter.get_sheet_by_model(ref_data[0][0])
        if not es:
            logging.error(
                f'Reference [{" - ".join(ref_data[0])}] either doesnt exist or isnt exported yet, hence no reference available. Ignoring!')
            return None

        col_format = es.get_formatting().get_column(lower(ref_data[0][1]))
        if not col_format:
            logging.error(f'Reference [{" - ".join(ref_data[0])}] is not available. Ignoring!')
            return None

        return ColRef(name=es.sheet_name,
                      startcell=f'${col_format.column_number}$2',
                      endcell=f'${col_format.column_number}${len(es.dbdata) + 1}')


@attr.s
class ColFormat(Formatter):
    DEFAULT_WIDTH = 10
    DEFAULT_RO = False
    DEFAULT_WRAP = True

    column_number = attr.ib(validator=attr.validators.instance_of(str))

    @classmethod
    def from_dict(cls, name: str, col_data=None):
        if col_data is None:
            col_data = Box(default_box=True)
        formatters = Box(default_box=True, width=ColFormat.DEFAULT_WIDTH, wrap=ColFormat.DEFAULT_WRAP,
                         read_only=ColFormat.DEFAULT_RO)
        if 'formatting' in col_data:
            col_data_fmtting = col_data.get('formatting')
            formatters.width = col_data_fmtting.get('chars_wrap', ColFormat.DEFAULT_WIDTH)
            formatters.wrap = col_data_fmtting.get('wrap', ColFormat.DEFAULT_WRAP)
            formatters.locked = col_data_fmtting.get('read_only', ColFormat.DEFAULT_RO)
            formatters.dv = col_data_fmtting.get('dv', False)
            comment = col_data_fmtting.get('comment', None)
            if comment:
                formatters.comment = Comment(text=comment.text, author=comment.author, width=comment.width_len, height=comment.height_len)

        tmp_ref = col_data.get('references', None)
        if tmp_ref:
            formatters.reference = ColRef.from_registry(tmp_ref) if tmp_ref else None
        return cls(name=name, type=FormatType.COLUMN, formatters=formatters,
                   column_number=col_data.get('column_number', 'A'))

    def update_excel_val(self, excel_val: dict):
        self.excel_val = excel_val


@attr.s
class TableFormat(Formatter):
    # various Worksheet properties https://openpyxl.readthedocs.io/en/stable/worksheet_properties.html
    # TODO: HG: more data validation forumals to the sheet as explained at https://www.contextures.com/xlDataVal07.html

    # DEFAULT_SHEET_POSITION = 1
    DEFAULT_FREEZE_PANE = 'A2'
    DEFAULT_HORIZONTAL_ALIGNMENT = 'justify'
    DEFAULT_WRAP_TEXT = True
    DEFAULT_READONLY = False

    columns = attr.ib(validator=attr.validators.instance_of(Box))  # Box of ColFormat
    # last_column_number = attr.ib(validator=attr.validators.instance_of(str))
    sheet_position = attr.ib(default=-1)

    @classmethod
    def from_dict(cls, name: str, t_fmting=None, c_fmting=None):
        if t_fmting is None:
            t_fmting = Box(default_box=True)
        if c_fmting is None:
            c_fmting = Box(default_box=True)

        def get_tbl_style(ts_dict: Box) -> Optional[TableStyleInfo]:
            # Helper function to fill up table style
            if ts_dict:
                t_tbl_style = TableStyleInfo(name='TableStyleMedium2')  # Default name
                key_mapper = {'name': 'name', 'show_first_column': 'showFirstColumn',
                              'show_last_column': 'showLastColumn', 'show_row_stripes': 'showRowStripes',
                              'show_column_stripes': 'showColumnStripes'}
                for f in ts_dict.keys() & key_mapper.keys():
                    setattr(t_tbl_style, key_mapper[f], ts_dict[f])
                return t_tbl_style
            else:
                return None

        def get_sheet_alignment(align_dict: Box):
            align = Alignment(horizontal=TableFormat.DEFAULT_HORIZONTAL_ALIGNMENT,
                              wrap_text=TableFormat.DEFAULT_WRAP_TEXT)
            if align_dict:
                align.horizontal = align_dict.get('horizontal', TableFormat.DEFAULT_HORIZONTAL_ALIGNMENT)
                align.wrap_text = align_dict.get('wrap_text', TableFormat.DEFAULT_WRAP_TEXT)
            return align

        formatters = Box(default_box=True)
        formatters.table_style_info = get_tbl_style(t_fmting.get('table_style', Box(default_box=True)))
        formatters.locked = t_fmting.get('read_only', TableFormat.DEFAULT_READONLY)
        formatters.alignment = get_sheet_alignment(t_fmting.get('alignment', Box(default_box=True)))
        formatters.freeze_panes = t_fmting.get('freeze_panes', TableFormat.DEFAULT_FREEZE_PANE)

        sheet_props = WorksheetProperties()
        if 'tab_color' in t_fmting:
            sheet_props.tabColor = t_fmting['tab_color']
        formatters.sheet_props = sheet_props
        sheet_position = t_fmting.get("position", -1)
        sheet_position = sheet_position - 1 if sheet_position > 0 else -1 if '*' == sheet_position else sheet_position

        obj = cls(name=name, type=FormatType.TABLE, formatters=formatters,
                  columns=Box(default_box=True), sheet_position=sheet_position)
        count = 1
        for col_nm, col_data in c_fmting.items():  # handle columns
            column_number = chr(64 + count) if count <= 26 else \
                chr(64 + int(count / 26)) + chr(64 + (int(count % 26) if int(count % 26) != 0 else 1))
            col_data['column_number'] = column_number
            count += 1
            col_obj = ColFormat.from_dict(col_nm, col_data)
            obj.reg_col(col_obj)
            # if col_obj.formatters.locked:
            #     obj.formatters.locked = True
        # obj.last_column_number = column_number
        return obj

    def reg_col(self, col_data: ColFormat = None):
        """ Registers column settings like width value, wrap enabled?, if data is referenced in other sheets
        Method chaining pattern used """
        if col_data is None:
            raise ValueError("column cannot be None")
        self.columns[lower(col_data.name)] = col_data
        return self

    def get_column(self, col_name: str, default=False) -> ColFormat:
        """ Returns column cf with registered values else returns default """
        return self.columns[lower(col_name)] if lower(col_name) in self.columns \
            else Formatter.default(ColFormat, col_name) if default \
            else None
