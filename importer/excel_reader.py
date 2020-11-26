import logging
import openpyxl

from box import Box
from openpyxl.worksheet.worksheet import Worksheet
from .validator import Validator


class XlsReader:
    def __init__(self, filename):
        self._wb = openpyxl.load_workbook(filename, data_only=True)
        self.validator = Validator()

    def get_xl_table(self, ws: Worksheet):
        xl_table = Box(default_box=True)
        xl_table.headers = []
        xl_table.rows = []

        for row in ws.iter_rows():
            if row[0].value is None or str(row[0].value).strip() == "":
                break
            if xl_table.headers:
                xl_table.rows.append(row)
            else:
                xl_table.headers = row

        return xl_table

    def get_xldata(self, sheet_nm, index_keys) -> Box:
        table = self.get_xl_table(self._wb[sheet_nm])

        self.validator.xl_index_keys(table.headers, index_keys)

        logging.debug("Loading sheet [%s]", sheet_nm)
        datadict = Box(default_box=True)
        idx = None

        for row in table.rows:
            idx = ""
            xl_row = {}
            for col_num, col_title in enumerate(table.headers):
                col_title = col_title.value.strip()
                if col_title != "id":  # not interested in "id" column
                    if col_title in index_keys:
                        idx = row[col_num].value.strip() if idx is "" else idx + ' - ' + row[
                            col_num].value.strip()
                    xl_row[col_title] = row[col_num].value
            datadict[idx] = xl_row
            # logging.debug(f"xlsrow {datadict[idx]}")
        return datadict
