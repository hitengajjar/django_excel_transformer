class ColRef(object):
    START_CELL = 'startcell'
    END_CELL = 'endcell'

    def __init__(self, tablename: str, column_settings):
        tablename.strip()
        self.sheet_name = tablename  # table.get_tablename()
        self.startcell = column_settings.get_sheet_metadata()[ColRef.START_CELL]
        self.endcell = column_settings.get_sheet_metadata()[ColRef.END_CELL]


class ColFormat(object):
    DEFAULT_WIDTH = 10
    DEFAULT_WRAP = True

    def __init__(self, column_nm: str, **args):
        argkeys = args.keys()
        self.column_nm = column_nm
        self.width = args["width"] if "width" in argkeys else ColFormat.DEFAULT_WIDTH
        self.wrap = args["wrap"] if "wrap" in argkeys else ColFormat.DEFAULT_WRAP
        self.comment = args["comment"] if "comment" in argkeys else None
        self.reference: ColRef = args[
            "reference"] if "reference" in argkeys else None
        self.dataref: dict = args["sheet_metadata"] if "sheet_metadata" in argkeys else None
        if self.dataref is None:
            self.dataref = {ColRef.START_CELL: '$B$2', ColRef.END_CELL: '$B$2'}

    def update_sheet_metadata(self, metadata: dict):
        """ Helper function that holds references within sheet for this column
        e.g. data starting cell, data ending cell etc"""
        self.dataref = metadata

    def get_sheet_metadata(self):
        return self.dataref

    @classmethod
    def get_defaultcolumn(cls, column: str):
        return cls(column, width=ColFormat.DEFAULT_WIDTH, wrap=ColFormat.DEFAULT_WRAP)


class TableFormat(object):
    """ Provides default formatting as well as provides registered class formatting
    """
    # Below COLUMN_* are assumed to be default columns each tables would have.
    # Non-required columns wouldn't be used hence no harm.
    COLUMN_ID = 'id'
    COLUMN_NM = 'name'
    COLUMN_DESC = 'description'
    COLUMN_ORDER = 'order'

    # TODO: HG:
    ''' a
        1. Check how we can use various Worksheet properties
            # https://openpyxl.readthedocs.io/en/stable/worksheet_properties.html
            >>> wsprops = ws.sheet_properties
            >>> wsprops.tabColor = "1072BA"
            >>> wsprops.filterMode = False
            >>> wsprops.pageSetUpPr = PageSetupProperties(fitToPage=True, autoPageBreaks=False)
            >>> wsprops.outlinePr.summaryBelow = False
            >>> wsprops.outlinePr.applyStyles = True
            >>> wsprops.pageSetUpPr.autoPageBreaks = True

        2. We also need to add more data validation forumals to the sheet as explained at 
        https://www.contextures.com/xlDataVal07.html - These validations will be part of ColumnFormatter or best 
        would be ColumnReference '''

    def __init__(self, tablename: str, sheet_pos=None, sheet_properties: WorksheetProperties = None,
                 table: dict = None):
        tablename = tablename.strip()
        self.table_nm = tablename
        self.sheet_pos = sheet_pos  # Sheet positions are just indicative and not guaranteed.
        self.sheet_properties = sheet_properties
        if not table:
            table = TableFormat.get_defaulttable()
        else:
            # Ensure all keys are in lower case without leading or trailing spaces.
            table1 = {}
            for (k, v) in table.items():
                k = k.strip()
                table1[k.lower()] = v
            table = table1
        self.table = table

    def reg_col(self, column_settings: ColFormat = None):
        """ Registers column settings like width value, wrap enabled?, if data is referenced in other sheets
        Method chaining pattern used """
        if column_settings is None:
            raise ValueError("column_settings cannot be None")
        column_nm = column_settings.column_nm.strip()
        column_nm = column_nm.lower()
        column_settings.column_nm = column_nm
        self.table[column_nm] = column_settings
        return self

    def reg_cols_samesettings(self, col_names: list, column_setting: ColFormat):
        """ Helper function to register multiple columns with same settings
        Follows Method chaining pattern
        """
        for column_nm in col_names:
            self.reg_col(ColFormat(column_nm, width=column_setting.width, wrap=column_setting.wrap))
        return self

    def reg_cols(self, columns: list):
        """ Helper function to register multiple columns with same settings
        Follows Method chaining pattern
        """
        for column in columns:
            self.reg_col(column)
        return self

    def get_tablename(self):
        return self.table_nm

    def update_table(self, columns: [ColFormat]):
        for column_setting in columns:
            column_nm = column_setting.get_columnname()
            column_nm = column_nm.strip()
            column_setting.column_nm = column_nm.lower()
            self.table[column_nm.lower()] = column_setting

    def get_column(self, col: str) -> ColFormat:
        """ Returns column formatting with registered values else returns default """
        try:
            col = col.strip()
            return self.table[col.lower()]
        except KeyError:
            return ColFormat.get_defaultcolumn(col.lower())

    @staticmethod
    def get_defaulttable() -> dict:
        """ Returns commonly available cell formatting """
        return {
            TableFormat.COLUMN_ID: ColFormat(TableFormat.COLUMN_ID),
            TableFormat.COLUMN_NM: ColFormat(TableFormat.COLUMN_NM, width=20),
            TableFormat.COLUMN_DESC: ColFormat(TableFormat.COLUMN_DESC, width=50),
            TableFormat.COLUMN_ORDER: ColFormat(TableFormat.COLUMN_ORDER)
        }

    def set_tablename(self, tablename):
        self.table_nm = tablename
        pass
