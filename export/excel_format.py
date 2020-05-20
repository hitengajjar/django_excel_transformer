import logging

import openpyxl
from box import Box
from openpyxl.styles import Alignment
from openpyxl.worksheet.properties import WorksheetProperties
from enum import Enum
import attr
from openpyxl.worksheet.table import TableStyleInfo

from ..common import lower, val, defval_dict, Registry


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
        raise PermissionError("Cannot create object of %s" % cls)

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
        # TODO: HG: See how we can fetch validation from common Registry and update excel_val?
        if ref_data is None or len(ref_data) > 1:
            logging.info("Received invalid ref_data [%s]. Excel expects only one sheet.column for datavalidation. Ignoring!" % (ref_data))
            return None

        es = Registry.exporter.get_sheet_by_model(ref_data[0][0])
        if not es:
            logging.error("Reference [%s] either doesn't exist or isn't exported yet, hence no reference available. Ignoring!" % (' - '.join(ref_data[0])))
            return None

        col_format = es.get_formatting().get_column(lower(ref_data[0][1]))
        if not col_format:
            logging.error("Reference [%s] is not available. Ignoring!" % (' - '.join(ref_data[0])))
            return None

        return ColRef(name=es.sheet_name,
                      startcell="${0}$2".format(col_format.column_number),
                      endcell="${0}${1}".format(col_format.column_number, len(es.dbdata)+1))

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
        formatters = Box(default_box=True)
        user_formatting_config = defval_dict(col_data, 'formatting', None)
        formatters.width = defval_dict(user_formatting_config, "width", ColFormat.DEFAULT_WIDTH)
        formatters.wrap = defval_dict(user_formatting_config, "wrap", ColFormat.DEFAULT_WRAP)
        formatters.read_only = defval_dict(user_formatting_config, "read_only", ColFormat.DEFAULT_RO)
        formatters.comment = defval_dict(user_formatting_config, "comment", None)
        tmp_ref = defval_dict(col_data, "references", None)
        formatters.reference = ColRef.from_registry(tmp_ref) if tmp_ref else None
        return cls(name=name, type=FormatType.COLUMN, formatters=formatters,
                  column_number=defval_dict(col_data, 'column_number', 'A'))

    def update_excel_val(self, excel_val: dict):
        self.excel_val = excel_val


@attr.s
class TableFormat(Formatter):
    # various Worksheet properties https://openpyxl.readthedocs.io/en/stable/worksheet_properties.html
    # TODO: HG: more data validation forumals to the sheet as explained at https://www.contextures.com/xlDataVal07.html

    # DEFAULT_SHEET_POSITION = 1
    DEFAULT_FREEZE_PANE = "A2"
    DEFAULT_HORIZONTAL_ALIGNMENT = 'justify'
    DEFAULT_WRAP_TEXT = True
    DEFAULT_READONLY = False

    columns = attr.ib(validator=attr.validators.instance_of(Box))  # Box of ColFormat
    last_column_number = attr.ib(validator=attr.validators.instance_of(str))
    sheet_position = attr.ib(default=None)

    @classmethod
    def from_dict(cls, name: str, t_fmting=None, c_fmting=None):
        if t_fmting is None:
            t_fmting = Box(default_box=True)

        def get_tbl_style(ts_dict: Box) -> openpyxl.worksheet.table.TableStyleInfo:
            # Helper function to fill up table style
            if ts_dict:
                t_tbl_style = TableStyleInfo(name='TableStyleMedium')  # Default name
                key_mapper = {'name': 'name', 'show_first_column': 'showFirstColumn',
                              'show_last_column': 'showLastColumn', 'show_row_stripes': 'showRowStripes',
                              'show_column_stripes': 'showColumnStripes'}
                for f in ts_dict.keys() & key_mapper.keys():
                    setattr(t_tbl_style, key_mapper[f], ts_dict[f])
                return t_tbl_style
            else:
                return None

        def get_sheet_alignment(align_dict: Box):
            align = Alignment()
            align.horizontal = defval_dict(align_dict, 'horizontal', TableFormat.DEFAULT_HORIZONTAL_ALIGNMENT)
            align.wrap_text = defval_dict(align_dict, 'wrap_text', TableFormat.DEFAULT_WRAP_TEXT)
            return align

        formatters = Box(default_box=True)
        formatters.table_style_info = get_tbl_style(defval_dict(t_fmting, "table_style", Box(default_box=True)))
        formatters.locked = defval_dict(t_fmting, "read_only", TableFormat.DEFAULT_READONLY)
        formatters.alignment = get_sheet_alignment(defval_dict(t_fmting, "alignment", Box(default_box=True)))
        formatters.freeze_panes = defval_dict(t_fmting, "freeze_panes", TableFormat.DEFAULT_FREEZE_PANE)

        sheet_props = WorksheetProperties()
        for f in {"tabColor", "filterMode"} & t_fmting.keys():
            setattr(sheet_props, f, t_fmting[f])
        formatters.sheet_props = sheet_props

        obj = cls(name=name, type=FormatType.TABLE, formatters=formatters,
                  columns=Box(default_box=True), last_column_number='A',
                  sheet_position=defval_dict(t_fmting, "position", None))
        count = 1
        column_number = 'A'
        for col_nm, col_data in c_fmting.items():  # handle columns
            column_number = chr(64 + count) if count <= 26 else \
                chr(64 + int(count / 26)) + chr(64 + (int(count % 26) if int(count % 26) != 0 else 1))
            col_data['column_number'] = column_number
            count += 1
            obj.reg_col(ColFormat.from_dict(col_nm, col_data))

        obj.last_column_number = column_number

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
